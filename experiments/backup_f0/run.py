"""Generate local synthetic F0 evidence. No network writes or CLI installation."""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import tracemalloc
import uuid

from . import contracts, profiles, scale


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.write_bytes(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True).encode() + b"\n")
    path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--age-dir", type=Path)
    args = parser.parse_args()
    args.out = args.out.resolve()
    os.umask(0o077)
    args.out.mkdir(parents=True, mode=0o700, exist_ok=False)
    start = time.perf_counter()
    for name, schema in contracts.SCHEMAS.items():
        write(args.out, "schemas/" + name + ".json", schema)
    sys.path.insert(0, str(profiles.REPO / "tests"))
    from test_backup_f0 import examples
    vectors = examples()
    for name, vector in vectors.items():
        contracts.validate(name, vector)
    identity = vectors["catalog"]["entries"][0]["identity"]
    write(args.out, "vectors.json", {"canonical_scheme": "csl-json-v1", "namespace": str(contracts.NAMESPACE),
        "valid": vectors, "identity_canonical_utf8": contracts.canonical(identity).decode(),
        "version_key": contracts.digest(identity),
        "object_id": contracts.object_id("11111111-1111-4111-8111-111111111111", contracts.digest(identity)),
        "invalid_mutations": ["unknown schema_version", "unknown field", "bool repo_id", "native+scrub",
                              "empty complete", "coverage mismatch", "cross-source", "oversize asset"]})
    measurements = []
    for count in (100, 1000, 10000):
        tracemalloc.start()
        tick = time.perf_counter()
        catalog = copy.deepcopy(vectors["catalog"])
        template = catalog["entries"][0]
        catalog["entries"] = []
        for index in range(count):
            entry = copy.deepcopy(template)
            entry["identity"]["origin"]["source_uuid"] = str(uuid.uuid5(contracts.NAMESPACE, str(index)))
            entry["version_key"] = contracts.digest(entry["identity"])
            catalog["entries"].append(entry)
        catalog["counts"].update(eligible=count, succeeded=count)
        try:
            contracts.validate("catalog", catalog)
            validation = "passed"
        except ValueError:
            validation = "rejected_by_contract"
        encoded = contracts.canonical(catalog)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        measurements.append({"entries": count, "bytes": len(encoded), "peak_python_bytes": peak,
                             "local_seconds": time.perf_counter() - tick, "validation": validation})
    write(args.out, "catalog-measurements.json", measurements)
    matrix_start = time.perf_counter()
    rows = scale.matrix()
    write(args.out, "scale.json", {"seed": scale.SEED, "kind": "formula estimates, not remote benchmarks",
                                   "scenarios": rows})
    write(args.out, "container-alternative.json", {"default_1000_sessions_1MiB": scale.container_comparison(),
        "size_sensitivity": [scale.container_comparison(size=size) for size in (65536, 1024**2, 8*1024**2)]})
    write(args.out, "scale-summary.json", {"count": len(rows),
        "local_model_seconds": time.perf_counter() - matrix_start,
        "unknown": ["effective credential quotas", "remote latency", "compression", "organization policies"],
        "flagged": {key: sum(bool(r[key]) for r in rows) for key in
                    ("exceeds_256MiB_object", "exceeds_16MiB_catalog", "exceeds_2GiB_run",
                     "bootstrap_exceeds_500_writes_hour", "projected_exceeds_1250_api_hourly_mean")},
        "samples": [scale.scenario(100, 90, 65536, .01, 24, 0),
                    scale.scenario(1000, 90, 1024**2, .1, 6, .01),
                    scale.scenario(10000, 365, 8*1024**2, .5, 1, .05)]})
    work = args.out / "runtime"
    work.mkdir(mode=0o700)
    write(args.out, "profiles.json", profiles.compare(work, args.native))
    if args.age_dir:
        write(args.out, "age.json", profiles.encryption_trial(args.age_dir))
    def version(command):
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        return (result.stdout or result.stderr).splitlines()[0]
    write(args.out, "environment.json", {"base_sha": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=profiles.REPO, text=True).strip(),
        "python": platform.python_version(), "platform": platform.platform(),
        "codex": version(["codex", "--version"]), "gh_manunruks": version(["gh-manunruks", "--version"]),
        "seconds": time.perf_counter() - start, "synthetic_only": True,
        "paid_inference": False, "product_cli_modified": False})
    hashes = {str(path.relative_to(args.out)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in args.out.rglob("*.json")}
    write(args.out, "artifact-hashes.json", hashes)
    print("F0 evidence:", args.out)


if __name__ == "__main__":
    main()
