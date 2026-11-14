"""Continuity evidence levels: structure, active context, native replay, never live recall."""

from collections import Counter
import json
from pathlib import Path

import csl_canonical as canonical
import csl_claude
from csl_history import codex_effective


def metrics(items):
    text, opaque, multimodal = 0, 0, 0
    pending = [items]
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, dict):
            opaque += value.get("type") in ("compaction", "context_compaction", "compaction_summary")
            multimodal += value.get("type") in ("image", "input_image", "document", "input_file")
            for key, child in value.items():
                if key in ("encrypted_content", "thinking", "signature"):
                    continue
                if key in ("input", "output", "arguments") and isinstance(child, dict):
                    text += len(json.dumps(child, ensure_ascii=False))
                    continue
                if isinstance(child, str) and key in ("text", "output", "arguments", "input", "content"):
                    text += len(child)
                elif isinstance(child, (dict, list)):
                    pending.append(child)
    return {"input_items": len(items), "text_characters": text, "opaque_items": opaque,
            "multimodal_blocks": multimodal}


def analyze(path, provider, *, leaf=None, context_window=None, max_context_chars=None, observation=None):
    result = {"provider": provider, "structure": "not-checked", "active_context": "not-reconstructed",
              "native_replay": "not-tested", "live_continuation": "not-tested",
              "errors": [], "warnings": [], "metrics": None}
    if Path(path).stat().st_size > 64 * 1024 * 1024:
        result["warnings"].append("analysis_limit: transcript exceeds the 64 MiB diagnostic limit")
        return result
    try:
        records = canonical.read_jsonl(path)
        for record in records:
            provenance = record.get("csl_conversion")
            if isinstance(provenance, dict):
                if provenance.get("history_policy") == "visible":
                    result["warnings"].append("visible_history_recovery: this history is labeled recovery, not exact original compacted context")
                if provenance.get("synthetic_tool_results"):
                    result["warnings"].append("synthetic_tool_results: interrupted historical tool outcomes were explicitly marked UNKNOWN")
        counts = Counter(record.get("type") for record in records)
        result["record_types"] = dict(counts)
        if provider == "codex":
            from csl_transfer import validate_compaction
            for record in records:
                validate_compaction(record)
            if not records or records[0].get("type") != "session_meta":
                raise ValueError("Codex history lacks its leading session metadata")
            result["structure"] = "passed"
            if any(not isinstance(record.get("timestamp"), str) for record in records):
                result["warnings"].append("native_record_timestamps_missing: the installed CLI may skip records; use native verification")
            if records[0].get("payload", {}).get("history_base"):
                result["warnings"].append("missing_ancestry: only records in this transcript can be inspected")
            try:
                effective, history_report = codex_effective(records)
            except ValueError as exc:
                result["warnings"].append(f"active_context_unavailable: {exc}")
                return result
            items = [record["payload"] for record in effective if record.get("type") == "response_item"]
            result["history_report"] = dict(history_report)
        else:
            csl_claude.validate(Path(path), _read_records)
            result["structure"] = "passed"
            try:
                chain, _, selected_leaf = canonical.claude_chain(records, leaf)
            except ValueError as exc:
                result["warnings"].append(f"active_context_unavailable: {exc}")
                return result
            items = [record["message"] for record in chain if record.get("type") in ("user", "assistant")]
            result["selected_leaf"] = selected_leaf
        if observation is not None:
            observation.update(observe_native(items, provider))
        result["metrics"] = metrics(items)
        if not items:
            result["warnings"].append("no_model_history: visible events alone do not establish model context")
            return result
        result["active_context"] = "reconstructed-statically"
        if result["metrics"]["opaque_items"]:
            result["warnings"].append("opaque_context: encrypted context cannot be measured or verified across accounts")
        if result["metrics"]["multimodal_blocks"]:
            result["warnings"].append("multimodal_context: text estimates exclude image/document token costs")
        apply_budget(result, context_window, max_context_chars)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        result["structure"] = "failed"
        result["errors"].append(str(exc))
    return result


def _read_records(stream):
    for line in stream:
        if line.strip():
            yield canonical.strict_json(line)


def apply_budget(report, context_window=None, max_context_chars=None):
    values = report.get("metrics")
    if values is None:
        return
    chars = values["text_characters"]
    report["token_estimate"] = {"tokens": (chars + 3) // 4, "exact": False,
                               "method": "text characters / 4; excludes tokenizer, tool schema, hidden and multimodal overhead"}
    if context_window:
        report["requested_context_window"] = context_window
        if report["token_estimate"]["tokens"] >= context_window:
            report["warnings"].append("context_risk: rough text estimate reaches/exceeds the supplied window; not an exact token count")
    if chars >= 1_000_000:
        report["warnings"].append("large_context: inspect native replay and the recipient model limit before continuing")
    if max_context_chars is not None and chars > max_context_chars:
        report["errors"].append(f"Explicit context character limit exceeded: {chars} > {max_context_chars}")


def preflight(path, provider, *, max_context_chars=None, observation=None):
    report = analyze(path, provider, max_context_chars=max_context_chars, observation=observation)
    if max_context_chars is not None and report["metrics"] is None:
        report["errors"].append("Cannot enforce an explicit context character limit without reconstructing the active context")
    if report["errors"]:
        raise ValueError("Continuity preflight failed: " + "; ".join(report["errors"]))
    print(f"continuity: structure={report['structure']}; context={report['active_context']}; native/live=not-tested")
    for warning in report["warnings"]:
        print(f"continuity warning: {warning}")
    return report


def observe_blocks(events):
    """Count recognized in-memory records; never infer tools from historical text."""
    calls, results, errors = Counter(), Counter(), set()
    messages = media = 0
    for event in events:
        blocks = event.get("blocks", [])
        messages += any(b.get("type") in ("text", "image", "document") for b in blocks)
        for block in blocks:
            kind, key = block.get("type"), block.get("call_id")
            if kind in ("image", "document"):
                media += 1
            elif kind in ("tool_call", "tool_result") and isinstance(key, str) and key:
                (calls if kind == "tool_call" else results)[key] += 1
                if kind == "tool_result" and block.get("is_error") is True:
                    errors.add(key)
    paired = {key for key in calls.keys() & results.keys() if calls[key] == results[key] == 1}
    return {"messages": messages, "tool_pairs": len(paired), "error_pairs": len(paired & errors),
            "unpaired_tool_records": sum(calls.values()) + sum(results.values()) - 2 * len(paired),
            "media_blocks": media}


def observe_native(items, provider):
    """Reuse the active items already read for continuity, without another file pass."""
    def events():
        for item in items:
            if provider == "codex":
                kind = item.get("type")
                if kind in ("function_call", "custom_tool_call"):
                    yield {"blocks": [{"type": "tool_call", "call_id": item.get("call_id")}]}
                    continue
                if kind in ("function_call_output", "custom_tool_call_output"):
                    yield {"blocks": [{"type": "tool_result", "call_id": item.get("call_id"),
                                        "is_error": item.get("csl_is_error")}]}
                    continue
                if kind != "message":
                    continue
            if item.get("role") not in ("user", "assistant"):
                continue
            content = item.get("content", [])
            blocks = []
            if isinstance(content, str):
                blocks.append({"type": "text"})
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    kind = block.get("type")
                    if kind in ("text", "input_text", "output_text", "image", "input_image", "document", "input_file"):
                        blocks.append({"type": {"input_text": "text", "output_text": "text",
                            "input_image": "image", "input_file": "document"}.get(kind, kind)})
                    elif provider == "claude" and kind in ("tool_use", "tool_result"):
                        blocks.append({"type": "tool_call" if kind == "tool_use" else "tool_result",
                            "call_id": block.get("id") if kind == "tool_use" else block.get("tool_use_id"),
                            "is_error": block.get("is_error")})
            yield {"blocks": blocks}
    return observe_blocks(events())


def conversion_observation(data):
    """Use validated canonical events/report; no native history re-read or schema change."""
    report = data.get("report", {})
    result = observe_blocks(data["events"])
    synthetic = report.get("synthetic_interruption_results", [])
    # Canonical JSON report is not trusted to invent provenance. Treat an invalid
    # report count as unknown rather than upgrading it to a preservation claim.
    result.update(quarantined_policy=len(data["source_context"]),
                  synthetic_results=len(synthetic) if isinstance(synthetic, list) else None,
                  ignored=report.get("ignored_native_state", {}),
                  visible_recovery=report.get("history_policy") == "visible")
    return result


def print_conservation(report, observation, *, provider, session_id=None, conversion=None, entry=None, reused=False):
    """Human-only summary. Whitelisted labels/counts; no bodies, IDs from tools or paths."""
    print("Conservation (selected history; not a proof of complete equivalence):")
    source = observation if session_id else conversion
    if source:
        pairs = source["tool_pairs"]
        synthetic = conversion.get("synthetic_results", 0) if conversion is not None else 0
        if type(synthetic) is int and 0 <= synthetic <= pairs:
            pairs -= synthetic
        else:
            pairs = None
        pair_text = f"{pairs} correlated historical tool pairs" if pairs is not None else "historical tool provenance not assessed"
        print(f"  Present: {source['messages']} text/media message records; {pair_text}; {source['error_pairs']} result error flags (including any marked repairs).")
        if source.get("unpaired_tool_records"):
            print("  Not assessed: unmatched/duplicate native tool records; no full correlation claim.")
        if source.get("media_blocks"):
            print(f"  Media: {source['media_blocks']} top-level image/document blocks recognized; visual fidelity not tested.")
    else:
        print("  Present: content categories not assessed (continuity analysis unavailable or limited).")
    if conversion is not None:
        print("  Transformed: canonical/native representation and message grouping; destination identity/cwd rebound." if session_id
              else "  Transformed: canonical representation; no native destination identity allocated.")
        if observation and conversion['messages'] != observation['messages']:
            print(f"  Transformed: selected text/media message record count from {conversion['messages']} to {observation['messages']}; counts alone do not establish text equivalence.")
        print(f"  Not replayed as authority: {conversion['quarantined_policy']} source context/policy records.")
        ignored = conversion.get("ignored", {})
        labels = {"reasoning": "reasoning records", "thinking": "thinking blocks",
            "redacted_thinking": "redacted thinking blocks", "omitted_encrypted_agent_blocks": "encrypted agent blocks",
            "configuration_update": "configuration updates not replayed", "additional_tools": "tool-availability records not replayed",
            "ghost_snapshot": "native snapshots not replayed",
            "off_branch_records": "off-branch records", "opaque_state_not_restored": "opaque context items",
            "rendered_provider_actions": "provider actions represented as historical text",
            "applied_compaction_checkpoints": "applied compaction checkpoints",
            "applied_rollback_turns": "applied rollback turns"}
        if isinstance(ignored, dict):
            for key, label in labels.items():
                count = ignored.get(key, 0)
                if type(count) is int and 0 < count <= 10_000_000:
                    print(f"  Reported selection/state change: {count} {label}.")
        if isinstance(ignored, dict):
            bookkeeping = sum(value for key in ("session_meta", "event_msg", "turn_context", "world_state",
                "token_usage_record", "inter_agent_communication_metadata", "retained_context", "system", "progress")
                if type(value := ignored.get(key, 0)) is int and 0 <= value <= 10_000_000)
            if bookkeeping:
                print(f"  Not replayed byte-for-byte: {bookkeeping} native bookkeeping records; destination metadata/UI may be regenerated.")
        if conversion.get("synthetic_results"):
            print("  Transformed: interrupted tool outcomes include synthetic UNKNOWN results, not observed executions.")
        if conversion.get("visible_recovery"):
            print("  Not restored: hidden compacted context/missing ancestry; explicit visible-history recovery only.")
    elif reused:
        print("  Transformed: no new identity; receipt reused the existing local copy. Earlier transfer fidelity not reassessed.")
    else:
        print("  Transformed: native identity/cwd rebound; full source/destination semantic equivalence not assessed.")
    removed = entry.get("encrypted_items_removed", 0) if entry else 0
    if type(removed) is int and 0 < removed <= 10_000_000:
        print(f"  Omitted by source package: {removed} encrypted/thinking items (not recoverable here).")
    elif removed:
        print("  Not assessed: unrecognized source-package omission count.")
    if entry and entry.get("compaction_state_removed") is True:
        print("  Not restored: opaque compaction state removed from the package.")
    print("  Not assessed: complete native/opaque state and universal model continuity.")
    print(f"  Validation: structure={report['structure']}; native CLI loading=not-tested; model continuation=not-tested.")
    if session_id:
        if reused:
            print(f"  Identity: reused {provider} copy {session_id}; no new session installed.")
        else:
            print(f"  Identity: independent {provider} copy {session_id}; open this UUID, not the source. Source files unchanged by this operation.")
        detail = "embedded csl_conversion provenance; " if conversion is not None else ""
        print(f"  Detail: {detail}csl doctor {session_id} --json (destination checks; not a source-equivalence audit).")
    else:
        print("  Detail: canonical output report/source_context; no native session installed.")
