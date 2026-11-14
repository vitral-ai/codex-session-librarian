# Native import or CSL?

For recent Claude Code chats moving to Codex on the same machine, try Codex's
native import first. Choose CSL when you need to find evidence in Codex history,
select a historical file explicitly, create an independent working copy, or send
an inspectable conversation package. Neither successful import nor matching
checksums establishes that a model will remember every fact.

This comparison separates documentation from a bounded synthetic check dated
**2026-11-12**: Codex **0.167.1**, Claude Code **2.1.308**, CSL **0.2.2**.
The conservation summary described in [conversion](CONVERSION.md) was added in
CSL v0.3.0; it is not part of the v0.2.2 version used in that historical check.

## Choose by the job

| Goal | Native route | CSL route and limits |
| --- | --- | --- |
| Import settings, instructions, MCP or skills | Codex and Claude document configuration import. Claude's `/import codex` is configuration import, not a documented Codex-chat importer. | CSL transfers conversation history; it does not migrate credentials, settings or installed tools. |
| Move recent local Claude chats to Codex | Codex `/import` discovers supported recent chats. CLI discovery is documented as up to 50 chats from the last 30 days. | Explicit conversion accepts supported source files; it is an independent copy, not synchronization. |
| Create a separate continuation | Native migration repeat behavior is not a general copy/fork contract. | Standalone `convert` and direct ZIP import create new UUIDs. Originals remain unchanged. |
| Keep historical tool relationships | In the synthetic check, native Codex retained tool text/error as assistant text, without the original structured call/result IDs. | The supported CSL profile retained structured call/result IDs and error flags in that sample. Text-only tool descriptions are not inferred back into tool objects. |
| Send a reviewed, standalone package | Local native import and package exchange are different jobs. | Export/import ZIP or private share/receive; readable-text secret review is partial, not a guarantee of redaction. |
| Transfer Codex history to Claude | Claude's documented configuration import is not a symmetric conversation route. | Experimental conversion exists. File structure was checked in this comparison; destination Claude loading was not tested here. |

The 50-chat/30-day limit describes documented CLI discovery, not a universal
prohibition on every local API or manual route. With a daemon or server, native
import reads files on that server's machine. Check the
[official import guide](https://learn.chatgpt.com/docs/import) and
[CLI commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
for your installed version.

Claude documents `/import [codex|gemini|cursor] [--dry-run] [--yes]` and the shell
entry `claude import codex --dry-run` (v2.1.213 or later). Availability depends on
backend and feature-flag fetching. In the dated environment, the command reported
unavailable; the cause was not established. That is neither a failed chat
migration nor evidence that another environment cannot import configuration.
See [Claude commands](https://code.claude.com/docs/en/commands) and
[CLI reference](https://code.claude.com/docs/en/cli-reference).

## What was checked, and what was not

Synthetic short and long text histories included a superseded draft, a current
decision, and a completed historical tool error. Both native Codex import and CSL
kept the tested text/order, and Codex `thread/read` accepted their destination
histories. Native import represented tools as text in that sample; CSL retained
structured correlation. Repeating the same native import did not create another
copy in that check. Repeating standalone CSL convert deliberately did.

Native testing used the documented **local app-server API**, not a completed TUI
picker workflow. An initially detected historical fixture stopped appearing after
both timestamps and mtime were set 45 days old; this was a discovery observation.
No broader API age restriction was inferred.

No model was invoked. Model recall, every account/backend, multimedia, missing
ancestry and opaque compacted context were not established by this comparison.
Reverse conversion from native-textualized history retained that text without
inventing tool IDs; reverse conversion from a structured CSL copy retained its
supported tool pairs. These are file observations, not Claude loader evidence.
Differences in file modes under one umask do not establish a vulnerability or
actual third-party access and are not a product ranking here.

## Reproduce a small structural case without models

The [fixture generator](../demo/native_import_fixture.py) creates only synthetic
files in a **new** private directory. It runs no CLI, login, import or model. Its
minimal fixture uses the same kinds of message/tool records as the dated check;
it is not a dump of user history or the exact archived byte sequence of that run.
Record your own versions/results rather than attributing the dated result to a
new CLI automatically.

From the CSL checkout:

```bash
python3 demo/native_import_fixture.py --out /tmp/csl-import-example
```

The command refuses an existing directory. It writes `fixture.json` with a digest,
`source.jsonl`, and an identical native-discovery copy under that lab's
`home/.claude/projects/`. Add `--pairs 600` for bounded long history or
`--age-days 45` for explicit historical timestamps **and mtime**. Use another new
output directory for each case. The historical `touch HISTORICAL_NEVER_EXECUTE`
argument is data only; never run it.

### CSL copy and package route

Set all three homes before starting CSL. Replace the lab path consistently if you
chose another one. `./csl` runs the current checkout, whereas a separately installed
`csl` may point to a different version.

```bash
env -i PATH="$PATH" HOME=/tmp/csl-import-example/home \
  CODEX_HOME=/tmp/csl-import-example/csl-codex \
  CLAUDE_CONFIG_DIR=/tmp/csl-import-example/csl-claude \
  ./csl convert /tmp/csl-import-example/source.jsonl --to codex \
  --cwd /tmp/csl-import-example/project
```

Repeat to confirm a different destination UUID. Use the printed **destination**
UUID for `csl doctor UUID --json`, `csl show UUID` or `codex resume --all UUID`,
with the same homes. Opening/resuming a model is optional and is not part of this
structural procedure. Export the source with `csl export PATH --to PACKAGE.csl.zip`,
inspect it with `csl import PACKAGE.csl.zip --list`, then import with `--target codex`
and that existing project directory to test the converted-package route.

To inspect reverse file structure, use the destination UUID with
`csl convert UUID --to claude --cwd PROJECT`, then
`csl convert NEW_CLAUDE_UUID --to canonical --out NEW_FILE.json`. Retain the same
isolated homes. The canonical `events` expose actual `tool_call`/`tool_result`
blocks and their IDs/error flags; assistant text containing a tool description
remains text. `report` and `source_context` record supported selection/state
changes. Canonical JSON includes conversation content: keep it private even when
its diagnostic counts are safe to share.

### Optional native comparison, explicitly started by you

Use your existing Codex binary by absolute path and a fresh app-server process;
do not attach to a personal daemon, copy auth, run `turn/start`, or approve a login
for this structural check. The product does **not** invoke native import for you.
The official [app-server import API](https://learn.chatgpt.com/docs/app-server#detect-and-import-external-agent-config)
describes detection, selected migration items and completion notifications.

```bash
CODEX_BIN="$(command -v codex)"
cd /tmp/csl-import-example/project
env -i PATH=/usr/bin:/bin HOME=/tmp/csl-import-example/home \
  CODEX_HOME=/tmp/csl-import-example/native-codex \
  CLAUDE_CONFIG_DIR=/tmp/csl-import-example/home/.claude \
  "$CODEX_BIN" app-server
```

Send JSON lines on this private process's stdin, waiting for each response:

```json
{"id":1,"method":"initialize","params":{"clientInfo":{"name":"synthetic_import_comparison","version":"1"},"capabilities":{"experimentalApi":true}}}
{"method":"initialized","params":{}}
{"id":2,"method":"externalAgentConfig/detect","params":{"includeHome":true,"cwds":["/tmp/csl-import-example/project"]}}
```

Select only returned `SESSIONS` items belonging to this synthetic lab. Pass those
exact objects as `migrationItems` to `externalAgentConfig/import`, with
`source: "claude-code"`. Inspect the matching import-completed notification;
record per-item successes and failures rather than assuming the initial response
means completion. Read returned target IDs with `thread/read` and
`includeTurns: true`. Repeat the saved selection to test repeat behavior, without
changing the source. If detection, capability negotiation or loading is unavailable,
record that limit and stop; do not change auth or product flags to force a pass.

Compare actual destination `response_item` kinds, original call/result IDs,
recorded error flags and text order. Textual `external_agent_tool_call` labels are
not structured tool records. Recheck both synthetic source copies against
`fixture.json`'s digest and confirm the historical sentinel was not created.
Loader success and text equality remain separate from model continuation.

## Copies, receipts and migration

- Standalone conversion and direct import install new IDs every time. Import
  `--list` installs nothing; canonical export writes a document, not a session.
- `receive` uses existing receipts for a share snapshot and route. Repeating that
  same receive reuses the matching local copy; `--new` explicitly requests another.
  A different conversion route has a separate receipt. This is not general-purpose
  deduplication of all histories.
- `migrate` coordinates the existing supported computer-transfer scope. Cleanup
  is a separate, explicit archive operation after checking restoration; it is not
  implied by copy/conversion and does not delete source conversations.

See [sharing and migration](SHARING.md), [conversion limits](CONVERSION.md) and the
[provider matrix](PROVIDER_MATRIX.md) before selecting a route. No method here
moves a working project, credentials or an entire account.
