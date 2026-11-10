# CSL synthetic demo assets

These are executed demonstrations using synthetic fixtures, not a real user's
conversation, a customer testimonial or a compatibility guarantee. `demo.json`
contains public-safe results for the landing page. It includes four verified
local actions and two actual Codex model continuations. `offline.json` records a
separate run without inference. No raw provider streams, credentials, account
identities, private paths or real histories are included.

Run the offline demo from this directory with Python 3.11+ and an existing CSL
checkout. No native Codex/Claude binary, login, dependency installation or network
is required:

```bash
python3 demo.py --repo /path/to/context-session-librarian --out offline-reproduction.json
```

The script creates its own fixed synthetic Codex and Claude fixtures and runs the
checkout's actual `codex_sessions.py` commands. It exports a ZIP, validates its
checksum, inspects it without installation, imports it under a new UUID and
performs the experimental Claude → Codex conversion. Assertions check source
SHA-256 immutability, normalized historical text/tool equality, a new identity and
the retained commentary phase. `HOME`, `CODEX_HOME` and `CLAUDE_CONFIG_DIR` are
separate temporary directories. The temporary fixtures/packages/homes are removed
on exit. It never reads personal histories. Two independent offline runs produced
identical fixtures, checks and step outcomes; the generated timestamp and native
new identities may differ. The reported source checksums are deterministic.

In JSON command templates, `$WORK` represents the script's disposable directory.
The commands were actually executed with that placeholder expanded internally;
`output` contains concise verified result text, not raw terminal logs. The
landing animation should be labelled **replay of verified synthetic demo results**.
It is a replay, not a live terminal or a recording of a real user's session.
Timing, cursor movement or transitions supplied by the landing are illustrative.

The synthetic history starts with an obsolete draft, corrects the release to
`amber42` and the database to `SQLite`, and places `DEMO-617` only in a historical
tool result. The generated files are labelled fixtures. No original tool runs.

The included live result used Codex CLI **0.166.0**, with **gpt-6.1-sol** confirmed
in both resulting turn contexts. Both the ZIP handoff and Claude → Codex handoff
recalled all three facts. The prompt supplied field names, not the answers, and
tools were disabled: **2/2 continuations passed, zero tools executed**. Reported
usage: **16,829 input + 44 output tokens**, cached input zero. This consumes the
existing ChatGPT plan; no dollar price is inferred. These two calls supplement
the earlier three checks under the same authorized maximum of 24 model attempts.
Claude inference was not retried; these results demonstrate destination Codex
recall only.

Optional live reproduction consumes plan quota and creates only new synthetic
sessions in an already authenticated, explicitly dedicated test home. It never
copies credentials or starts login. Do not pass a personal/custom production home:

```bash
python3 demo.py --repo /path/to/context-session-librarian \
  --out live-reproduction.json --allow-paid \
  --live-codex-home /path/to/already-authenticated-synthetic-test-home
```

This launches at most two model calls with the existing bounded CSL live harness,
90-second per-call timeout, no tool use and no automatic retry loop. Source
fixtures remain unchanged. Default personal homes are rejected; the operator must
ensure any custom home is also dedicated to synthetic testing. Offline checks
measure file structure/history fidelity; actual model checks add bounded recall
evidence. Neither proves universal backend/version/context compatibility.

CSL transfers do not include a repository, credential files or external
attachments that were never embedded. Secret scanning is partial and does not
inspect opaque/binary assets. Imported history is context, not permission to
execute prior instructions. Real conversation content should be reviewed before
sharing; this demonstration contains synthetic material only.
