"""Versioned F0 wire-contract candidates; standard library only."""

import hashlib
import json
import re
import uuid
from datetime import datetime

NAMESPACE = uuid.UUID("e13079ba-d83d-5bb6-ae72-c436da9c98d6")
MAX_CATALOG = 16 * 1024 * 1024
MAX_OBJECT = 256 * 1024 * 1024
MAX_ENTRIES = 10000
PROFILES = ["native-age-v1", "portable-age-v1", "synthetic-native-v1", "synthetic-portable-v1"]
EXIT_CODES = {"complete": 0, "failed_or_partial": 2, "policy_or_key": 3,
              "busy_or_lease": 4, "stale_or_confirmation": 5}


class ContractError(ValueError):
    pass


def canonical(value):
    """csl-json-v1: UTF-8, sorted keys, no floats, no whitespace or normalization."""
    def check(v):
        if isinstance(v, dict):
            if not all(isinstance(k, str) for k in v):
                raise ContractError("Non-string JSON key")
            for child in v.values():
                check(child)
        elif isinstance(v, list):
            for child in v:
                check(child)
        elif v is not None and type(v) not in (str, int, bool):
            raise ContractError("Unsupported canonical JSON value")
    check(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def object_id(run_id, version_key):
    validate_value(run_id, {"type": "string", "format": "uuid"})
    validate_value(version_key, {"type": "string", "pattern": "^[0-9a-f]{64}$"})
    return str(uuid.uuid5(NAMESPACE, run_id + ":" + version_key))


def obj(fields):
    return {"type": "object", "properties": fields, "required": list(fields),
            "additionalProperties": False}


S = {"type": "string", "minLength": 1, "maxLength": 4096}
U = {"type": "string", "format": "uuid"}
H = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
T = {"type": "string", "format": "utc"}
I = {"type": "integer", "minimum": 0}
POS = {"type": "integer", "minimum": 1}
B = {"type": "boolean"}
ORIGIN = obj({"set_id": U, "source_id": U, "provider": {"enum": ["codex"]}, "source_uuid": U})
FINGERPRINT = obj({"exporter": S, "format": S, "policy": {"enum": ["stop", "retain", "scrub"]},
                   "detector": S, "cipher": S,
                   "recipients": {"type": "array", "items": S, "maxItems": 32}})
IDENTITY = obj({"origin": ORIGIN, "source_sha256": H,
                "state": {"enum": ["interactive", "archived", "agent"]},
                "profile": {"enum": PROFILES}, "fingerprint": FINGERPRINT})
EVIDENCE = obj({"state": {"enum": ["referenced", "available", "integrity_verified", "restored"]},
                "at": T, "scope": S, "result": {"enum": ["passed", "failed", "unknown"]}})
ENTRY = obj({"identity": IDENTITY, "version_key": H, "object_id": U,
             "release_id": POS, "asset_id": POS, "asset_bytes": {**I, "maximum": MAX_OBJECT},
             "asset_sha256": H, "capture_bytes": I, "captured_at": T, "last_observed_at": T,
             "losses": {"type": "array", "items": S, "maxItems": 100},
             "dependencies": {"type": "array", "items": S, "maxItems": 100},
             "pending_tool_calls": {"type": "array", "items": S, "maxItems": 10000},
             "restore_validation": {"enum": ["structural", "native_passed", "native_unverified", "quarantined"]},
             "evidence": {"type": "array", "items": EVIDENCE, "maxItems": 100}})


def document(name, fields):
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:csl:backup:f0:" + name + ":v1", **obj({
                "format": {"enum": ["csl-backup-" + name]}, "schema_version": {"enum": [1]}, **fields})}


SCHEMAS = {
    "config": document("config", {"repo_id": POS, "repo_name": S, "set_id": U, "source_id": U,
        "profile": {"enum": PROFILES}, "fingerprint": FINGERPRINT, "key_reference": S}),
    "object": document("object", {"repo_id": POS, "set_id": U, "source_id": U, "run_id": U,
        "object_id": U, "cipher": {"enum": ["age-v1-x25519"]},
        "ciphertext_bytes": {**POS, "maximum": MAX_OBJECT}, "ciphertext_sha256": H}),
    "catalog": document("catalog", {"repo_id": POS, "set_id": U, "source_id": U,
        "run_id": U, "checkpoint_id": U, "lease_epoch": POS, "cut_at": T,
        "selection": obj({"provider": {"enum": ["codex"]}, "archives": B, "agent_forks": B}),
        "status": {"enum": ["complete", "partial"]},
        "entries": {"type": "array", "items": ENTRY, "maxItems": MAX_ENTRIES},
        "failures": {"type": "array", "items": obj({"origin": ORIGIN, "code": S}), "maxItems": MAX_ENTRIES},
        "exclusions": {"type": "array", "items": obj({"origin": ORIGIN, "reason": S}), "maxItems": MAX_ENTRIES},
        "counts": obj({"eligible": I, "succeeded": I, "failed": I, "excluded": I})}),
    "control": document("control", {"repo_id": POS, "set_id": U, "lease_epoch": I,
        "lease_owner": {"type": "string", "maxLength": 36}, "expires_at": T,
        "latest_complete": {"type": "string", "maxLength": 36},
        "latest_partial": {"type": "string", "maxLength": 36},
        "intents": {"type": "array", "items": U, "maxItems": 10000}}),
    "intent": document("intent", {"repo_id": POS, "set_id": U, "run_id": U,
        "lease_epoch": POS, "object_id": U, "operation": {"enum": ["object", "catalog", "pointer"]},
        "status": {"enum": ["planned", "accepted", "uncertain", "verified", "abandoned"]}}),
    "receipt": document("receipt", {"repo_id": POS, "set_id": U, "source_id": U,
        "restore_id": U, "checkpoint_id": U, "object_id": U, "installed_uuid": U,
        "installed_sha256": H, "last_restored_at": T,
        "restore_validation": {"enum": ["structural", "native_passed", "native_unverified", "quarantined"]}}),
    "evidence": document("evidence", {"event_id": U, "observer_id": U,
        "repo_id": POS, "set_id": U, "object_id": U, "asset_id": POS,
        "asset_sha256": H, "event": EVIDENCE,
        "operation": {"enum": ["query", "verify", "restore"]},
        "native_validation": {"enum": ["structural", "native_passed", "native_unverified", "quarantined"]},
        "reason_code": S}),
    "restore-intent": document("restore-intent", {"repo_id": POS, "set_id": U,
        "restore_id": U, "checkpoint_id": U, "object_id": U, "asset_id": POS,
        "asset_sha256": H, "installed_uuid": U, "installed_sha256": H,
        "destination": S, "status": {"enum": ["reserved", "published", "receipted", "conflict"]}}),
}

MEMBER = obj({"member_id": U, "origin": ORIGIN, "version_key": H,
              "path": {"type": "string", "pattern": "^members/[0-9a-f-]{36}\\.jsonl$"},
              "bytes": {**POS, "maximum": MAX_OBJECT}, "sha256": H})
SCHEMAS["container"] = document("container", {"repo_id": POS, "set_id": U,
    "source_id": U, "run_id": U, "container_id": U, "layout_kind": {"enum": ["normal", "oversized_single"]},
    "members": {"type": "array", "items": MEMBER, "maxItems": 10000}})
SCHEMAS["layout"] = document("layout", {"repo_id": POS, "set_id": U, "source_id": U,
    "checkpoint_id": U, "container_id": U, "container_asset_id": POS,
    "container_ciphertext_sha256": H, "container_ciphertext_bytes": {**POS, "maximum": MAX_OBJECT},
    "layout_kind": {"enum": ["normal", "oversized_single"]},
    "cipher": {"enum": ["age-v1-x25519"]},
    "members": {"type": "array", "items": MEMBER, "maxItems": 10000}})


def validate_value(value, rule):
    if "enum" in rule and not any(type(value) is type(x) and value == x for x in rule["enum"]):
        raise ContractError("Unknown enumeration")
    kind = rule.get("type")
    expected = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if kind and type(value) is not expected[kind]:
        raise ContractError("Invalid JSON type")
    if kind == "object":
        if set(value) != set(rule["required"]):
            raise ContractError("Missing or unknown fields")
        for key, child in value.items():
            validate_value(child, rule["properties"][key])
    elif kind == "array":
        if len(value) > rule["maxItems"]:
            raise ContractError("Array exceeds limit")
        for child in value:
            validate_value(child, rule["items"])
    elif kind == "string":
        if not rule.get("minLength", 0) <= len(value) <= rule.get("maxLength", 4096):
            raise ContractError("String exceeds limit")
        if "pattern" in rule and re.fullmatch(rule["pattern"], value) is None:
            raise ContractError("Invalid string pattern")
        if rule.get("format") == "uuid":
            if str(uuid.UUID(value)) != value:
                raise ContractError("Noncanonical UUID")
        if rule.get("format") == "utc":
            if not value.endswith("Z") or datetime.fromisoformat(value[:-1] + "+00:00").utcoffset().total_seconds():
                raise ContractError("Expected UTC timestamp")
    elif kind == "integer":
        if not rule.get("minimum", 0) <= value <= rule.get("maximum", 2**63 - 1):
            raise ContractError("Integer exceeds limit")


def validate(name, value):
    validate_value(value, SCHEMAS[name])
    if name == "config":
        profile, policy = value["profile"], value["fingerprint"]["policy"]
        if profile == "native-age-v1" and policy == "scrub":
            raise ContractError("Native byte-exact profile cannot scrub")
        fingerprint = value["fingerprint"]
        if profile.endswith("age-v1"):
            recipients = fingerprint["recipients"]
            if (fingerprint["cipher"] != "age-v1-x25519" or len(set(recipients)) < 2 or
                    recipients != sorted(set(recipients)) or
                    not all(re.fullmatch(r"age1[023456789acdefghjklmnpqrstuvwxyz]{58}", r) for r in recipients) or
                    not value["key_reference"].startswith("keyring:")):
                raise ContractError("Age profile requires coherent cipher, two sorted public recipients and keyring reference")
    if name == "catalog":
        entries, failures, counts = value["entries"], value["failures"], value["counts"]
        if not entries or (value["status"] == "complete" and failures):
            raise ContractError("Empty or incomplete complete checkpoint")
        if value["status"] == "partial" and not failures:
            raise ContractError("Partial requires an eligible failure and a success")
        if counts != {"eligible": len(entries) + len(failures), "succeeded": len(entries),
                       "failed": len(failures), "excluded": len(value["exclusions"])}:
            raise ContractError("Coverage counts differ")
        origins = set()
        for entry in entries:
            identity = entry["identity"]
            origin = identity["origin"]
            if origin["set_id"] != value["set_id"] or origin["source_id"] != value["source_id"]:
                raise ContractError("Cross-source entry")
            key = canonical(origin)
            if key in origins or digest(identity) != entry["version_key"]:
                raise ContractError("Duplicate origin or version mismatch")
            origins.add(key)
        if len(canonical(value)) > MAX_CATALOG:
            raise ContractError("Catalog exceeds limit")
    if name in ("container", "layout"):
        if not value["members"]:
            raise ContractError("Empty container")
        seen = set()
        for member in value["members"]:
            if (member["member_id"] in seen or member["path"] != "members/" + member["member_id"] + ".jsonl" or
                    member["origin"]["set_id"] != value["set_id"] or
                    member["origin"]["source_id"] != value["source_id"]):
                raise ContractError("Duplicate or misbound member")
            seen.add(member["member_id"])
        limit = 64 * 1024 * 1024 if value["layout_kind"] == "normal" else MAX_OBJECT
        if (value["layout_kind"] == "oversized_single" and len(value["members"]) != 1 or
                sum(member["bytes"] for member in value["members"]) > limit):
            raise ContractError("Container exceeds limit")
        if name == "layout":
            validate_cipher_size(value["container_ciphertext_bytes"], len(value["members"]), value["layout_kind"])
    canonical(value)
    return value


def validate_cipher_size(size, members, kind):
    limit = 64 * 1024 * 1024 if kind == "normal" else MAX_OBJECT
    if kind not in ("normal", "oversized_single") or members < 1 or not 0 < size <= limit:
        raise ContractError("Final ciphertext exceeds layout limit")
    if kind == "oversized_single" and members != 1:
        raise ContractError("Oversize layout must contain exactly one logical version")
