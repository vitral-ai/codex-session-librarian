"""GitHub transport and fenced control chain; never selects or changes a login."""

import copy
import datetime as dt
import email.utils
import json
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import tempfile
import time

from csl_backup_core import BackupBusy, canonical, exclusive_output, hash_file, json_read, now
from csl_transfer import TransferError
from csl_sharing import REPO_RE

API_VERSION = "2026-03-10"
CONTROL_REF = "heads/csl-backup-control-v1"


class RemoteError(TransferError):
    def __init__(self, status):
        self.status = status
        meaning = {403: "access or rate denied", 404: "missing or access denied",
                   409: "concurrent change", 422: "conflict or invalid request", 429: "rate limited"}
        super().__init__("Backup GitHub request failed: " + meaning.get(status, "transport failure") +
                         "; no login, permission change or overwrite attempted")


class GitHub:
    def __init__(self, repo, *, expected_id=None, executable="gh"):
        if not isinstance(repo, str) or not REPO_RE.fullmatch(repo):
            raise TransferError("Backup repository must be OWNER/PRIVATE-REPO")
        self.repo = repo
        self.executable = shutil.which(executable)
        if not self.executable:
            raise TransferError("Selected GitHub CLI unavailable; authenticate explicitly outside CSL")
        self.server_time = None
        self.calls = 0
        self.metrics = {"request_calls": 0, "metadata_calls": 0, "download_calls": 0, "downloaded_bytes": 0,
                        "upload_calls": 0, "uploaded_bytes": 0}
        self.metadata = self.request("GET", "")
        if self.metadata.get("private") is not True:
            raise TransferError("Backup destination must remain private")
        if expected_id is not None and self.metadata.get("id") != expected_id:
            raise TransferError("Backup repository identity changed; refusing replacement")
        self.repo = self.metadata["full_name"]
        self.repo_id = self.metadata["id"]

    def command(self, method, endpoint):
        return [self.executable, "api", "--hostname", "github.com", "--method", method,
                "-H", "X-GitHub-Api-Version: " + API_VERSION, endpoint]

    def revalidate(self, *, write=False):
        current = self.request("GET", "")
        if current.get("private") is not True or current.get("id") != self.repo_id:
            raise TransferError("Backup repository became public or changed identity; no mutation attempted")
        if write and current.get("permissions", {}).get("push") is not True:
            raise TransferError("Backup write permission changed; no login or permission repair attempted")
        self.repo, self.metadata = current["full_name"], current
        return current

    def request(self, method, suffix, body=None, *, upload=None):
        if method not in ("GET", "POST", "PATCH"):
            raise TransferError("Unsupported backup operation; no deletion or settings change permitted")
        if method != "GET":
            self.revalidate(write=True)
        endpoint = ("https://uploads.github.com/repos/" + self.repo + suffix) if upload else "repos/" + self.repo + suffix
        command = self.command(method, endpoint) + ["--include", "-H", "Accept: application/vnd.github+json"]
        if body is not None:
            command += ["--input", "-"]
        if upload:
            command += ["--input", str(upload), "-H", "Content-Type: application/octet-stream"]
        self.calls += 1
        self.metrics["request_calls"] += 1
        self.metrics["metadata_calls"] += int(upload is None)
        if upload:
            self.metrics["upload_calls"] += 1
            self.metrics["uploaded_bytes"] += Path(upload).stat().st_size
        try:
            result = subprocess.run(command, input=canonical(body) if body is not None else None,
                                    capture_output=True, timeout=300)
        except subprocess.TimeoutExpired:
            raise RemoteError(0) from None
        response = result.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
        headers, separator, payload = response.partition("\n\n")
        status_match = re.match(r"HTTP/\S+ (\d{3})", headers)
        status = int(status_match[1]) if status_match else 0
        for line in headers.splitlines():
            if line.lower().startswith("date:"):
                self.server_time = email.utils.parsedate_to_datetime(line.split(":", 1)[1].strip()).timestamp()
        if result.returncode or not 200 <= status < 300:
            raise RemoteError(status)
        if not separator or len(payload) > 16 * 1024**2:
            raise TransferError("Oversize or invalid GitHub metadata")
        try:
            return json.loads(payload) if payload.strip() else None
        except ValueError:
            raise TransferError("Invalid GitHub backup response") from None

    def download(self, asset, target):
        with exclusive_output(target) as staging:
            self._download_to(asset, staging)

    def _download_to(self, asset, target):
        if type(asset.get("id")) is not int or type(asset.get("size")) is not int or not 0 < asset["size"] <= 256*1024**2:
            raise TransferError("Invalid encrypted asset metadata")
        command = self.command("GET", "repos/" + self.repo + "/releases/assets/" + str(asset["id"]))
        command += ["-H", "Accept: application/octet-stream"]
        self.calls += 1
        self.metrics["download_calls"] += 1
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        deadline, received = time.monotonic() + 300, 0
        try:
            with Path(target).open("xb") as stream:
                Path(target).chmod(0o600)
                while True:
                    timeout = deadline - time.monotonic()
                    if timeout <= 0 or not select.select([process.stdout], [], [], timeout)[0]:
                        raise TransferError("Backup download deadline exceeded")
                    chunk = os.read(process.stdout.fileno(), 1024**2)
                    if not chunk:
                        break
                    received += len(chunk)
                    self.metrics["downloaded_bytes"] += len(chunk)
                    if received > asset["size"]:
                        raise TransferError("Encrypted asset exceeds declared size")
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if process.wait(timeout=5) or received != asset["size"]:
                raise TransferError("Incomplete or denied backup download")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()

    def releases(self):
        for page in range(1, 10001):
            rows = self.request("GET", "/releases?per_page=100&page=" + str(page))
            yield from rows
            if len(rows) < 100:
                return
        raise TransferError("Backup discovery budget exceeded; no truncated success")

    def resolve_release(self, identifier, kind="c", release_id=None):
        tag = "cslb-v1-" + kind + "-" + identifier
        if release_id is not None:
            release = self.request("GET", "/releases/" + str(release_id))
            if release.get("tag_name") != tag:
                raise TransferError("Release ID/tag binding differs")
            return release
        # Draft tags are not reliably returned by GET-by-tag. List authenticated
        # releases, including drafts; never recreate an uncertain POST blindly.
        found = [r for r in self.releases() if r.get("tag_name") == tag]
        if len(found) > 1:
            raise TransferError("Duplicate backup release identity")
        return found[0] if found else None

    def reserve(self, identifier, kind="c"):
        self.revalidate(write=True)
        release = self.resolve_release(identifier, kind)
        if release is None:
            tag = "cslb-v1-" + kind + "-" + identifier
            head = self.request("GET", "/git/ref/heads/" + self.metadata["default_branch"])["object"]["sha"]
            try:
                release = self.request("POST", "/releases", {"tag_name": tag, "target_commitish": head,
                    "name": tag, "body": "CSL encrypted backup; opaque metadata only.",
                    "draft": True, "prerelease": False, "make_latest": "false"})
            except RemoteError:
                release = self.resolve_release(identifier, kind)
                if release is None:
                    raise TransferError("Uncertain release POST; stable intention retained; no blind retry") from None
        return release

    def finalize(self, identifier, kind, release_id):
        release = self.resolve_release(identifier, kind, release_id)
        if release.get("draft"):
            try:
                release = self.request("PATCH", "/releases/" + str(release_id),
                                       {"draft": False, "make_latest": "false"})
            except RemoteError:
                release = self.resolve_release(identifier, kind, release_id)
                if release.get("draft"):
                    raise TransferError("Uncertain release publication; intention retained") from None
        return release

    def publish(self, identifier, ciphertext, kind, *, release_id=None):
        if kind not in ("o", "c", "p"):
            raise TransferError("Unknown backup object kind")
        release_kind = "c" if kind == "p" else kind
        release = (self.resolve_release(identifier, release_kind, release_id) if release_id is not None
                   else self.reserve(identifier, release_kind))
        name = {"o": "container.age", "c": "catalog.age", "p": "plan.age"}[kind]
        descriptor_name = "plan-descriptor.json" if kind == "p" else "descriptor.json"
        found = [a for a in release["assets"] if a["name"] == name]
        if len(found) > 1:
            raise TransferError("Duplicate encrypted asset")
        if found:
            # Ciphertext is randomized. Caller must download/decrypt and compare
            # the intended logical binding before adopting an existing instance.
            asset = found[0]
            if not any(a['name'] == descriptor_name for a in release['assets']):
                with tempfile.TemporaryDirectory(prefix="csl-envelope-recovery-") as directory:
                    accepted = Path(directory) / "accepted.age"
                    self.download(asset, accepted)
                    self._descriptor(release, identifier, accepted, descriptor_name)
            else:
                self.read_envelope(release, identifier, descriptor_name)
        else:
            try:
                asset = self.request("POST", "/releases/" + str(release["id"]) + "/assets?name=" + name, upload=ciphertext)
            except RemoteError:
                release = self.resolve_release(identifier, release_kind, release["id"])
                found = [a for a in release["assets"] if a["name"] == name]
                if len(found) != 1:
                    raise TransferError("Uncertain upload; durable intention retained; no blind retry") from None
                asset = found[0]
                # Never write an envelope from regenerated bytes for uncertain
                # remote data. Download the accepted asset to derive its digest.
            release = self.resolve_release(identifier, release_kind, release["id"])
            with tempfile.TemporaryDirectory(prefix="csl-adopt-") as directory:
                accepted = Path(directory) / "accepted.age"
                self.download(asset, accepted)
                self._descriptor(release, identifier, accepted, descriptor_name)
        return {"release_id": release["id"], "asset": asset, "tag": release["tag_name"]}

    def _descriptor(self, release, identifier, ciphertext, name="descriptor.json"):
        expected = {"format": "csl-backup-envelope", "schema_version": 1, "object_id": identifier,
                    "cipher": "age-v1-x25519", "bytes": Path(ciphertext).stat().st_size, "sha256": hash_file(ciphertext)}
        found = [a for a in release["assets"] if a["name"] == name]
        if len(found) > 1:
            raise TransferError("Duplicate backup envelope")
        if found:
            if self.read_envelope(release, identifier, name) != expected:
                raise TransferError("Conflicting backup envelope; never overwrite")
            return found[0]
        with tempfile.TemporaryDirectory(prefix="csl-envelope-") as directory:
            path = Path(directory) / name
            path.write_bytes(canonical(expected))
            path.chmod(0o600)
            try:
                return self.request("POST", "/releases/" + str(release["id"]) + "/assets?name=" + name, upload=path)
            except RemoteError:
                release = self.resolve_release(identifier, "c" if name.startswith("plan") else release["tag_name"].split("-")[2], release["id"])
                if self.read_envelope(release, identifier, name) != expected:
                    raise TransferError("Uncertain envelope upload; intention retained") from None
                return next(a for a in release["assets"] if a["name"] == name)

    def read_envelope(self, release, identifier, name="descriptor.json"):
        found = [a for a in release["assets"] if a["name"] == name]
        if len(found) != 1 or not 0 < found[0]["size"] <= 4096:
            raise TransferError("Missing, duplicate or oversized opaque backup envelope")
        with tempfile.TemporaryDirectory(prefix="csl-envelope-read-") as directory:
            target = Path(directory) / "descriptor.json"
            self.download(found[0], target)
            value = json_read(target)
        if (not isinstance(value, dict) or set(value) != {"format", "schema_version", "object_id", "cipher", "bytes", "sha256"} or
                value.get("format") != "csl-backup-envelope" or type(value.get("schema_version")) is not int or
                value["schema_version"] != 1 or value.get("object_id") != identifier or value.get("cipher") != "age-v1-x25519" or
                type(value.get("bytes")) is not int or not 0 < value["bytes"] <= 256*1024**2 or
                not isinstance(value.get("sha256"), str) or not re.fullmatch("[0-9a-f]{64}", value["sha256"])):
            raise TransferError("Unknown or misbound backup envelope")
        return value


class Control:
    def __init__(self, github):
        self.github = github

    def read(self):
        gh = self.github
        try:
            head = gh.request("GET", "/git/ref/" + CONTROL_REF)["object"]["sha"]
        except RemoteError as error:
            if error.status == 404:
                return None, {"format": "csl-backup-control", "schema_version": 1, "repo_id": gh.repo_id, "sets": {}}
            raise
        tree = gh.request("GET", "/git/commits/" + head)["tree"]["sha"]
        entries = gh.request("GET", "/git/trees/" + tree)["tree"]
        blob = next((entry["sha"] for entry in entries if entry["path"] == "control.json"), None)
        if not blob:
            raise TransferError("Control branch has no valid state; scan is read-only")
        import base64
        raw = gh.request("GET", "/git/blobs/" + blob)
        content = base64.b64decode(raw["content"])
        if len(content) > 16*1024**2:
            raise TransferError("Control exceeds metadata budget")
        state = json.loads(content)
        if state.get("format") != "csl-backup-control" or state.get("schema_version") != 1 or state.get("repo_id") != gh.repo_id:
            raise TransferError("Unknown or substituted control state; no repair attempted")
        return head, state

    def change(self, mutate):
        gh = self.github
        for _ in range(3):
            parent, state = self.read()
            next_state = copy.deepcopy(state)
            if gh.server_time is None:
                raise TransferError("No provider Date available for lease")
            mutate(next_state, int(gh.server_time))
            base = parent or gh.request("GET", "/git/ref/heads/" + gh.metadata["default_branch"])["object"]["sha"]
            tree = gh.request("GET", "/git/commits/" + base)["tree"]["sha"]
            blob = gh.request("POST", "/git/blobs", {"content": canonical(next_state).decode(), "encoding": "utf-8"})
            updated = gh.request("POST", "/git/trees", {"base_tree": tree, "tree": [
                {"path": "control.json", "mode": "100644", "type": "blob", "sha": blob["sha"]}]})
            child = gh.request("POST", "/git/commits", {"message": "CSL backup control", "tree": updated["sha"], "parents": [base]})
            try:
                if parent:
                    gh.request("PATCH", "/git/refs/" + CONTROL_REF, {"sha": child["sha"], "force": False})
                else:
                    gh.request("POST", "/git/refs", {"ref": "refs/" + CONTROL_REF, "sha": child["sha"]})
                return next_state
            except RemoteError as error:
                if error.status not in (409, 422):
                    raise
        raise BackupBusy("Control contention; bounded retries exhausted")
