"""Bounded, explicitly invoked live F0 harness for one authorized synthetic repo.

No delete, auth change, helper configuration, real history or model operation.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

from .backend import API_VERSION, check_repo, release_payload
from .contracts import canonical
from .run import write

REPO = "manunruks/csl-backup-validation-20261109"
REPO_ID = 1452103289
PREFIX = "repos/" + REPO


class API:
    def __init__(self, root):
        self.root = root
        self.calls = []

    def call(self, method, path, payload=None, *, raw=None, expected_error=False):
        command = ["gh-manunruks", "api", "--hostname", "github.com", "--method", method,
                   "-H", "Accept: application/vnd.github+json", "-H", "X-GitHub-Api-Version: " + API_VERSION, path]
        if payload is not None:
            command.extend(["--input", "-"])
        if raw is not None:
            command.extend(["--input", str(raw), "-H", "Content-Type: application/octet-stream"])
        result = subprocess.run(command, input=canonical(payload) if payload is not None else None,
                                capture_output=True, timeout=60)
        try:
            data = json.loads(result.stdout)
        except ValueError:
            data = {"bytes": len(result.stdout), "sha256": hashlib.sha256(result.stdout).hexdigest()}
        row = {"method": method, "path": path, "request": payload,
               "exit": result.returncode, "response": data}
        self.calls.append(row)
        write(self.root, "remote-requests.json", {"api_version": API_VERSION, "calls": self.calls})
        if result.returncode and not expected_error:
            raise RuntimeError("Synthetic GitHub call failed: " + method + " " + path)
        return data, result.returncode

    def get(self, path):
        return self.call("GET", PREFIX + path)[0]

    def post(self, path, payload):
        return self.call("POST", PREFIX + path, payload)[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--confirm-repo-id", type=int, required=True)
    args = parser.parse_args()
    if args.confirm_repo_id != REPO_ID:
        raise ValueError("Explicit F0 destination mismatch")
    os.umask(0o077)
    args.out.mkdir(parents=True, mode=0o700, exist_ok=False)
    api = API(args.out)
    repo = api.get("")
    check_repo(REPO_ID, repo)
    if not repo.get("permissions", {}).get("push"):
        raise ValueError("No authorized write access")
    before = api.get("/releases?per_page=100")
    if before:
        raise ValueError("Harness requires empty synthetic repo; inspect existing inventory, never delete/retry blindly")
    head = api.get("/git/ref/heads/main")["object"]["sha"]
    base_tree = api.get("/git/commits/" + head)["tree"]["sha"]
    run = str(uuid.uuid4())
    write(args.out, "destination.json", {"repo": REPO, "repo_id": REPO_ID,
        "private": True, "run": run, "limits": {"releases": 5, "assets": 10, "bytes": 10485760},
        "remote_delete": False, "identity_command": "gh-manunruks"})
    # All objects are synthetic labels only, intentionally plaintext in this F0
    # backend protocol experiment; real data are prohibited until encrypted E1.
    releases = []
    sentinel = api.post("/releases", {**release_payload("cslb-v1-f0-sentinel-" + run, head), "make_latest": "true"})
    releases.append(sentinel)
    latest_before = api.get("/releases/latest")["id"]
    content = b'{"synthetic_only":true,"fixture":"F0 REMOTE OBJECT"}\n'
    object_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, "csl-f0-object:" + run))
    checkpoint_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, "csl-f0-catalog:" + run))
    object_release = api.post("/releases", release_payload("cslb-v1-o-" + object_uuid, head))
    releases.append(object_release)
    content_path = args.out / "fixture.bin"
    content_path.write_bytes(content)
    asset, failed = api.call("POST", "https://uploads.github.com/" + PREFIX + "/releases/" + str(object_release["id"]) +
                            "/assets?name=object.synthetic.bin", raw=content_path)
    assert not failed
    # Simulate losing the caller's response, then recover the known stable tag.
    found = api.get("/releases/tags/cslb-v1-o-" + object_uuid)
    assert found["id"] == object_release["id"]
    catalog = {"synthetic_only": True, "repo_id": REPO_ID, "run_id": run,
               "object_tag": found["tag_name"], "asset_id": asset["id"],
               "asset_sha256": hashlib.sha256(content).hexdigest()}
    catalog_release = api.post("/releases", release_payload("cslb-v1-c-" + checkpoint_uuid, head))
    releases.append(catalog_release)
    catalog_path = args.out / "catalog.json"
    catalog_path.write_bytes(canonical(catalog))
    cat_asset, failed = api.call("POST", "https://uploads.github.com/" + PREFIX + "/releases/" + str(catalog_release["id"]) +
                                "/assets?name=catalog.synthetic.json", raw=catalog_path)
    assert not failed
    # Two sibling commits; API fast-forward rejects the losing candidate.
    def commit(parent, state):
        blob = api.post("/git/blobs", {"content": canonical(state).decode(), "encoding": "utf-8"})
        tree = api.post("/git/trees", {"base_tree": base_tree, "tree": [
            {"path": "control.json", "mode": "100644", "type": "blob", "sha": blob["sha"]}]})
        return api.post("/git/commits", {"message": "Synthetic CSL F0 control", "tree": tree["sha"], "parents": [parent]})["sha"]
    initial = commit(head, {"epoch": 1, "owner": "synthetic-A", "latest_complete": None})
    api.post("/git/refs", {"ref": "refs/heads/csl-backup-control-v1", "sha": initial})
    a = commit(initial, {"epoch": 1, "owner": "synthetic-A", "latest_complete": "A"})
    b = commit(initial, {"epoch": 2, "owner": "synthetic-B", "latest_complete": checkpoint_uuid})
    api.call("PATCH", PREFIX + "/git/refs/heads/csl-backup-control-v1", {"sha": b, "force": False})
    _, stale_status = api.call("PATCH", PREFIX + "/git/refs/heads/csl-backup-control-v1",
                               {"sha": a, "force": False}, expected_error=True)
    assert stale_status != 0
    assert api.get("/git/ref/heads/csl-backup-control-v1")["object"]["sha"] == b
    assert api.get("/releases/latest")["id"] == latest_before
    # Discovery does not depend on local journal. Force pagination one release/page.
    pages = []
    for page in range(1, 6):
        rows = api.get("/releases?per_page=1&page=" + str(page))
        if not rows:
            break
        pages.extend(rows)
    cold_catalog_release = next(row for row in pages if row["tag_name"].startswith("cslb-v1-c-"))
    # Metadata discovery alone is not integrity verification. Download both assets.
    def download(asset_id):
        result = subprocess.run(["gh-manunruks", "api", "--hostname", "github.com", "-H",
            "Accept: application/octet-stream", "-H", "X-GitHub-Api-Version: " + API_VERSION,
            PREFIX + "/releases/assets/" + str(asset_id)], capture_output=True, check=True, timeout=60)
        return result.stdout
    cold_catalog = json.loads(download(cold_catalog_release["assets"][0]["id"]))
    recovered = download(cold_catalog["asset_id"])
    assert hashlib.sha256(recovered).hexdigest() == cold_catalog["asset_sha256"]
    inventory = api.get("/releases?per_page=100")
    total_assets = sum(len(row["assets"]) for row in inventory)
    total_bytes = sum(asset["size"] for row in inventory for asset in row["assets"])
    assert len(inventory) <= 5 and total_assets <= 10 and total_bytes <= 10485760
    write(args.out, "remote-result.json", {"repo_id": REPO_ID, "releases": len(inventory),
        "assets": total_assets, "bytes": total_bytes, "make_latest_false_preserved_sentinel": True,
        "ff_rejected_stale_sibling": True, "metadata_discovery_paginated": True,
        "asset_download_hash_verified": True, "cold_discovery_scope": "fresh variables from repo listing; not isolated encrypted E1",
        "simulated_lost_response_adoption": True, "objects_immutable_by_client": True,
        "lease_expiry_clock_and_permissions_revocation": "not tested live; offline tests only",
        "no_delete": True, "inventory": [{"id": r["id"], "tag": r["tag_name"],
            "assets": [{"id": a["id"], "name": a["name"], "bytes": a["size"]} for a in r["assets"]]} for r in inventory]})
    print("F0 remote evidence:", args.out)


if __name__ == "__main__":
    main()
