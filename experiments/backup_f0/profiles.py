"""Controlled synthetic native/portable and age experiments. Never user data."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import zipfile

REPO = Path(__file__).resolve().parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fixture(case, sid):
    stamp = "2026-11-09T00:00:00Z"
    def row(kind, payload):
        return {"timestamp": stamp, "type": kind, "payload": payload}
    rows = [row("session_meta", {"id": sid, "session_id": sid, "cwd": "/synthetic-only",
        "timestamp": stamp, "originator": "codex_cli_rs", "cli_version": "0.167.0",
        "model_provider": "offline_synthetic", "source": "exec" if case == "agent" else "cli"}),
        row("response_item", {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "SYNTHETIC caf" + chr(233) + " fixture"}]}),
        row("event_msg", {"type": "user_message", "message": "SYNTHETIC USER", "images": [],
                           "local_images": [], "text_elements": []})]
    if case in ("tools", "error", "pending"):
        rows.append(row("response_item", {"type": "function_call", "call_id": "call_f0",
                    "name": "synthetic_never_execute", "arguments": '{"fixture":true}'}))
        if case != "pending":
            rows.append(row("response_item", {"type": "function_call_output", "call_id": "call_f0",
                "output": "SYNTHETIC ERROR" if case == "error" else "SYNTHETIC RESULT"}))
    if case == "opaque":
        rows.append(row("response_item", {"type": "reasoning", "encrypted_content": "SYNTHETIC-OPAQUE-NOT-REAL-CIPHERTEXT", "summary": []}))
    if case == "compaction":
        rows.append(row("compacted", {"message": "SYNTHETIC SUMMARY", "replacement_history": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "SYNTHETIC SUMMARY"}]},
            {"type": "reasoning", "encrypted_content": "SYNTHETIC-OPAQUE", "summary": []}]}))
    rows.extend([row("response_item", {"type": "message", "role": "assistant",
        "content": [{"type": "output_text", "text": "SYNTHETIC ANSWER"}]}),
        row("event_msg", {"type": "agent_message", "message": "SYNTHETIC ANSWER", "phase": "final_answer"})])
    # Deliberately noncanonical whitespace/order/UTF-8; raw export must not be
    # mistaken for byte-exact native preservation.
    return b"".join((json.dumps(r, ensure_ascii=False, separators=(", ", ": ")) + " \n").encode() for r in rows)


def native_cut(data):
    cut = data[:data.rfind(b"\n") + 1]
    for line in cut.splitlines():
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get("payload"), dict):
            raise ValueError("Unsupported native row")
    return cut


def native_probe(source, sid, hidden_a, runtime, expected):
    script = ("import json,sys; from pathlib import Path; "
              "sys.path.insert(0,sys.argv[1]); from native_rpc import probe; "
              "print(json.dumps(probe(Path(sys.argv[2]),sys.argv[3],'F0',json.loads(sys.argv[4]))))")
    cmd = ["bwrap", "--unshare-net", "--die-with-parent", "--ro-bind", "/", "/",
           "--dev-bind", "/dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
           "--tmpfs", str(hidden_a), "--bind", str(runtime), str(runtime),
           "--setenv", "HOME", str(runtime), "--setenv", "CODEX_HOME", str(runtime / "codex"),
           sys.executable, "-c", script, str(REPO / "benchmarks/consolidation"), str(source), sid, json.dumps(expected)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=45,
        env={"PATH": os.environ["PATH"], "LANG": "C.UTF-8"})
    if result.returncode:
        return {"accepted": False, "reason": "probe_process_failed", "exit": result.returncode,
                "detail": result.stderr[-1000:]}
    return json.loads(result.stdout)


def compare(root, native=False):
    root = Path(root).resolve()
    source_home, b = root / "A", root / "B"
    source_home.mkdir(mode=0o700)
    b.mkdir(mode=0o700)
    results = []
    env = {"PATH": os.environ["PATH"], "HOME": str(source_home),
           "CODEX_HOME": str(source_home / "codex"), "LANG": "C.UTF-8"}
    for case in ("text", "tools", "error", "pending", "archived", "agent", "opaque", "compaction", "external_dependency"):
        sid = str(uuid.uuid5(uuid.NAMESPACE_URL, "csl-f0:" + case))
        original = fixture(case, sid)
        if case == "external_dependency":
            original = original.replace(b"SYNTHETIC ANSWER", b"SYNTHETIC ANSWER; external /missing/fixture.pdf not captured")
        source = source_home / (case + ".jsonl")
        source.write_bytes(original)
        expected = ["SYNTHETIC ANSWER"]
        if case == "tools":
            expected.append("SYNTHETIC RESULT")
        if case == "error":
            expected.append("SYNTHETIC ERROR")
        cut = native_cut(original + b'{"partial":')
        captured = b / (case + "-native.jsonl")
        captured.write_bytes(cut)
        row = {"case": case, "source_sha256": sha(original), "source_bytes": len(original),
               "native_byte_exact": cut == original, "partial_tail_deferred": True,
               "allowlist": ["complete JSONL prefix"], "sidecars_captured": [],
               "excluded": ["auth", "config", "global indexes", "projects", "external attachments"],
               "source_visibility": case if case in ("agent", "archived") else "interactive",
               "visibility_preservation": "not tested by thread/read; F1 gate",
               "capture_native_load": native_probe(captured, sid, source_home, b, expected) if native else "not_run"}
        for mode in ("raw", "portable"):
            bundle = b / (case + "-" + mode + ".zip")
            cmd = [sys.executable, str(REPO / "codex_sessions.py"), "export", str(source), "--to", str(bundle), "--allow-secrets"]
            if mode == "raw":
                cmd.append("--raw")
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
            if result.returncode:
                row[mode] = {"exported": False, "exit": result.returncode, "error": result.stderr[-600:]}
                continue
            with zipfile.ZipFile(bundle) as archive:
                entry = json.loads(archive.read("manifest.json"))["sessions"][0]
                exported = archive.read(entry["file"])
            path = b / (case + "-" + mode + ".jsonl")
            path.write_bytes(exported)
            row[mode] = {"exported": True, "bytes": len(exported), "zip_bytes": bundle.stat().st_size,
                "sha256": sha(exported), "byte_exact": exported == original,
                "opaque_marker_retained": b"SYNTHETIC-OPAQUE" in exported,
                "pending_call_preserved": case != "pending" or (b"function_call" in exported and b"function_call_output" not in exported),
                "encrypted_items_removed": entry.get("encrypted_items_removed"),
                "native_load": native_probe(path, sid, source_home, b, expected) if native else "not_run"}
        row["source_intact"] = source.read_bytes() == original
        results.append(row)
    return results


def encryption_trial(age_dir):
    age, keygen = Path(age_dir) / "age", Path(age_dir) / "age-keygen"
    version = subprocess.check_output([str(age), "--version"], text=True).strip()
    if version != "v1.3.2":
        raise ValueError("F0 age pin mismatch")
    identities, recipients = [], []
    for _ in range(3):
        private = subprocess.check_output([str(keygen)], stderr=subprocess.DEVNULL)
        recipient = subprocess.check_output([str(keygen), "-y"], input=private, stderr=subprocess.DEVNULL).decode().strip()
        identities.append(private)
        recipients.append(recipient)
    marker = b"SYNTHETIC-ENCRYPTION-FIXTURE-ONLY"
    cipher = subprocess.check_output([str(age), "-r", recipients[0], "-r", recipients[1]], input=marker,
                                     stderr=subprocess.DEVNULL)
    def decrypt(identity, content):
        fd = os.memfd_create("csl-f0-synthetic-identity")
        try:
            os.write(fd, identity)
            os.lseek(fd, 0, os.SEEK_SET)
            return subprocess.run([str(age), "-d", "-i", "/proc/self/fd/" + str(fd)], input=content,
                                  capture_output=True, pass_fds=(fd,), timeout=20)
        finally:
            os.close(fd)
    operational = decrypt(identities[0], cipher)
    external = decrypt(identities[1], cipher)
    wrong = decrypt(identities[2], cipher)
    corrupt = decrypt(identities[1], cipher[:-1] + bytes([cipher[-1] ^ 1]))
    assert operational.stdout == external.stdout == marker
    assert wrong.returncode != 0 and corrupt.returncode != 0
    return {"version": version, "operational_decrypt": True, "external_decrypt": True,
            "wrong_key_rejected": True, "tamper_rejected": True,
            "ciphertext_contains_marker": marker in cipher,
            "private_material_on_disk_or_evidence": False,
            "scope": "in-memory synthetic cryptographic roundtrip; NOT E1 cold encrypted restore",
            "bytes": len(cipher), "ciphertext_sha256": sha(cipher)}
