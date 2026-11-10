"""Capture reproducible test logs without real API/model calls."""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
from .profiles import REPO
from .run import write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--full-opt-ins", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    args.out.mkdir(parents=True, mode=0o700, exist_ok=False)
    env = dict(os.environ)
    if args.full_opt_ins:
        env.update(CSL_RUN_CODEX_NATIVE_TESTS="1", CSL_RUN_CLAUDE_NATIVE_TESTS="1",
                   CSL_RUN_MIGRATION_E2E_TESTS="1", CSL_RUN_MEDIA_TESTS="1", CSL_MEDIA_SANDBOX="required")
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    tick = time.perf_counter()
    result = subprocess.run(command, cwd=REPO, env=env, capture_output=True, timeout=600)
    log = result.stdout + result.stderr
    (args.out / "tests.log").write_bytes(log)
    write(args.out, "result.json", {"command": command, "cwd": str(REPO), "exit": result.returncode,
        "seconds": time.perf_counter() - tick, "full_opt_ins": args.full_opt_ins,
        "log_sha256": hashlib.sha256(log).hexdigest(), "paid_inference": False,
        "base_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()})
    print("F0 regression evidence:", args.out, "exit:", result.returncode)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
