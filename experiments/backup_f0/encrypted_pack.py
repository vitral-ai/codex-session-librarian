"""Last two authorized releases: synthetic encrypted two-member pack + catalog."""

import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import uuid
import zipfile

from . import contracts as c, profiles
from .backend import check_repo, release_payload
from .cold import launch
from .remote import API, PREFIX, REPO_ID
from .run import write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--age-dir", type=Path, required=True)
    parser.add_argument("--identity-helper", type=Path, required=True)
    parser.add_argument("--hide-a", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    root = args.out.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    api = API(root)
    check_repo(REPO_ID, api.get(""))
    before = api.get("/releases?per_page=100")
    if len(before) != 3 or sum(len(r["assets"]) for r in before) != 2:
        raise ValueError("Expected exact prior F0 inventory; no blind retry or cleanup")
    age, keygen = args.age_dir / "age", args.age_dir / "age-keygen"
    if subprocess.check_output([str(age), "--version"], text=True).strip() != "v1.3.2":
        raise ValueError("age pin mismatch")
    keys, recipients = [], []
    for _ in range(2):
        key = subprocess.check_output([str(keygen)], stderr=subprocess.DEVNULL)
        keys.append(key)
        recipients.append(subprocess.check_output([str(keygen), "-y"], input=key, stderr=subprocess.DEVNULL).decode().strip())
    recipients.sort()
    def encrypt(data):
        command = [str(age)]
        for recipient in recipients:
            command.extend(["-r", recipient])
        return subprocess.check_output(command, input=data, stderr=subprocess.DEVNULL)
    set_id, source_id, run_id, checkpoint_id = [str(uuid.uuid4()) for _ in range(4)]
    container_id = str(uuid.uuid5(c.NAMESPACE, run_id + ":synthetic-two-member-container"))
    members, contents = [], {}
    for case in ("text", "pending"):
        sid = str(uuid.uuid5(c.NAMESPACE, run_id + ":" + case))
        data = profiles.fixture(case, sid)
        identity = {"origin": {"set_id": set_id, "source_id": source_id, "provider": "codex", "source_uuid": sid},
            "source_sha256": profiles.sha(data), "state": "interactive", "profile": "native-age-v1",
            "fingerprint": {"exporter": "csl-f0-prototype", "format": "native-prefix-v1",
                "policy": "stop", "detector": "synthetic-no-credentials", "cipher": "age-v1-x25519", "recipients": recipients}}
        version_key = c.digest(identity)
        member_id = c.object_id(run_id, version_key)
        member = {"member_id": member_id, "origin": identity["origin"], "version_key": version_key,
                  "path": "members/" + member_id + ".jsonl", "bytes": len(data), "sha256": profiles.sha(data)}
        members.append(member)
        contents[member["path"]] = data
    manifest = {"format": "csl-backup-container", "schema_version": 1, "repo_id": REPO_ID,
        "set_id": set_id, "source_id": source_id, "run_id": run_id, "container_id": container_id,
        "layout_kind": "normal", "members": members}
    c.validate("container", manifest)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", c.canonical(manifest))
        for name, data in contents.items():
            archive.writestr(name, data)
    ciphertext = encrypt(buffer.getvalue())
    c.validate_cipher_size(len(ciphertext), len(members), "normal")
    # Validate all local packing/cipher constraints BEFORE any mutation.
    existing_bytes = sum(a["size"] for r in before for a in r["assets"])
    if len(ciphertext) > 1024**2 or existing_bytes > 1024**2:
        raise ValueError("Synthetic F0 size budget guard")
    head = api.get("/git/ref/heads/main")["object"]["sha"]
    def publish(tag, name, data, descriptor_id):
        release = api.post("/releases", release_payload(tag, head))
        target = root / name
        target.write_bytes(data)
        url = "https://uploads.github.com/" + PREFIX + "/releases/" + str(release["id"]) + "/assets?name="
        asset, error = api.call("POST", url + name, raw=target)
        if error:
            raise RuntimeError("Inspect accepted remote state before retry")
        descriptor = {"schema_version": 1, "object_id": descriptor_id, "cipher": "age-v1-x25519",
                      "ciphertext_bytes": len(data), "ciphertext_sha256": profiles.sha(data)}
        file = root / (name + ".descriptor.json")
        file.write_bytes(c.canonical(descriptor))
        _, error = api.call("POST", url + "descriptor.json", raw=file)
        if error:
            raise RuntimeError("Descriptor failed; do not replace asset")
        return asset
    pack = publish("cslb-v1-o-" + container_id, "container.age", ciphertext, container_id)
    catalog = {"format": "csl-backup-layout", "schema_version": 1, "repo_id": REPO_ID,
        "set_id": set_id, "source_id": source_id, "checkpoint_id": checkpoint_id,
        "container_id": container_id, "container_asset_id": pack["id"],
        "container_ciphertext_sha256": profiles.sha(ciphertext), "container_ciphertext_bytes": len(ciphertext),
        "layout_kind": "normal", "cipher": "age-v1-x25519", "members": members}
    c.validate("layout", catalog)
    catalog_cipher = encrypt(c.canonical({**catalog, "synthetic_only": True}))
    if len(catalog_cipher) + len(ciphertext) + existing_bytes > 10485760 - 4096:
        raise ValueError("F0 asset budget exceeded")
    publish("cslb-v1-c-" + checkpoint_id, "catalog.age", catalog_cipher, checkpoint_id)
    spec = importlib.util.spec_from_file_location("authorized_identity", args.identity_helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = module.Client()
    try:
        # Cold process gets ONLY own authorized transport token + external key.
        # No operational private key, catalog, member UUID or state from A.
        payload = c.canonical({"token": client._token, "external_identity": keys[1].decode()})
        launch(root / "cold-B", args.hide_a, payload, age.resolve())
    finally:
        client.close()
        keys.clear()
    inventory = api.get("/releases?per_page=100")
    assets = [asset for release in inventory for asset in release["assets"]]
    if len(inventory) != 5 or len(assets) > 10 or sum(a["size"] for a in assets) > 10485760:
        raise ValueError("Remote F0 budget mismatch; no deletion attempted")
    write(root, "encrypted-result.json", {"repo_id": REPO_ID, "releases": len(inventory),
        "assets": len(assets), "bytes": sum(a["size"] for a in assets), "members": 2,
        "cipher_bytes": len(ciphertext), "plain_member_bytes": sum(m["bytes"] for m in members),
        "container_download_amplification": len(ciphertext) / min(m["bytes"] for m in members),
        "object_and_catalog_encrypted": True, "external_only_cold_B_passed": True,
        "operational_private_passed_to_B": False, "private_keys_on_disk": False,
        "e1": "not closed: no product install or operational keyring custody",
        "no_delete": True, "inventory": [{"release_id": r["id"], "tag": r["tag_name"],
            "assets": [{"asset_id": a["id"], "name": a["name"], "bytes": a["size"]} for a in r["assets"]]} for r in inventory]})
    print("Encrypted F0 evidence:", root)


if __name__ == "__main__":
    main()
