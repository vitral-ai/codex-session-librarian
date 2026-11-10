"""Seal local F0 evidence with hashes; no secrets, requests or remote mutation."""

import argparse
import hashlib
from pathlib import Path
import subprocess
from .profiles import REPO
from .run import write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    args = parser.parse_args()
    root = args.evidence.resolve()
    def hashes(paths, base):
        return {str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(paths) if p.is_file()}
    tracked = subprocess.check_output(["git", "ls-files", "experiments/backup_f0", "tests/test_backup_f0.py",
        "docs/BACKUP_F0_REVIEW.md", "docs/BACKUP_ADR_002_CONTAINERS.md"], cwd=REPO, text=True).splitlines()
    manifest = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "base": "318332bfe73c5b585651b39b9bd258927e65df22",
        "sources": hashes([REPO / name for name in tracked], REPO),
        "spec_read": hashes(args.spec.glob("*.md"), args.spec),
        "artifacts": hashes((p for p in root.rglob("*") if p.name != "SEALED.json" and "__pycache__" not in p.parts), root)}
    write(root, "SEALED.json", manifest)
    print("Sealed evidence:", root / "SEALED.json")


if __name__ == "__main__":
    main()
