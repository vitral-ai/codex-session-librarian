"""CLI for manual encrypted backup; account/auth remain owned by GitHub CLI."""

import argparse
import json
from pathlib import Path
import sys
import uuid

from csl_backup_core import BackupBusy, BackupStale, json_read, now, save, uid
from csl_backup_crypto import Age, BackupPolicyError, operational_identity
from csl_backup_engine import Backup
from csl_backup_store import GitHub
from csl_secrets import masked_diagnostic
from csl_transfer import TransferError


def last_attempt(root, set_id=None, source_id=None):
    files = list((root / "attempts").glob("*.json"))
    if len(files) > 10000:
        raise TransferError("Local attempt metadata budget exceeded; no truncated status")
    attempts = [json_read(path) for path in files]
    attempts = [a for a in attempts if (not set_id or a.get("set_id") == set_id) and
                (not source_id or a.get("source_id") == source_id)]
    return max(attempts, key=lambda a: a["started_at"]) if attempts else None


def command(args, csl):
    root = csl.DEFAULT_CODEX_HOME / "csl-backup"
    attempt = None
    if args.backup_action in ("run", "restore", "verify") or (args.backup_action == "keys" and args.keys_action == "apply"):
        def safe_id(value):
            try:
                return uid(value) if value else None
            except TransferError:
                return None
        attempt = {"schema_version": 1, "attempt_id": str(uuid.uuid4()), "repo_id": None,
            "set_id": safe_id(args.set), "source_id": safe_id(args.source),
            "operation": args.backup_action, "started_at": now(), "stage": "preparing", "result": "in_progress"}
        try:
            root.mkdir(parents=True, mode=0o700, exist_ok=True)
            root.chmod(0o700)
            save(root / "attempts" / (attempt["attempt_id"] + ".json"), attempt, exclusive=True)
        except (OSError, ValueError):
            print("csl backup: cannot persist a new attempt; operation not started; cached status may be stale", file=sys.stderr)
            raise SystemExit(2) from None
    try:
        config = None
        if args.backup_action == "keys":
            from csl_backup_keys import configuration_path
            if args.keys_action == "apply":
                planned = json_read(args.plan)
                if not isinstance(planned, dict):
                    raise BackupStale("Unknown key rotation plan")
                if planned.get("set_id") != args.set or args.source and planned.get("source_id") != args.source:
                    raise BackupStale("Explicit set/source differs from the rotation plan")
                args.source = uid(planned.get("source_id"))
            path = configuration_path(root, args.set, args.source)
            from csl_backup_format import config as check_config
            config = check_config(json_read(path))
            if attempt:
                attempt.update(repo_id=config["repo_id"], source_id=config["source_id"])
        if args.set and args.backup_action != "keys":
            path = root / "sets" / (uid(args.set) + ".json")
            if args.source and (root / "sets" / args.set / (uid(args.source) + ".json")).exists():
                path = root / "sets" / args.set / (args.source + ".json")
            elif args.backup_action == "run" and not args.source and any((root / "sets" / args.set).glob("*.json")):
                raise TransferError("Multiple locally configured sources; select --source explicitly")
            if path.exists():
                from csl_backup_format import config as check_config
                config = check_config(json_read(path))
                if attempt:
                    attempt.update(repo_id=config["repo_id"], source_id=config["source_id"] if args.backup_action == "run" else attempt["source_id"])
        if args.backup_action == "run" and config and args.source and args.source != config["source_id"]:
            raise TransferError("Explicit --source differs from the configured origin; nothing uploaded")
        if args.backup_action == "keys" and args.keys_action == "list":
            from csl_backup_keys import list_epochs
            result = list_epochs(None, config)
        elif args.backup_action == "status" and args.cached:
            result = {"mode": "cached", "remote": "unknown; not queried",
                "last_attempt": last_attempt(root, args.set, args.source),
                "warning": "Cached success is not current availability or integrity"}
        else:
            repo = args.repo or (config or {}).get("repo")
            if not repo:
                raise TransferError("Specify --repo, or use --set for a locally configured backup")
            gh = GitHub(repo, expected_id=(config or {}).get("repo_id"), executable=args.github_cli)
            if attempt:
                attempt["repo_id"] = gh.repo_id
            needs_age = args.backup_action in ("init", "run", "restore", "verify") or (args.backup_action == "keys" and args.keys_action in ("plan", "apply"))
            backup = Backup(csl, gh, Age(args.age_bin) if needs_age else None)
            if args.backup_action == "init":
                result = backup.initialize(set_name=args.set_name, source_name=args.source_name,
                    profile=args.profile, policy=args.secret_policy, recipients=args.recipient,
                    key_reference=args.key_reference, retain_accepted=args.accept_retain_risk,
                    include_agents=args.include_agent_forks, set_id=args.set)
            elif args.backup_action == "keys":
                from csl_backup_keys import plan_rotation, apply_rotation, list_epochs
                if args.keys_action == "plan":
                    result = plan_rotation(backup, config, args.recipient, key_reference=args.key_reference, output=args.out)
                elif args.keys_action == "apply":
                    attempt.update(stage="executing")
                    save(root / "attempts" / (attempt["attempt_id"] + ".json"), attempt)
                    result = apply_rotation(backup, config, args.plan)
                    attempt.update(result="passed", finished_at=now(), summary=result)
                    save(root / "attempts" / (attempt["attempt_id"] + ".json"), attempt)
                else:
                    result = list_epochs(backup, config)
            elif args.backup_action in ("list", "discover", "status"):
                result = backup.discover(scan=getattr(args, "scan", False))
                if "sets" in result:
                    result["sets"] = {sid: info for sid, info in result["sets"].items() if not args.set or sid == args.set}
                    if args.source:
                        result["sets"] = {sid: {**info, "sources": {source: data for source, data in info["sources"].items()
                            if source == args.source}} for sid, info in result["sets"].items()}
                if args.backup_action == "status":
                    result["last_local_attempt"] = last_attempt(root, args.set, args.source)
            else:
                manual = None
                if args.identity_stdin:
                    if sys.stdin.isatty():
                        raise BackupPolicyError("Pipe the identity from authorized custody; do not type/display it in a terminal")
                    manual = sys.stdin.buffer.read(16385)
                    if not 0 < len(manual) <= 16384:
                        raise BackupPolicyError("Missing or oversized identity on stdin")
                if args.backup_action == "run":
                    if not config:
                        raise TransferError("Run requires a local --set configuration; restore never adopts one")
                    identity = operational_identity(config["key_reference"], manual=manual)
                else:
                    identity = manual or (operational_identity(config["key_reference"]) if config else None)
                    if not identity:
                        raise BackupPolicyError("Cold restore/verify requires an externally held identity via --identity-stdin")
                attempt.update(stage="executing")
                save(root / "attempts" / (attempt["attempt_id"] + ".json"), attempt)
                if args.backup_action == "run":
                    result = backup.run(config, identity, dry_run=args.dry_run, resume=args.resume)
                elif args.backup_action == "restore":
                    result = backup.restore(args.checkpoint, identity, args.cwd, set_id=args.set, source_id=args.source,
                                            dry_run=args.dry_run, new=args.new, allow_partial=args.allow_partial)
                else:
                    result = backup.verify(args.checkpoint, identity, set_id=args.set, source_id=args.source, native=args.native)
                attempt.update(result="partial" if result.get("status") == "partial" else "passed", finished_at=now(), summary=result)
                save(root / "attempts" / (attempt["attempt_id"] + ".json"), attempt)
        print(json.dumps(result, sort_keys=True, indent=None if args.json else 2))
        if result.get("status") == "partial":
            raise SystemExit(2)
        return result
    except (TransferError, OSError, KeyError, TypeError, ValueError) as error:
        if attempt:
            attempt.update(result="failed", finished_at=now(), reason_code=type(error).__name__)
            try:
                save(root / "attempts" / (attempt["attempt_id"] + ".json"), attempt)
            except (OSError, ValueError):
                print("csl backup: failed to persist latest failure; cached status may be stale", file=sys.stderr)
        print("csl backup: " + masked_diagnostic(str(error)), file=sys.stderr)
        raise SystemExit(5 if isinstance(error, BackupStale) else 3 if isinstance(error, BackupPolicyError) else 4 if isinstance(error, BackupBusy) else 2) from None


def add_commands(subparsers, csl):
    parser = subparsers.add_parser("backup", help="Experimental encrypted Codex backups, separate from share/migrate.")
    actions = parser.add_subparsers(dest="backup_action", required=True)
    for name in ("init", "run", "status", "list", "discover", "restore", "verify"):
        sub = actions.add_parser(name)
        sub.add_argument("--repo", help="Existing private GitHub OWNER/REPO; never inherited from team connect.")
        sub.add_argument("--set", help="Opaque backup set UUID.")
        sub.add_argument("--source", help="Opaque source UUID; required when latest would be ambiguous.")
        sub.add_argument("--github-cli", default="gh", help="Explicit GitHub CLI/wrapper executable; CSL never changes its login.")
        sub.add_argument("--age-bin", default="age", help="Explicit optional pinned age executable.")
        sub.add_argument("--json", action="store_true")
        if name == "init":
            sub.add_argument("--set-name", required=True)
            sub.add_argument("--source-name", required=True)
            sub.add_argument("--profile", choices=("native-age-v1", "portable-age-v1"), default="native-age-v1")
            sub.add_argument("--secret-policy", choices=("stop", "scrub", "retain"), default="stop")
            sub.add_argument("--recipient", action="append", required=True, help="Repeat for operational and external recovery public recipients.")
            sub.add_argument("--key-reference", required=True, help="stdin (explicit manual) or keyring:UUID; never a private key/file.")
            sub.add_argument("--accept-retain-risk", action="store_true")
            sub.add_argument("--include-agent-forks", action="store_true")
        if name in ("run", "restore", "verify"):
            sub.add_argument("--identity-stdin", action="store_true", help="Read a private identity from a pipe, never argv/env or saved auth.")
        if name == "run":
            sub.add_argument("--resume", help="Resume the exact durable run UUID/cut; never implies a fresh capture.")
        if name in ("run", "restore"):
            sub.add_argument("--dry-run", action="store_true")
        if name in ("restore", "verify"):
            sub.add_argument("checkpoint", help="Checkpoint UUID, or latest within an unambiguous set/source.")
        if name == "restore":
            sub.add_argument("--allow-partial", action="store_true", help="Explicitly restore a partial checkpoint with omissions/stale coverage.")
            sub.add_argument("--cwd", type=Path, required=True)
            sub.add_argument("--new", action="store_true", help="Explicitly install another copy instead of reusing the verified receipt.")
        if name == "verify":
            sub.add_argument("--native", action="store_true", help="Opt-in disposable localhost request reconstruction; no paid model generation.")
        if name == "status":
            sub.add_argument("--cached", action="store_true", help="Local last-attempt evidence only; remote state remains unknown.")
        if name == "discover":
            sub.add_argument("--scan", action="store_true", help="Read-only candidate scan; does not repair pointers or certify checkpoints.")
        sub.set_defaults(func=lambda args, module=csl: command(args, module))

    keys = actions.add_parser("keys", help="Plan/apply future recipient rotation; no historical re-encryption.")
    key_actions = keys.add_subparsers(dest="keys_action", required=True)
    for action in ("plan", "apply", "list"):
        sub = key_actions.add_parser(action)
        sub.add_argument("--repo")
        sub.add_argument("--set", required=True)
        sub.add_argument("--source", help="Select one existing local origin; never adopts a lost source.")
        sub.add_argument("--github-cli", default="gh")
        sub.add_argument("--age-bin", default="age")
        sub.add_argument("--json", action="store_true")
        if action == "plan":
            sub.add_argument("--recipient", action="append", required=True, help="Exactly two new public X25519 recipients.")
            sub.add_argument("--key-reference", help="Future stdin or keyring:UUID reference; no private material.")
            sub.add_argument("--out", type=Path, help="Exclusive output plan path; default private local plan directory.")
        if action == "apply":
            sub.add_argument("--plan", type=Path, required=True)
        sub.set_defaults(backup_action="keys", func=lambda args, module=csl: command(args, module))
