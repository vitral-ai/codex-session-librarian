"""Synthetic-only filesystem backend to test immutable publish primitives."""

import hashlib
import json
import os
from pathlib import Path
from .contracts import ContractError, canonical

API_VERSION = "2026-03-10"


def release_payload(tag, target):
    if not tag.startswith("cslb-v1-"):
        raise ContractError("Not a backup experiment tag")
    return {"tag_name": tag, "target_commitish": target, "name": tag,
            "body": "Synthetic CSL F0 experiment; no user histories.",
            "draft": False, "prerelease": False, "make_latest": "false"}


def check_repo(expected_id, result):
    if result.get("id") != expected_id or result.get("private") is not True:
        raise ContractError("Destination substituted or public")
    return result["full_name"]


def bounded_error(status):
    return {403: "access_or_rate_denied", 404: "missing_or_denied", 409: "conflict",
            422: "invalid_or_already_exists", 429: "rate_limited"}.get(status, "remote_failure")


class SyntheticStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def publish(self, identifier, content, *, lose_response=False, truncate=False):
        import uuid
        if str(uuid.UUID(identifier)) != identifier:
            raise ContractError("Invalid synthetic object ID")
        target = self.root / identifier
        try:
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if target.read_bytes() != content:
                raise ContractError("Contradictory existing object; never overwrite")
            return self.get(identifier)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content[:len(content)//2] if truncate else content)
        if lose_response:
            raise TimeoutError("Accepted upload; response lost")
        return self.get(identifier)

    def get(self, identifier, expected_hash=None):
        content = (self.root / identifier).read_bytes()
        if expected_hash and hashlib.sha256(content).hexdigest() != expected_hash:
            raise ContractError("Incomplete or corrupted asset")
        return content

    def discover(self, page_size=2):
        names = sorted(p.name for p in self.root.iterdir() if p.is_file())
        return [names[start:start + page_size] for start in range(0, len(names), page_size)]

    def commit_catalog(self, identifier, entries):
        for entry in entries:
            self.get(entry["object_id"], entry["sha256"])
        return self.publish(identifier, canonical({"synthetic": True, "entries": entries}))

    def cold_read(self, identifier):
        catalog = json.loads(self.get(identifier))
        return [self.get(entry["object_id"], entry["sha256"]) for entry in catalog["entries"]]
