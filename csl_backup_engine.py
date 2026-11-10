"""Manual encrypted backup engine. No timers, pruning, model turns or auth changes."""

import datetime as dt
import contextlib
import json
from pathlib import Path
import shutil
import sys
import time
import tempfile
from types import SimpleNamespace
import uuid
import zipfile

import csl_backup_format as fmt
from csl_backup_core import (BackupBusy, MAX_MANIFEST, MAX_OBJECT, NORMAL_CONTAINER, NAMESPACE,
    canonical, capture, header_source, zip_digest, zip_extract, hash_bytes, hash_file, json_read, locked, now, save, source_kind, uid, zip_preflight, zip_read)
from csl_backup_crypto import BackupPolicyError
from csl_backup_store import Control
from csl_secrets import SecretReview
from csl_transfer import (TransferError, export_bundle, inspect_bundle, json_line,
    publish_session_file, read_records, refresh_native_picker, rewrite_import_record, validate_compaction)
from csl_display import project_file


CAPTURE_BUDGET = 2 * 1024**3
SOURCE_ENTRY_BUDGET = 10000


class Backup:
    def __init__(self, csl, github, age):
        self.csl, self.github, self.age = csl, github, age
        self.home = csl.DEFAULT_CODEX_HOME
        self.root = self.home / "csl-backup"
        self.control = Control(github)

    def load(self, set_id, source_id=None):
        path = self.root / "sets" / (uid(set_id) + ".json")
        if source_id and (self.root / "sets" / set_id / (uid(source_id) + ".json")).exists():
            path = self.root / "sets" / set_id / (source_id + ".json")
        elif not source_id and any((self.root / "sets" / set_id).glob("*.json")):
            raise TransferError("Multiple locally configured sources; select --source explicitly")
        value = fmt.config(json_read(path))
        if source_id is not None and value["source_id"] != source_id:
            raise TransferError("Explicit source differs from local configuration")
        if value["repo_id"] != self.github.repo_id:
            raise TransferError("Configured backup repo ID differs")
        return value

    def initialize(self, *, set_name, source_name, profile, policy, recipients, key_reference,
                   retain_accepted=False, include_agents=False, set_id=None):
        with locked(self.root):
            return self._initialize(set_name=set_name, source_name=source_name, profile=profile, policy=policy,
                recipients=recipients, key_reference=key_reference, retain_accepted=retain_accepted,
                include_agents=include_agents, set_id=set_id)

    def _initialize(self, *, set_name, source_name, profile, policy, recipients, key_reference,
                    retain_accepted=False, include_agents=False, set_id=None):
        if any(not isinstance(name, str) or not 0 < len(name) <= 80 for name in (set_name, source_name)):
            raise TransferError("Backup set/source labels must contain 1 to 80 characters")
        if set_id is not None:
            uid(set_id)
            _, state = self.control.read()
            if set_id not in state["sets"]:
                raise TransferError("Explicit set must already exist remotely; no implicit source adoption")
        value = {"format": "csl-backup-config", "schema_version": 1,
            "repo": self.github.repo, "repo_id": self.github.repo_id,
            "set_id": set_id or str(uuid.uuid4()), "source_id": str(uuid.uuid4()),
            "set_name": set_name, "source_name": source_name,
            "profile": profile, "secret_policy": policy, "recipients": self.age.recipients(recipients),
            "key_reference": key_reference, "retain_accepted": retain_accepted,
            "agent_forks": include_agents, "created_at": now()}
        fmt.config(value)
        if not self.github.metadata.get("permissions", {}).get("push"):
            raise TransferError("Backup init requires existing repository write permission")
        desired = {k: v for k, v in value.items() if k not in ("set_id", "source_id", "created_at")}
        for path in (self.root / "sets").rglob("*.json"):
            existing = fmt.config(json_read(path))
            if set_id is not None:
                if existing["set_id"] != set_id or existing["source_name"] != source_name:
                    continue
            elif existing["set_name"] != set_name:
                continue
            compared = {k: v for k, v in existing.items() if k not in ("set_id", "source_id", "created_at")}
            if desired != compared:
                raise TransferError("Backup set label already has different configuration; no silent second source or profile change")
            return {"set_id": existing["set_id"], "source_id": existing["source_id"], "repo_id": existing["repo_id"],
                    "status": "already configured; no backup captured or timer enabled"}
        path = (self.root / "sets" / value["set_id"] / (value["source_id"] + ".json") if set_id is not None
                else self.root / "sets" / (value["set_id"] + ".json"))
        save(path, value, exclusive=True)
        return {"set_id": value["set_id"], "source_id": value["source_id"], "repo_id": value["repo_id"],
                "status": "configured; no backup captured or timer enabled"}

    def _lease(self, config, run_id, *, checkpoint=None, catalog_binding=None, intents=None,
               acquire=False, expected_epoch=None, base_checkpoint=None, source_base=..., partial=False, run_binding=None):
        def mutate(state, clock):
            if config["set_id"] not in state["sets"] and not acquire:
                raise BackupBusy("Backup lease no longer registered")
            item = state["sets"].setdefault(config["set_id"], {"epoch": 0, "owner": "", "expires": 0,
                "sources": {}, "intents": []})
            source = item["sources"].setdefault(config["source_id"], {"latest_complete": None, "latest_partial": None})
            if acquire:
                if expected_epoch is not None:
                    if item["epoch"] != expected_epoch:
                        raise BackupBusy("Resume lost its expected epoch; cannot acquire")
                    registered = item.get("runs", {}).get(run_id)
                    if (registered and (registered.get("source_id") != config["source_id"] or
                            registered.get("base_checkpoint") != base_checkpoint or registered.get("retired"))):
                        raise BackupBusy("Resume intention retired or misbound")
                    if not registered and item["owner"] != run_id:
                        raise BackupBusy("Resume intention no longer registered")
                    if item["owner"] not in ("", run_id) and item["expires"] > clock:
                        raise BackupBusy("Backup busy: another writer owns the remote lease")
                elif item["owner"] and item["expires"] > clock:
                    raise BackupBusy("Backup busy: another writer owns the remote lease")
                item.update(owner=run_id, epoch=item["epoch"] + 1)
            elif item["owner"] != run_id or item["epoch"] != expected_epoch or item["expires"] <= clock:
                raise BackupBusy("Writer lost lease/epoch; cannot reacquire or publish pointer")
            if base_checkpoint != source.get("latest_complete"):
                raise BackupBusy("Base checkpoint changed; old run cannot publish pointer")
            if source_base is not ... and source_base != source.get("latest_checkpoint", source.get("latest_complete")):
                raise BackupBusy("Source checkpoint changed; old run cannot publish pointer")
            item["expires"] = clock + 600
            if intents is not None:
                item["intents"] = list(intents)
            if run_binding is not None:
                previous = item.setdefault("runs", {}).get(run_id)
                if previous and previous != run_binding:
                    stable_previous = {k: v for k, v in previous.items() if k != "lease_epoch"}
                    stable_next = {k: v for k, v in run_binding.items() if k != "lease_epoch"}
                    if (stable_previous != stable_next or run_binding["lease_epoch"] != expected_epoch or
                            run_binding["lease_epoch"] <= previous["lease_epoch"]):
                        raise TransferError("Remote run intention binding differs")
                item["runs"][run_id] = run_binding
            if checkpoint:
                name = "latest_partial" if partial else "latest_complete"
                source.update({name: checkpoint, "latest_checkpoint": checkpoint, "partial_catalog" if partial else "catalog": catalog_binding,
                               "committed_at": now()})
                item.update(owner="", expires=clock, intents=[])
        return self.control.change(mutate)["sets"][config["set_id"]]["epoch"]

    def _entries(self, config, temporary):
        captures, excluded, seen, failures = [], [], set(), []
        captured_bytes, scanned = 0, 0
        for archived, folder in ((False, self.home / "sessions"), (True, self.home / "archived_sessions")):
            for source in folder.rglob("rollout-*.jsonl"):
                scanned += 1
                if scanned > SOURCE_ENTRY_BUDGET:
                    raise TransferError("Source discovery exceeds 10000 histories; no truncated checkpoint")
                try:
                    header = header_source(source)
                    if header is not None:
                        kind = source_kind(header.get("source", "cli"))
                        if kind == "noninteractive" or kind == "agent" and not config["agent_forks"]:
                            sid = header["id"]
                            if sid in seen:
                                raise TransferError("Duplicate source UUID")
                            seen.add(sid)
                            excluded.append({"origin": {"set_id": config["set_id"], "source_id": config["source_id"],
                                "provider": "codex", "source_uuid": sid},
                                "reason": "noninteractive_source" if kind == "noninteractive" else "agent_forks_not_selected"})
                            continue
                    target = temporary / ("capture-" + str(uuid.uuid4()) + ".jsonl")
                    if len(captures) >= SOURCE_ENTRY_BUDGET or captured_bytes + source.stat().st_size > CAPTURE_BUDGET:
                        raise TransferError("Backup capture/run budget exceeded before copying")
                    result = capture(source, target)
                    captured_bytes += result["bytes"]
                    sid, metadata = result["source_uuid"], result.pop("metadata")
                    if sid in seen:
                        raise TransferError("Duplicate source UUID; not choosing by modification date")
                    seen.add(sid)
                    kind = source_kind(metadata.get("source", "cli"))
                    origin = {"set_id": config["set_id"], "source_id": config["source_id"], "provider": "codex", "source_uuid": sid}
                    if kind == "noninteractive" or kind == "agent" and not config["agent_forks"]:
                        excluded.append({"origin": origin, "reason": "noninteractive_source" if kind == "noninteractive" else "agent_forks_not_selected"})
                        target.unlink()
                        continue
                    review = SecretReview(SimpleNamespace())
                    pending = set()
                    with target.open("rb") as stream:
                        for record in read_records(stream):
                            review.scan(record, "capture")
                            payload = record.get("payload", {})
                            if payload.get("type") in ("function_call", "custom_tool_call"):
                                pending.add(payload.get("call_id", "unknown"))
                            elif payload.get("type") in ("function_call_output", "custom_tool_call_output"):
                                pending.discard(payload.get("call_id"))
                    if review.findings and config["secret_policy"] == "stop":
                        raise BackupPolicyError("Backup blocked by partial secret review; configure an explicit encrypted policy")
                    losses = ["external dependencies are not captured", "global indexes/auth/config are excluded"]
                    if result["message_records"] == 0:
                        losses.append("empty/pending native state; no user/assistant message yet; restore quarantined unless separately supported")
                    source_sha = result["sha256"]
                    result["compaction_state_removed"] = False
                    if config["profile"] == "portable-age-v1":
                        if result["message_records"] == 0:
                            raise TransferError("Portable exporter cannot represent this empty/pending native session; explicitly choose native-age-v1")
                        bundle = temporary / ("portable-" + str(uuid.uuid4()) + ".zip")
                        args = SimpleNamespace(sessions=[str(target)], provider="codex", db=self.root / "lookup.sqlite",
                            to=bundle, raw=False, repair_legacy_compaction=False,
                            allow_secrets=config["secret_policy"] == "retain", scrub_secrets=config["secret_policy"] == "scrub")
                        export_bundle(args, self.csl, quiet=True, scan_secrets=config["secret_policy"] == "scrub")
                        with zipfile.ZipFile(bundle) as archive:
                            entry = inspect_bundle(archive)["sessions"][0]
                            result["compaction_state_removed"] = bool(entry.get("compaction_state_removed", False))
                            derived = temporary / ("derived-" + str(uuid.uuid4()) + ".jsonl")
                            derived.write_bytes(archive.read(entry["file"]))
                        target = derived
                        losses.extend(["JSON reserialization", "encrypted reasoning/state omitted when present"])
                        if config["secret_policy"] == "scrub":
                            losses.append("detected readable values scrubbed; coverage partial")
                    state = "archived" if archived else "agent" if kind == "agent" else "interactive"
                    fp = fmt.fingerprint(config)
                    identity = {"origin": origin, "source_sha256": source_sha, "state": state, "fingerprint": fp}
                    result.update(origin=origin, state=state, fingerprint=fp, source_sha256=source_sha,
                        version_key=hash_bytes(canonical(identity)), losses=losses, pending_tool_calls=sorted(pending),
                        bytes=target.stat().st_size, sha256=hash_file(target))
                    captures.append((target, result))
                    if len(captures) > 10000 or sum(item[1]["bytes"] for item in captures) > CAPTURE_BUDGET:
                        raise TransferError("Backup capture/run budget exceeded; no truncation")
                except BackupPolicyError:
                    raise
                except (TransferError, OSError, ValueError) as error:
                    # No path or text is recorded in the public diagnostic. The
                    # native UUID from a bounded header permits last-good binding.
                    sid = None
                    try:
                        with source.open("rb") as stream:
                            header = json.loads(stream.readline(1024**2))
                        sid = uid(header["payload"]["id"])
                    except (ValueError, KeyError, TypeError, OSError, TransferError):
                        pass
                    failures.append({"source_uuid": sid, "reason_code": type(error).__name__})
        distinct_failures, failure_ids = [], set()
        for failure in failures:
            sid = failure["source_uuid"]
            if sid is None or sid not in failure_ids:
                distinct_failures.append(failure)
            failure_ids.add(sid)
        failures = distinct_failures
        failed_ids = {failure["source_uuid"] for failure in failures if failure["source_uuid"] is not None}
        # Ambiguous duplicate UUIDs invalidate every candidate for that origin;
        # filesystem traversal order can never choose a seemingly good winner.
        captures = [(path, entry) for path, entry in captures if entry["origin"]["source_uuid"] not in failed_ids]
        excluded = [entry for entry in excluded if entry["origin"]["source_uuid"] not in failed_ids]
        self._last_capture_bytes = captured_bytes
        return captures, excluded, failures

    def _pack(self, config, run_id, entries, temporary):
        groups, group, size = [], [], 0
        for path, entry in entries:
            member_id = str(uuid.uuid5(NAMESPACE, run_id + ":" + entry["version_key"]))
            entry.update(member_id=member_id, file="members/" + member_id + ".jsonl")
            if group and size + entry["bytes"] + len(canonical(entry)) + 256 > NORMAL_CONTAINER - 1024**2:
                groups.append(group)
                group, size = [], 0
            group.append((path, entry))
            size += entry["bytes"] + len(canonical(entry)) + 256
        if group:
            groups.append(group)
        packed = []
        for group in groups:
            container_id = str(uuid.uuid5(NAMESPACE, run_id + ":pack:" + hash_bytes(canonical([e["version_key"] for _, e in group]))))
            layout = "oversized_single" if len(group) == 1 and group[0][1]["bytes"] > NORMAL_CONTAINER - 1024**2 else "normal"
            manifest = {"format": "csl-backup-container", "schema_version": 1, "repo_id": config["repo_id"],
                "set_id": config["set_id"], "source_id": config["source_id"], "run_id": run_id,
                "container_id": container_id, "fingerprint": fmt.fingerprint(config), "layout": layout,
                "members": [entry for _, entry in group]}
            fmt.manifest(manifest, {**config, "fingerprint": fmt.fingerprint(config)})
            manifest_bytes = canonical(manifest)
            if len(manifest_bytes) > MAX_MANIFEST:
                raise TransferError("Container manifest exceeds metadata budget before upload")
            plain, encrypted = temporary / (container_id + ".zip"), temporary / (container_id + ".age")
            with zipfile.ZipFile(plain, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("manifest.json", manifest_bytes)
                for source, entry in group:
                    archive.write(source, entry["file"])
            self.age.encrypt(plain, encrypted, config["recipients"])
            fmt.cipher_limit(encrypted.stat().st_size, layout, len(group))
            packed.append((encrypted, manifest))
        return packed

    def run(self, config, identity, *, dry_run=False, resume=None):
        from csl_backup_incremental import run
        return run(self, config, identity, dry_run=dry_run, resume=resume)

    @staticmethod
    def _verify_container(path, expected):
        with zipfile.ZipFile(path) as archive:
            zip_preflight(archive)
            actual = json.loads(zip_read(archive, "manifest.json"))
            fmt.manifest(actual, expected)
            if actual != expected:
                raise TransferError("Interior manifest differs from expected logical bindings")
            names = {"manifest.json"} | {entry["file"] for entry in actual["members"]}
            if set(archive.namelist()) != names:
                raise TransferError("Unlisted container member")
            for entry in actual["members"]:
                if archive.getinfo(entry["file"]).file_size != entry["bytes"]:
                    raise TransferError("Member declared size differs")
                zip_digest(archive, entry)
        return actual

    def discover(self, *, scan=False):
        if scan:
            return {"repo_id": self.github.repo_id, "mode": "read-only unverified scan",
                "candidates": [{"tag": r["tag_name"], "release_id": r["id"]} for r in self.github.releases()
                               if r["tag_name"].startswith("cslb-v1-c-")],
                "warning": "Candidates are not validated checkpoints; no pointers repaired"}
        _, state = self.control.read()
        paths = list((self.root / "events").glob("*.json"))
        if len(paths) > 10000:
            raise TransferError("Local evidence budget exceeded; no truncated status")
        events = [json_read(path) for path in paths]
        events = [event for event in events if event.get("repo_id") == self.github.repo_id]
        run_paths = list((self.root / "runs").glob("*/journal.json"))
        if len(run_paths) > 10000:
            raise TransferError("Local run metadata budget exceeded; no truncated status")
        summaries = [json_read(path).get("summary") for path in run_paths]
        summaries = [summary for summary in summaries if summary and summary.get("repo_id") == self.github.repo_id]
        return {"repo_id": self.github.repo_id, "sets": state["sets"], "local_events": events,
                "local_runs_as_of": summaries,
                "evidence": "referenced control metadata only; no ciphertext integrity check"}

    def latest(self, set_id=None, source_id=None):
        _, state = self.control.read()
        candidates = []
        for sid, item in state["sets"].items():
            for origin, source in item["sources"].items():
                if (set_id is None or sid == set_id) and (source_id is None or origin == source_id) and source.get("latest_complete"):
                    candidates.append((sid, origin, source))
        if len(candidates) != 1:
            raise TransferError("Select an unambiguous backup set/source; latest is not global")
        return candidates[0]

    def _asset(self, identifier, kind, expected=None):
        release = self.github.request("GET", "/releases/tags/cslb-v1-" + kind + "-" + uid(identifier))
        if release.get("draft") is True:
            raise TransferError("Draft/plan is not a restorable backup")
        name = "catalog.age" if kind == "c" else "container.age"
        assets = [a for a in release["assets"] if a["name"] == name]
        if len(assets) != 1:
            raise TransferError("Missing or duplicate encrypted backup asset")
        envelope = self.github.read_envelope(release, identifier)
        if assets[0]["size"] != envelope["bytes"] or expected and expected["sha256"] != envelope["sha256"]:
            raise TransferError("Asset/envelope binding differs")
        if expected and (release["id"] != expected["release_id"] or assets[0]["id"] != expected["asset_id"] or
                         assets[0]["size"] != expected["bytes"]):
            raise TransferError("Backup asset identity/size differs from catalog/control")
        return {**assets[0], "expected_sha256": envelope["sha256"]}

    def _read_checkpoint(self, checkpoint, identity, temporary, *, set_id=None, source_id=None,
                         metadata_only=False, allow_partial=False):
        expected = None
        if checkpoint == "latest":
            set_id, source_id, source = self.latest(set_id, source_id)
            checkpoint, expected = source["latest_complete"], source["catalog"]
        asset = self._asset(checkpoint, "c", expected)
        encrypted, plain = temporary / "catalog.age", temporary / "catalog.json"
        self.github.download(asset, encrypted)
        if hash_file(encrypted) != asset["expected_sha256"]:
            raise TransferError("Encrypted catalog differs from its opaque envelope")
        if expected and hash_file(encrypted) != expected["sha256"]:
            raise TransferError("Catalog ciphertext differs from committed pointer")
        self.age.decrypt(encrypted, plain, identity)
        catalog = fmt.catalog(json_read(plain))
        if expected and expected.get("lease_epoch") is not None and catalog["lease_epoch"] != expected["lease_epoch"]:
            raise TransferError("Checkpoint lease epoch differs from committed control binding")
        if (catalog["checkpoint_id"] != checkpoint or catalog["repo_id"] != self.github.repo_id or
                set_id is not None and catalog["set_id"] != set_id or
                source_id is not None and catalog["source_id"] != source_id):
            raise TransferError("Requested checkpoint/set/source binding differs")
        if catalog["status"] == "partial" and not allow_partial:
            raise TransferError("Partial checkpoint requires explicit --allow-partial")
        if metadata_only:
            return catalog, []
        objects = []
        for container in catalog["containers"]:
            asset = self._asset(container["container_id"], "o", container)
            encrypted = temporary / (container["container_id"] + ".age")
            plain = temporary / (container["container_id"] + ".zip")
            self.github.download(asset, encrypted)
            if hash_file(encrypted) != container["sha256"]:
                raise TransferError("Container ciphertext checksum differs")
            self.age.decrypt(encrypted, plain, identity)
            self._verify_container(plain, container["manifest"])
            objects.append((container, plain))
        return catalog, objects

    def _event(self, catalog, container, operation, result="passed", validation="native_unverified", *, member=None, installed=None):
        observer_path = self.root / "observer.json"
        if not observer_path.exists():
            save(observer_path, {"observer_id": str(uuid.uuid4())}, exclusive=True)
        event = {"format": "csl-backup-evidence", "schema_version": 1,
            "event_id": str(uuid.uuid4()), "observer_id": json_read(observer_path)["observer_id"],
            "repo_id": catalog["repo_id"], "set_id": catalog["set_id"], "object_id": container["container_id"],
            "asset_id": container["asset_id"], "asset_sha256": container["sha256"],
            "operation": operation, "at": now(), "result": result,
            "level": "restored" if operation == "restore" else "available" if operation == "available" else "integrity_verified",
            "scope": "full ciphertext/plain manifest/member hashes", "native_validation": validation}
        if operation == "available":
            event["scope"] = "remote asset/envelope identity and size; no ciphertext download"
        event["source_id"] = catalog["source_id"]
        if operation == "restore":
            if not member or not installed:
                raise TransferError("Restore evidence requires a logical member and installed binding")
            event.update(object_id=member["member_id"], member_id=member["member_id"], version_key=member["version_key"],
                container_id=container["container_id"], installed_uuid=installed["installed_uuid"],
                installed_sha256=installed["installed_sha256"],
                target_binding=hash_bytes(canonical({"target": installed["target"], "cwd": installed["cwd"]})),
                scope="one logical member verified and installed/quarantined; not all container members")
        save(self.root / "events" / (event["event_id"] + ".json"), event, exclusive=True)

    @staticmethod
    def _derive_install(source, staged, sid, entry, cwd, stamp):
        with source.open("rb") as input_stream, staged.open("xb") as output:
            for record in read_records(input_stream):
                output.write(json_line(rewrite_import_record(record, sid,
                    {"id": entry["origin"]["source_uuid"],
                     "compaction_state_removed": entry.get("compaction_state_removed", False)}, cwd, stamp)))
        projected = staged.with_name(sid + ".display.jsonl")
        project_file(staged, projected, read_records, json_line, {entry["origin"]["source_uuid"], sid})
        return projected

    def verify(self, checkpoint, identity, *, set_id=None, source_id=None, native=False):
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        with locked(self.root), tempfile.TemporaryDirectory(prefix="verify-", dir=self.root) as directory:
            temporary = Path(directory)
            catalog, objects = self._read_checkpoint(checkpoint, identity, temporary, set_id=set_id, source_id=source_id)
            native_results = []
            for container, plain in objects:
                validation = "native_unverified"
                if native:
                    from csl_probe import native_replay
                    with zipfile.ZipFile(plain) as archive:
                        zip_preflight(archive)
                        for entry in fmt.selected(catalog, container):
                            source = temporary / (entry["member_id"] + ".jsonl")
                            zip_extract(archive, entry, source)
                            result = native_replay(source, "codex")
                            native_results.append(result)
                    validation = "structural"  # Probe result is returned separately, never inferred from hashes.
                self._event(catalog, container, "verify", validation=validation)
            return {"checkpoint_id": catalog["checkpoint_id"], "integrity_verified_at": now(),
                    "containers": len(objects), "native": native_results,
                    "scope": "bytes/structure; native request probes separate; no paid model generation"}

    def restore(self, checkpoint, identity, cwd, *, set_id=None, source_id=None, dry_run=False, new=False, allow_partial=False):
        cwd = Path(cwd).expanduser().resolve()
        if not cwd.is_dir():
            raise TransferError("Choose an existing restore --cwd")
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        with locked(self.root), tempfile.TemporaryDirectory(prefix="restore-", dir=self.root) as directory:
            temporary = Path(directory)
            catalog, objects = self._read_checkpoint(checkpoint, identity, temporary, set_id=set_id, source_id=source_id, allow_partial=allow_partial)
            prepared = []
            # Verify every native source binding before installing any session.
            for container, plain in objects:
                with zipfile.ZipFile(plain) as archive:
                    zip_preflight(archive)
                    for entry in fmt.selected(catalog, container):
                        source = temporary / (entry["member_id"] + ".source.jsonl")
                        zip_extract(archive, entry, source)
                        metadata, first = None, True
                        unsupported = entry.get("message_records") == 0
                        with source.open("rb") as stream:
                            for record in read_records(stream):
                                if first and record.get("type") != "session_meta":
                                    unsupported = True
                                first = False
                                if record.get("type") == "session_meta":
                                    metadata = record.get("payload")
                                    if not isinstance(metadata, dict) or metadata.get("id") != entry["origin"]["source_uuid"]:
                                        raise TransferError("Native source identity differs from encrypted manifest")
                                try:
                                    validate_compaction(record)
                                except TransferError:
                                    unsupported = True
                                if record.get("type") not in ("session_meta", "turn_context", "response_item", "event_msg", "compacted"):
                                    unsupported = True
                        if not metadata:
                            raise TransferError("Missing native source identity")
                        kind = source_kind(metadata.get("source", "cli"))
                        if entry["state"] == "agent" and kind != "agent" or entry["state"] == "interactive" and kind != "interactive":
                            raise TransferError("Native source kind differs from manifest visibility")
                        prepared.append((container, entry, source, unsupported))
            if dry_run:
                return {"status": "validated; no sessions installed", "sessions": len(prepared),
                        "quarantined": sum(row[3] for row in prepared), "checkpoint_id": catalog["checkpoint_id"]}
            installed = []
            for container, entry, source, quarantine in prepared:
                key = hash_bytes(canonical({"repo_id": catalog["repo_id"], "origin": entry["origin"], "version_key": entry["version_key"]}))
                intent_path = self.root / "restore-intents" / (key + ".json")
                prior = json_read(intent_path) if intent_path.exists() and not new else None
                if prior:
                    if (prior["cwd"] != str(cwd) or prior["member_sha256"] != entry["sha256"] or
                            prior["quarantined"] != quarantine):
                        raise TransferError("Existing restore differs; use --new explicitly")
                    sid, target, expected_hash = prior["installed_uuid"], Path(prior["target"]), prior["installed_sha256"]
                    uid(sid)
                    allowed = self.root / "quarantine" if quarantine else self.home / "archived_sessions" if entry["state"] == "archived" else self.home / "sessions"
                    if not target.resolve().is_relative_to(allowed.resolve()) or sid not in target.name:
                        raise TransferError("Reserved restore destination is outside its visibility scope")
                    staged = temporary / (sid + ".jsonl")
                    if target.exists():
                        if target.is_symlink() or hash_file(target) != expected_hash:
                            raise TransferError("Installed copy changed; conflict, not overwritten")
                    else:
                        if quarantine:
                            shutil.copyfile(source, staged)
                        else:
                            staged = self._derive_install(source, staged, sid, entry, cwd, prior["rewrite_at"])
                        if hash_file(staged) != expected_hash:
                            raise TransferError("Reserved restore bytes cannot be reconstructed exactly")
                        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                        publish_session_file(staged, target)
                else:
                    sid, stamp = str(uuid.uuid4()), now()
                    staged = temporary / (sid + ".jsonl")
                    if quarantine:
                        shutil.copyfile(source, staged)
                        target = self.root / "quarantine" / (sid + ".jsonl")
                    else:
                        staged = self._derive_install(source, staged, sid, entry, cwd, stamp)
                        if entry["state"] == "archived":
                            target = self.home / "archived_sessions" / ("rollout-" + dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%S") + "-" + sid + ".jsonl")
                        else:
                            date = dt.datetime.now(dt.timezone.utc)
                            target = self.home / "sessions" / date.strftime("%Y/%m/%d") / ("rollout-" + date.strftime("%Y-%m-%dT%H-%M-%S") + "-" + sid + ".jsonl")
                    expected_hash = hash_file(staged)
                    intent = {"format": "csl-backup-restore-intent", "schema_version": 1, "restore_id": str(uuid.uuid4()),
                        "repo_id": catalog["repo_id"], "checkpoint_id": catalog["checkpoint_id"], "member_id": entry["member_id"],
                        "member_sha256": entry["sha256"], "container_id": container["container_id"], "asset_sha256": container["sha256"],
                        "installed_uuid": sid, "target": str(target), "installed_sha256": expected_hash,
                        "cwd": str(cwd), "quarantined": quarantine, "status": "reserved", "reserved_at": now()}
                    intent["rewrite_at"] = stamp
                    save(self.root / "restore-intents" / "history" / (intent["restore_id"] + ".json"), intent, exclusive=True)
                    save(intent_path, intent, exclusive=not intent_path.exists())
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    publish_session_file(staged, target)
                    prior = intent
                if not quarantine:
                    index_path = getattr(self.csl, "DEFAULT_SESSION_INDEX", None)
                    index_existed = index_path.exists() if index_path else True
                    conn = self.csl.init_db(self.csl.DEFAULT_DB)
                    try:
                        if conn.execute("SELECT 1 FROM sessions WHERE session_id=?", (sid,)).fetchone() is None:
                            self.csl.register_native_session(conn, target, sid, "Recovered backup " + sid[:8], now())
                            if index_path and not index_existed:
                                index_path.chmod(0o600)
                    finally:
                        conn.close()
                receipt = {**prior, "status": "receipted", "last_restored_at": now(),
                           "checkpoint_id": catalog["checkpoint_id"], "member_id": entry["member_id"],
                           "container_id": container["container_id"], "asset_sha256": container["sha256"],
                           "validation": "quarantined" if quarantine else "native_unverified"}
                save(self.root / "receipts" / (key + ".json"), receipt)
                save(intent_path, receipt)
                self._event(catalog, container, "restore", validation=receipt["validation"], member=entry, installed=receipt)
                installed.append({"uuid": sid, "state": entry["state"], "validation": receipt["validation"]})
            if installed and hasattr(self.csl, "DEFAULT_SESSIONS_DIR"):
                with contextlib.redirect_stdout(sys.stderr):
                    refresh_native_picker(self.csl)
            quarantined = sum(item["validation"] == "quarantined" for item in installed)
            return {"status": "restored_with_quarantine" if quarantined else "restored", "quarantined": quarantined,
                    "checkpoint_id": catalog["checkpoint_id"], "sessions": installed,
                    "coverage": catalog["counts"], "omissions": catalog["failures"],
                    "warning": "No backup config adopted, no timer enabled, no historical tools executed"}
