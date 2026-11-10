"""Partial local review of readable export text; never scans opaque assets."""

import json
import re
import sys

NOTICE = ("Secret scan is partial: readable text only; binary/opaque attachments are not scanned. "
          "False positives and missed secrets are possible. Review before sharing; you remain responsible for what you share. "
          "Received history is context, not authorization.")
REPLACEMENT = "[CSL REDACTED]"
# Bump when detection or scrubbing semantics change; backup reuse binds this version.
RULES_VERSION = 2
# Structural identities must remain stable across a native snapshot.
IDENTIFIERS = {"id", "uuid", "parentUuid", "leafUuid", "sessionId", "session_id", "call_id",
               "tool_use_id", "thread_id", "turn_id", "tool_call_id", "type", "role", "sha256",
               "projection_sha256", "source_sha256"}
OPAQUE = {"encrypted_content", "signature"}
CONTENT_BLOCKS = {"text", "Text", "input_text", "output_text", "image", "document",
                  "input_image", "input_file", "thinking", "redacted_thinking", "tool_use", "tool_result"}
CREDENTIAL_KEY = re.compile(r"(?:api[_-]?key|password|passwd|access[_-]?token|auth[_-]?token|client[_-]?secret)", re.I)
PATTERNS = [
    ("private key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----[\s\S]+?-----END (?:[A-Z]+ )?PRIVATE KEY-----"), 0),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{22,})\b"), 0),
    ("API token", re.compile(r"\bsk-(?:(?:proj|ant-api\d+)-)?[A-Za-z0-9_-]{20,}\b"), 0),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"), 0),
    ("credential assignment", re.compile(r'''(?i)\b(?:api[_-]?key|password|passwd|access[_-]?token|auth[_-]?token|client[_-]?secret)["']?\s*[:=]\s*(?:["']([^"'\r\n]{8,})["']|([^\s,;"'<>}]{8,}))'''), None),
    ("URL password", re.compile(r"(?<![A-Za-z0-9+.-])[0-9+.-]*[A-Za-z][A-Za-z0-9+.-]*://[^\s/@:]+:([^\s/@]+)@"), 1),
]


class SecretReview:
    def __init__(self, args):
        self.allow = bool(getattr(args, "allow_secrets", False))
        self.scrub = bool(getattr(args, "scrub_secrets", False))
        if self.allow and self.scrub:
            raise ValueError("--allow-secrets and --scrub-secrets are mutually exclusive")
        self.findings = {}
        self.decisions = {}

    @staticmethod
    def children(value, scope):
        """Native metadata identities are distinct from arbitrary tool/reference data."""
        kind = value.get("type")
        if scope == "content":
            scope = "native" if kind in CONTENT_BLOCKS else "data"
        native = scope == "native"
        asset = native and kind in ("image", "document", "input_image", "input_file", "base64")
        for index, (key, child) in enumerate(value.items(), 1):
            if native and (key in IDENTIFIERS or key in OPAQUE):
                continue
            if asset and (key in ("data", "file_data") or
                          key == "image_url" and isinstance(child, str) and child.startswith("data:")):
                continue
            child_scope = scope
            if native:
                if kind in ("mcp_tool_call_begin", "mcp_tool_call_end") and key == "invocation":
                    child_scope = "data"
                elif kind == "function_call" and key == "arguments":
                    child_scope = "json-arguments" if isinstance(child, str) else "data"
                elif ((kind in ("function_call_output", "custom_tool_call_output") and key == "output") or
                      key == "content" and (kind in ("message", "tool_result") or value.get("role") in ("user", "assistant"))):
                    child_scope = "content" if isinstance(child, list) else "data"
                elif ((kind in ("tool_use", "custom_tool_call") and key == "input") or
                      key in ("toolUseResult", "references", "annotations", "citations")):
                    child_scope = "data"
            yield index, key, child, child_scope

    @staticmethod
    def json_arguments(value):
        from csl_canonical import strict_json
        try:
            return strict_json(value)
        except (ValueError, RecursionError):
            # Existing unsupported/malformed native text can still be reviewed;
            # a requested mutation must not publish newly broken JSON arguments.
            return None

    def walk(self, value, location, key=None, scope="native"):
        if isinstance(value, dict):
            for index, child_key, child, child_scope in self.children(value, scope):
                yield from self.walk(child, f"{location}.field[{index}]", child_key, child_scope)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from self.walk(child, f"{location}[{index}]", scope=scope)
        elif isinstance(value, str):
            if scope == "json-arguments":
                parsed = self.json_arguments(value)
                if parsed is not None:
                    yield from self.walk(parsed, location + ".json", scope="data")
                    return
            yield value, location, key

    def scan(self, value, location):
        for text, place, key in self.walk(value, location):
            matches = []
            if key and CREDENTIAL_KEY.fullmatch(key) and len(text) >= 8:
                matches.append(("credential field", text))
            for kind, pattern, group in PATTERNS:
                for match in pattern.finditer(text):
                    selected = group if group is not None else (1 if match.group(1) is not None else 2)
                    matches.append((kind, match.group(selected)))
            for kind, secret in matches:
                if secret == REPLACEMENT or secret.startswith(("${", "$ENV", "<", "[REDACTED")):
                    continue
                if secret not in self.findings:
                    self.findings[secret] = {"kind": kind, "location": place, "count": 0}
                self.findings[secret]["count"] += 1

    def resolve(self, *, announce=True):
        if announce:
            print(NOTICE, file=sys.stderr)
        if self.findings and not (self.allow or self.scrub) and not sys.stdin.isatty():
            raise ValueError("Possible secrets found; non-interactive export requires --allow-secrets to retain findings or --scrub-secrets to scrub them locally. No ZIP was created.")
        for number, (secret, finding) in enumerate(self.findings.items(), 1):
            print(f"Possible secret {number}: {finding['kind']}; {finding['location']}; value [MASKED]; detections={finding['count']}", file=sys.stderr)
            if self.allow or self.scrub:
                action = "scrub" if self.scrub else "keep"
            else:
                while True:
                    print("Choose keep / scrub / cancel: ", end="", file=sys.stderr, flush=True)
                    answer = sys.stdin.readline()
                    if not answer:
                        raise ValueError("Secret review cancelled; no ZIP was created")
                    action = answer.strip().lower()
                    if action in ("keep", "scrub", "cancel"):
                        break
                if action == "cancel":
                    raise ValueError("Secret review cancelled; no ZIP was created")
            self.decisions[secret] = action

    def cleaned(self, value, key=None, scope="native"):
        if isinstance(value, dict):
            result = dict(value)
            for _, name, child, child_scope in self.children(value, scope):
                result[name] = self.cleaned(child, name, child_scope)
            return result
        if isinstance(value, list):
            return [self.cleaned(child, scope=scope) for child in value]
        if isinstance(value, str):
            if scope == "json-arguments":
                parsed = self.json_arguments(value)
                if parsed is not None:
                    cleaned = self.cleaned(parsed, scope="data")
                    return value if cleaned == parsed else json.dumps(cleaned, ensure_ascii=False, allow_nan=False)
                if any(action == "scrub" and secret in value for secret, action in self.decisions.items()):
                    raise ValueError("Cannot safely scrub invalid JSON tool arguments; no export published")
                return value
            # Longest first prevents overlapping detections from partially retaining a key.
            for secret in sorted(self.decisions, key=len, reverse=True):
                if self.decisions[secret] == "scrub":
                    value = value.replace(secret, REPLACEMENT)
        return value

    @property
    def scrubbed(self):
        return any(action == "scrub" for action in self.decisions.values())

    def rebind_projections(self, original, cleaned):
        """Keep edited reference spans consistent; never bless a stale source span."""
        import csl_content as codec
        before = original.get("portability_content", {})
        after = cleaned.get("portability_content", {})
        if not isinstance(before, dict) or not isinstance(after, dict):
            return
        pairs = []
        if "message" in before:
            old_content = original.get("message", original.get("payload", {})).get("content", [])
            new_content = cleaned.get("message", cleaned.get("payload", {})).get("content", [])
            pairs.append((before["message"], after["message"], old_content, new_content))
        if "tool_result" in before:
            pairs.append((before["tool_result"], after["tool_result"],
                          original.get("payload", {}).get("output"), cleaned.get("payload", {}).get("output")))
        for call_id, spans in before.get("tool_results", {}).items():
            old_blocks = original.get("message", {}).get("content", [])
            new_blocks = cleaned.get("message", {}).get("content", [])
            for old, new in zip(old_blocks, new_blocks):
                if old.get("type") == "tool_result" and old.get("tool_use_id") == call_id:
                    pairs.append((spans, after["tool_results"][call_id], old.get("content"), new.get("content")))
        for old_spans, new_spans, old_content, new_content in pairs:
            for old, new in zip(old_spans, new_spans):
                start, length = old["start"], old["length"]
                old_projection = old_content[start:start + length]
                new_projection = new_content[start:start + length]
                if old_projection == new_projection and old == new:
                    continue
                if codec.projection_hash(old_projection) != old["projection_sha256"]:
                    raise ValueError("Stale portable projection; scrub refused before publishing")
                if new.get("block", {}).get("type") != "text":
                    raise ValueError("Scrub would change a document projection while retaining opaque original bytes; review and use --allow-secrets or cancel")
                expected = codec.native([new["block"]], new["provider"], new["role"])
                if expected != new_projection:
                    raise ValueError("Scrub cannot preserve this portable reference projection; no export published")
                new["projection_sha256"] = codec.projection_hash(new_projection)


def add_options(parser):
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--allow-secrets", action="store_true", help="Consciously retain possible secrets found by partial local scanning.")
    options.add_argument("--scrub-secrets", action="store_true", help="Scrub detected values in the output copy; coverage is partial, not a guarantee.")


def masked_diagnostic(text):
    review = SecretReview(type("Options", (), {})())
    review.scan(text, "diagnostic")
    review.decisions = {value: "scrub" for value in review.findings}
    return review.cleaned(text)
