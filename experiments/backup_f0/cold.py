"""Read-only cold-B experiment with authorized credential over stdin, never disk."""

import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from .backend import API_VERSION, check_repo
from . import contracts
from .remote import REPO, REPO_ID
from .run import write


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def child(root, age_bin=None):
    incoming = sys.stdin.buffer.read(16384).decode().strip()
    payload = json.loads(incoming) if incoming.startswith("{") else {"token": incoming}
    credential = payload["token"]
    if not credential:
        raise ValueError("No authorized credential in memory")
    opener = urllib.request.build_opener(NoRedirect())
    calls = 0
    def get(endpoint, binary=False):
        nonlocal calls
        if endpoint != "user" and not endpoint.startswith("repos/" + REPO):
            raise ValueError("Cold reader endpoint outside synthetic authorization")
        calls += 1
        request = urllib.request.Request("https://api.github.com/" + endpoint, headers={
            "Authorization": "Bearer " + credential,
            "Accept": "application/octet-stream" if binary else "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION, "User-Agent": "csl-f0-cold-synthetic"})
        try:
            with opener.open(request, timeout=30) as response:
                data = response.read()
        except urllib.error.HTTPError as error:
            if binary and error.code == 302:
                url = error.headers.get("Location", "")
                parsed = urllib.parse.urlparse(url)
                if parsed.scheme != "https" or parsed.hostname not in (
                        "release-assets.githubusercontent.com", "objects.githubusercontent.com"):
                    raise RuntimeError("Unexpected asset redirect; no credential forwarded") from None
                with opener.open(urllib.request.Request(url), timeout=30) as response:
                    data = response.read()
            else:
                raise RuntimeError("Cold GitHub HTTP " + str(error.code) + "; details suppressed") from None
        return data if binary else json.loads(data)
    if get("user").get("login") != "manunruks":
        raise ValueError("Effective identity mismatch")
    prefix = "repos/" + REPO
    check_repo(REPO_ID, get(prefix))
    pages = []
    for index in range(1, 7):
        rows = get(prefix + "/releases?per_page=1&page=" + str(index))
        if not rows:
            break
        pages.extend(rows)
    if age_bin:
        checkpoint = next(row for row in pages if any(a["name"] == "catalog.age" for a in row["assets"]))
    else:
        checkpoint = next(row for row in pages if row["tag_name"].startswith("cslb-v1-c-"))
    catalog_asset = next(a for a in checkpoint["assets"] if a["name"] == "catalog.age") if age_bin else checkpoint["assets"][0]
    catalog_bytes = get(prefix + "/releases/assets/" + str(catalog_asset["id"]), True)
    def decrypt(content):
        fd = os.memfd_create("csl-f0-external-recovery")
        try:
            os.write(fd, payload["external_identity"].encode())
            os.lseek(fd, 0, os.SEEK_SET)
            result = subprocess.run([str(age_bin), "-d", "-o", "-", "-i", "/proc/self/fd/" + str(fd)],
                input=content, pass_fds=(fd,), capture_output=True, timeout=30)
            if result.returncode:
                raise RuntimeError("Synthetic encrypted cold verification failed")
            return result.stdout
        finally:
            os.close(fd)
    catalog = json.loads(decrypt(catalog_bytes) if age_bin else catalog_bytes)
    if catalog["repo_id"] != REPO_ID or catalog.get("synthetic_only") is not True:
        raise ValueError("Synthetic catalog binding mismatch")
    asset_id = catalog["container_asset_id"] if age_bin else catalog["asset_id"]
    content = get(prefix + "/releases/assets/" + str(asset_id), True)
    expected_hash = catalog["container_ciphertext_sha256"] if age_bin else catalog["asset_sha256"]
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise ValueError("Cold object checksum mismatch")
    members_verified = 0
    if age_bin:
        if len(content) != catalog["container_ciphertext_bytes"]:
            raise ValueError("Ciphertext length binding mismatch")
        catalog.pop("synthetic_only")
        contracts.validate("layout", catalog)
        with zipfile.ZipFile(io.BytesIO(decrypt(content))) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            contracts.validate("container", manifest)
            if (manifest["container_id"] != catalog["container_id"] or
                    manifest["repo_id"] != catalog["repo_id"] or
                    manifest["members"] != catalog["members"]):
                raise ValueError("Interior container/member binding mismatch")
            expected_paths = {m["path"] for m in manifest["members"]} | {"manifest.json"}
            if set(archive.namelist()) != expected_paths or len(archive.namelist()) != len(expected_paths):
                raise ValueError("Unexpected or duplicate container member")
            for member in manifest["members"]:
                data = archive.read(member["path"])
                if len(data) != member["bytes"] or hashlib.sha256(data).hexdigest() != member["sha256"]:
                    raise ValueError("Member hash/size mismatch")
                members_verified += 1
    # No source journal, cache, package or native identity is input to this child.
    write(root, "cold-result.json", {"repo_id": REPO_ID, "authenticated_as": "manunruks",
        "repo_discovered": True, "catalog_downloaded": True, "object_downloaded_and_hash_verified": True,
        "credential_transport": "stdin memory only; own externally authorized credential",
        "home": "fresh B", "codex_home": "fresh B", "A_hidden": True,
        "network": "read-only GitHub API and credential-free allowlisted asset redirect",
        "remote_calls": calls, "source_state_inputs": [],
        "encrypted": bool(age_bin), "members_verified": members_verified,
        "container_downloads": 1 if age_bin else 0,
        "scope": "F0 cold retrieval/verification; NOT E1 native session installation or operational custody"})
    credential = None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--hide-a", type=Path)
    parser.add_argument("--identity-helper", type=Path)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--age-bin", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    root = args.out.resolve()
    if args.child:
        child(root, args.age_bin)
        return
    if not args.hide_a or not args.identity_helper:
        raise ValueError("Explicit A and authorized identity helper required")
    spec = importlib.util.spec_from_file_location("authorized_agent_identity", args.identity_helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = module.Client()
    try:
        launch(root, args.hide_a, client._token.encode())
    finally:
        client.close()
    print("Cold F0 evidence:", root)


def launch(root, hidden_a, payload, age_bin=None):
    root = Path(root).resolve()
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    (root / "home").mkdir(mode=0o700)
    (root / "codex").mkdir(mode=0o700)
    command = ["bwrap", "--die-with-parent", "--ro-bind", "/", "/",
        "--dev-bind", "/dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        "--tmpfs", str(hidden_a.resolve()), "--bind", str(root), str(root),
        "--setenv", "HOME", str(root / "home"), "--setenv", "CODEX_HOME", str(root / "codex"),
        sys.executable, "-m", "experiments.backup_f0.cold", "--child", "--out", str(root)]
    if age_bin:
        command.extend(["--age-bin", str(age_bin)])
    result = subprocess.run(command, input=payload, capture_output=True,
        env={"PATH": os.environ["PATH"], "LANG": "C.UTF-8"}, timeout=180)
    if result.returncode:
        # No exception body or subprocess stderr can accidentally log a token.
        write(root, "cold-failure.json", {"exit": result.returncode,
            "diagnostic": "child failed; secret-bearing stderr intentionally not persisted"})
        raise RuntimeError("Cold B reader failed; no auth or source files copied")


if __name__ == "__main__":
    main()
