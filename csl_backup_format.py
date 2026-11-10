"""Fail-closed encrypted backup bindings, separate from native CSL share bundles."""

import re

from csl_backup_core import MAX_OBJECT, NORMAL_CONTAINER, canonical, hash_bytes, uid
from csl_backup_crypto import Age, BackupPolicyError
from csl_transfer import TransferError
import csl_secrets
import csl_version

SCHEMA = 1
EXPORTER_VERSION = 2


def base(value, kind):
    if (not isinstance(value, dict) or value.get("format") != "csl-backup-" + kind or
            type(value.get("schema_version")) is not int or value["schema_version"] != SCHEMA):
        raise TransferError("Unknown backup format/version")


def checksum(value):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise TransferError("Invalid backup checksum")
    return value


def integer(value, low=0, high=2**63-1):
    if type(value) is not int or not low <= value <= high:
        raise TransferError("Invalid backup size/count")
    return value


def fingerprint(config):
    value = {"profile": config["profile"], "exporter": "csl-backup-" + config["profile"].split("-")[0] + "-v1",
        "cipher": "age-v1-x25519", "recipients": Age.recipients(config["recipients"]),
        "secret_policy": config["secret_policy"], "detector": "csl-partial-readable-v1",
        "csl_version": csl_version.__version__, "exporter_version": EXPORTER_VERSION,
        "detector_version": csl_secrets.RULES_VERSION}
    if "profile_epoch" in config:
        value["profile_epoch"] = uid(config["profile_epoch"])
    return value


def validate_fingerprint(value):
    fields = {"profile", "exporter", "cipher", "recipients", "secret_policy", "detector"}
    versions = {"csl_version", "exporter_version", "detector_version"}
    if not isinstance(value, dict) or set(value) not in (fields, fields | versions, fields | versions | {"profile_epoch"}):
        raise TransferError("Unknown backup fingerprint shape")
    if "profile_epoch" in value:
        uid(value["profile_epoch"])
    if versions <= set(value):
        if not isinstance(value["csl_version"], str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", value["csl_version"]):
            raise TransferError("Invalid producing CSL version")
        integer(value["exporter_version"],1)
        integer(value["detector_version"],1)
    if (value["profile"] not in ("native-age-v1", "portable-age-v1") or
            value["cipher"] != "age-v1-x25519" or value["detector"] != "csl-partial-readable-v1" or
            value["secret_policy"] not in ("stop", "retain", "scrub") or
            value["exporter"] != "csl-backup-" + value["profile"].split("-")[0] + "-v1" or
            value["profile"] == "native-age-v1" and value["secret_policy"] == "scrub"):
        raise TransferError("Unsupported backup profile/cipher/policy")
    if value["recipients"] != Age.recipients(value["recipients"]):
        raise TransferError("Recipients must be canonical and distinct")


def config(value):
    base(value, "config")
    for name in ("set_id", "source_id"):
        uid(value.get(name))
    integer(value.get("repo_id"), 1)
    if value.get("profile") not in ("native-age-v1", "portable-age-v1") or value.get("secret_policy") not in ("stop", "retain", "scrub"):
        raise BackupPolicyError("Unsupported backup profile/policy")
    if value["profile"] == "native-age-v1" and value["secret_policy"] == "scrub":
        raise BackupPolicyError("Native byte-exact profile cannot scrub; explicitly select portable-age-v1")
    Age.recipients(value.get("recipients"))
    if "profile_epoch" in value:
        uid(value["profile_epoch"])
    if not isinstance(value.get("key_reference"), str) or not (value["key_reference"] == "stdin" or
            re.fullmatch(r"keyring:[0-9a-f-]{36}", value["key_reference"])):
        raise BackupPolicyError("Backup key must be an explicit memory/keyring reference, never a plaintext fallback")
    if value.get("secret_policy") == "retain" and value.get("retain_accepted") is not True:
        raise BackupPolicyError("Retaining possible secrets requires explicit profile-scoped acceptance")
    if "key_epochs" in value:
        from csl_backup_keys import epochs
        epochs(value)
    return value


def binding(value, expected):
    for name in ("repo_id", "set_id", "source_id"):
        if value.get(name) != expected.get(name):
            raise TransferError("Backup repository/set/source binding differs")


def member(value, expected):
    if not isinstance(value, dict):
        raise TransferError("Invalid logical member")
    uid(value.get("member_id"))
    checksum(value.get("version_key"))
    checksum(value.get("sha256"))
    integer(value.get("bytes"), 1, MAX_OBJECT)
    origin = value.get("origin")
    if not isinstance(origin, dict):
        raise TransferError("Missing member origin")
    for name in ("set_id", "source_id"):
        if origin.get(name) != expected.get(name):
            raise TransferError("Cross-set/source member")
    if origin.get("provider") != "codex":
        raise TransferError("Unsupported backup provider")
    uid(origin.get("source_uuid"))
    if value.get("file") != "members/" + value["member_id"] + ".jsonl":
        raise TransferError("Member path is not bound to its identity")
    if value.get("state") not in ("interactive", "archived", "agent"):
        raise TransferError("Unknown native visibility")
    profile = value.get("fingerprint")
    if not isinstance(profile, dict) or profile != expected.get("fingerprint"):
        raise TransferError("Member profile/recipients/policy binding differs")
    identity = {"origin": origin, "source_sha256": value.get("source_sha256"),
                "state": value["state"], "fingerprint": profile}
    checksum(identity["source_sha256"])
    if profile["profile"] == "native-age-v1" and value["sha256"] != identity["source_sha256"]:
        raise TransferError("Byte-exact native source/member checksums differ")
    if hash_bytes(canonical(identity)) != value["version_key"]:
        raise TransferError("Member logical version identity differs")
    if not isinstance(value.get("losses"), list) or not isinstance(value.get("pending_tool_calls"), list):
        raise TransferError("Missing member continuity report")


def manifest(value, expected):
    base(value, "container")
    binding(value, expected)
    for name in ("container_id", "run_id"):
        uid(value.get(name))
    if value.get("fingerprint") != expected.get("fingerprint"):
        raise TransferError("Container profile binding differs")
    members = value.get("members")
    if not isinstance(members, list) or not 0 < len(members) <= 10000:
        raise TransferError("Empty/oversize container member list")
    if value.get("layout") not in ("normal", "oversized_single") or value["layout"] == "oversized_single" and len(members) != 1:
        raise TransferError("Invalid container layout")
    seen = set()
    for item in members:
        member(item, value)
        if item["member_id"] in seen:
            raise TransferError("Duplicate container member")
        seen.add(item["member_id"])
    return value


def cipher_limit(size, layout, members):
    limit = NORMAL_CONTAINER if layout == "normal" else MAX_OBJECT
    integer(size, 1, limit)
    if layout not in ("normal", "oversized_single") or layout == "oversized_single" and members != 1:
        raise TransferError("Invalid final ciphertext layout")


def catalog(value, expected=None):
    if isinstance(value, dict) and type(value.get("schema_version")) is int and value["schema_version"] == 2:
        return catalog2(value, expected)
    base(value, "catalog")
    integer(value.get("repo_id"), 1)
    integer(value.get("lease_epoch"), 1)
    for name in ("set_id", "source_id", "run_id", "checkpoint_id"):
        uid(value.get(name))
    validate_fingerprint(value.get("fingerprint"))
    if expected:
        binding(value, expected)
        if value.get("fingerprint") != expected.get("fingerprint"):
            raise TransferError("Checkpoint profile binding differs")
    if value.get("status") != "complete" or value.get("failures") != []:
        raise TransferError("F1 restores complete checkpoints only")
    containers = value.get("containers")
    if not isinstance(containers, list) or not containers or len(containers) > 10000:
        raise TransferError("Empty/oversize checkpoint")
    physical_ids, logical_ids, source_ids = set(), set(), set()
    if sum(integer(container.get("bytes"), 1, MAX_OBJECT) for container in containers) > 2 * 1024**3:
        raise TransferError("Checkpoint download budget exceeds 2 GiB; no partial verification presented as complete")
    for container in containers:
        uid(container.get("container_id"))
        checksum(container.get("sha256"))
        integer(container.get("asset_id"), 1)
        integer(container.get("release_id"), 1)
        manifest(container.get("manifest"), value)
        details = container["manifest"]
        if container["container_id"] != details["container_id"] or container["container_id"] in physical_ids:
            raise TransferError("Duplicate or misbound physical container")
        physical_ids.add(container["container_id"])
        cipher_limit(container.get("bytes"), details["layout"], len(details["members"]))
        for item in details["members"]:
            origin = item["origin"]["source_uuid"]
            if item["member_id"] in logical_ids or origin in source_ids:
                raise TransferError("Duplicate logical version/source in checkpoint")
            logical_ids.add(item["member_id"])
            source_ids.add(origin)
    counts, exclusions, selection = value.get("counts"), value.get("exclusions"), value.get("selection")
    if (not isinstance(counts, dict) or set(counts) != {"eligible", "succeeded", "failed", "excluded"} or
            not isinstance(exclusions, list) or not isinstance(selection, dict)):
        raise TransferError("Missing checkpoint coverage fields")
    for count in counts.values():
        integer(count)
    if (counts != {"eligible": len(logical_ids), "succeeded": len(logical_ids), "failed": 0, "excluded": len(exclusions)} or
            selection.get("provider") != "codex" or selection.get("archives") is not True or
            type(selection.get("agent_forks")) is not bool):
        raise TransferError("Checkpoint coverage/archives contract differs")
    return value


def heads(value):
    """Schema one selected every physical member; two has explicit logical heads."""
    if value["schema_version"] == 1:
        return [{"container_id": c["container_id"], "member_id": m["member_id"],
                 "version_key": m["version_key"], "sha256": m["sha256"],
                 "state": "current", "captured_at": m.get("captured_at", value["cut_at"]),
                 "last_observed_at": m.get("captured_at", value["cut_at"])}
                for c in value["containers"] for m in c["manifest"]["members"]]
    return value["heads"]


def selected(value, container):
    ids = {h["member_id"] for h in heads(value) if h["container_id"] == container["container_id"]}
    return [m for m in container["manifest"]["members"] if m["member_id"] in ids]


def timestamp(value):
    import datetime as dt
    if not isinstance(value, str):
        raise TransferError("Missing backup evidence date")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() != dt.timedelta(0):
            raise ValueError
    except ValueError:
        raise TransferError("Invalid backup evidence date") from None
    return parsed


def catalog2(value, expected=None):
    # Validate immutable physical bindings using schema-one rules independently of
    # logical selection. Old versions in a retained pack are deliberately allowed.
    if value.get("format") != "csl-backup-catalog":
        raise TransferError("Unknown backup catalog")
    for name in ("set_id", "source_id", "run_id", "checkpoint_id"):
        uid(value.get(name))
    integer(value.get("repo_id"), 1)
    integer(value.get("lease_epoch"), 1)
    validate_fingerprint(value.get("fingerprint"))
    if expected:
        binding(value, expected)
        if value["fingerprint"] != expected.get("fingerprint"):
            raise TransferError("Checkpoint profile binding differs")
    timestamp(value.get("cut_at"))
    containers, selected_heads = value.get("containers"), value.get("heads")
    if not isinstance(containers, list) or not 0 < len(containers) <= 10000 or not isinstance(selected_heads, list) or not 0 < len(selected_heads) <= 10000:
        raise TransferError("Empty/oversize checkpoint")
    physical, members, member_ids = {}, {}, set()
    if sum(integer(c.get("bytes"), 1, MAX_OBJECT) for c in containers) > 2 * 1024**3:
        raise TransferError("Checkpoint download budget exceeds 2 GiB")
    for c in containers:
        uid(c.get("container_id"))
        checksum(c.get("sha256"))
        integer(c.get("asset_id"), 1)
        integer(c.get("release_id"), 1)
        manifest(c.get("manifest"), value)
        if c["container_id"] != c["manifest"]["container_id"] or c["container_id"] in physical:
            raise TransferError("Duplicate or misbound physical container")
        physical[c["container_id"]] = c
        cipher_limit(c["bytes"], c["manifest"]["layout"], len(c["manifest"]["members"]))
        for m in c["manifest"]["members"]:
            if m["member_id"] in member_ids:
                raise TransferError("Duplicate physical member identity")
            member_ids.add(m["member_id"])
            members[(c["container_id"], m["member_id"])] = m
    seen, referenced = set(), set()
    states = {"current": 0, "stale": 0, "missing_local": 0}
    for h in selected_heads:
        if not isinstance(h, dict):
            raise TransferError("Invalid logical head")
        m = members.get((h.get("container_id"), h.get("member_id")))
        if m is None or h.get("sha256") != m["sha256"] or h.get("version_key") != m["version_key"]:
            raise TransferError("Logical head is not bound to a physical member")
        origin = m["origin"]["source_uuid"]
        if origin in seen or h.get("state") not in states:
            raise TransferError("Duplicate source or invalid logical head state")
        seen.add(origin)
        referenced.add(h["container_id"])
        states[h["state"]] += 1
        if timestamp(h.get("captured_at")) > timestamp(h.get("last_observed_at")):
            raise TransferError("Head observation precedes captured content")
    if referenced != set(physical):
        raise TransferError("Unreferenced physical container in checkpoint")
    counts, exclusions, failures = value.get("counts"), value.get("exclusions"), value.get("failures")
    fields = {"eligible", "captured", "reused", "failed", "stale", "missing_local", "protected", "excluded"}
    if not isinstance(counts, dict) or set(counts) != fields or not isinstance(exclusions, list) or not isinstance(failures, list):
        raise TransferError("Missing checkpoint coverage fields")
    for failure in failures:
        if (not isinstance(failure, dict) or set(failure) != {"source_uuid", "reason_code"} or
                not isinstance(failure["reason_code"], str) or
                not re.fullmatch("[A-Za-z][A-Za-z0-9]{0,79}", failure["reason_code"])):
            raise TransferError("Invalid checkpoint failure report")
        if failure["source_uuid"] is not None:
            uid(failure["source_uuid"])
    for n in counts.values():
        integer(n)
    if (counts["captured"] + counts["reused"] != states["current"] or
            counts["eligible"] != counts["captured"] + counts["reused"] + counts["failed"] or
            counts["failed"] != len(failures) or counts["stale"] != states["stale"] or
            counts["missing_local"] != states["missing_local"] or counts["protected"] != len(selected_heads) or
            counts["excluded"] != len(exclusions) or counts["stale"] > counts["failed"]):
        raise TransferError("Checkpoint coverage differs from logical heads")
    status = "partial" if counts["failed"] else "complete"
    if value.get("status") != status:
        raise TransferError("False complete/partial checkpoint")
    selection = value.get("selection", {})
    if selection.get("provider") != "codex" or selection.get("archives") is not True or type(selection.get("agent_forks")) is not bool:
        raise TransferError("Checkpoint selection differs")
    return value
