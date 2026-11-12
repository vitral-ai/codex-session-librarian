# Canonical Conversion And Continuity

CSL integrates a bounded, experimental Codex/Claude conversion profile through
`csl-conversation` version 2. This is native transcript reconstruction, not a
generated summary pasted into a new conversation. The core uses only the standard
library. Conversion never fetches credentials or buys model inference; optional
media decoding uses a separate interpreter. Explicit paid verification is a
different command, documented in [live verification](LIVE_VERIFICATION.md).

## Convert And Receive

```bash
csl convert SOURCE_UUID --to claude --cwd ~/work/project
csl convert SOURCE_UUID --to codex --cwd ~/work/project --open --model MODEL
csl import ~/Downloads/handoff.csl.zip --target claude --cwd ~/work/project --open
csl receive csl-xxxxxxxxxxxx --target codex --cwd ~/work/project --open
```

Sources are auto-detected. `--provider` restricts/asserts the source;
`--to` on convert and `--target` on import/receive explicitly choose a destination.
Without a target, existing native transfers stay native. All CSL options must
precede `--open`; subsequent arguments belong to the destination CLI.

Standalone `convert` and direct `import` (including `--target`) install new UUIDs
on every successful invocation and leave originals unchanged. Open the printed
**destination UUID**, not the source UUID. These are independent copies, not a
synchronized migration. `import --list` installs nothing; canonical export only
writes JSON.

A converted `receive` has its own receipt keyed by destination, history selection
and repair options; it never reuses the native copy by mistake. Repeat that same
share snapshot/route to reuse the local copy, or use `--new` for another one.
Source share ancestry is retained when the converted session is later shared back.
This does not change the separate computer-migration/cleanup contract.
See [native import versus CSL](NATIVE_IMPORT_COMPARISON.md) to choose a route.

Canonical JSON can be transferred privately and restored without the source CLI:

```bash
csl convert SOURCE_UUID --to canonical --out ~/Downloads/conversation.json
csl convert ~/Downloads/conversation.json --to claude --cwd ~/work/project
```

Canonical outputs are private `0600` files and cannot overwrite existing files.
The [v2 JSON Schema](canonical-v2.schema.json) describes the multimodal profile.
Canonical JSON is not itself a `.csl.zip` or GitHub release asset; use native
share/receive with `--target`, or transfer that JSON privately and use convert.

## Reading The Conservation Summary

The development checkout adds a human-only summary after successful conversion
or session installation; the published v0.2.2 output predates it. Machine-readable
`doctor --json`, canonical JSON and transfer formats keep their existing schema.

- **Present:** recognized text/media message records and structured tool pairs
  matched by ID in the selected history. Text that merely describes a tool is
  never counted as structured correlation. Error-flag counts include any explicitly
  marked repair results. These counts are not proof of full source equivalence.
- **Transformed/omitted:** canonical/native normalization, source policy quarantined
  instead of replayed as authority, known selection/state changes, and portable
  package losses where recorded. UNKNOWN interruption repair and visible-history
  recovery remain explicit; unavailable hidden state is not invented.
- **Validation:** structural inspection is separate from loading in a native CLI
  and model continuation. Ordinary import/conversion has not run those latter
  checks, even if picker metadata refreshed successfully.

Counts reuse the canonical report or continuity preflight's already loaded items;
there is no additional transcript-file pass for this summary. A missing/limited
analysis is reported as not assessed. Canonical export's detail is in its existing
`report`/`source_context`; converted native files also embed `csl_conversion`
provenance counts. For installed copies, `csl doctor UUID --json` inspects
current destination structure and context, not complete source equivalence.
No message bodies, tool arguments/results, private paths or tool IDs are printed
by the summary.

Fresh receive uses the import summary. Receipt reuse reports the current local
copy and no new identity, without inheriting an old transfer's preservation claim.
Export/share have no equivalent full continuity/canonical report, so they retain
the existing package/portable-removal and partial-secret-review information instead
of adding a speculative preservation summary. `import --list` validates a package
without claiming an installed session. Backup is a separate feature/contract.

## Profile And Fail-Closed Behavior

Text, assistant phases, JSON/text tool calls, completed text results, error flags
and historical citation/reference metadata are preserved. References render as
explicit historical text without opening URLs; hashed projection spans retain
their original metadata and reject stale/edited projections on another conversion.
Tool names and arguments remain historical evidence, not instructions to retry.
When Codex splits a phased assistant message into text and tool-call records,
CSL portability metadata retains the tool-call phase for later conversion.

Codex structured compactions select replacement history before normalization;
Claude selects its parent-linked active branch and stops at readable compaction
summaries. `--leaf UUID` explicitly selects another Claude branch. Rollback is
handled only when it does not cross a compaction; uncertain native windows fail.

System/developer policy, AGENTS/environment context and internal state are not
reinstalled as destination authority. Canonical `source_context` archives that
context separately; native destinations include only provenance hashes/counts.
When a Claude/canonical user message would begin a native Codex text record
with `# AGENTS.md instructions` or `<environment_context>`, conversion to Codex
rejects it before writing a destination. These reserved prefixes would otherwise
be mistaken for source policy on reconversion. This also applies to a text segment
after a tool result. Genuine source policy remains quarantined; ordinary historical
text is not silently removed to make a roundtrip appear faithful.

Source auth, shell settings, MCP definitions and execution permissions are not
translated. The recipient's own CLI configuration and explicit launch flags apply.
Historical assistant model metadata uses a synthetic marker in Claude output;
select an available recipient model via `--open --model MODEL` when needed.

The following do not silently degrade into an apparently faithful conversion:

- External URL/path/file-ID attachments, audio/video/SVG, animated images and
  unknown content blocks are rejected. Native same-CLI transfers still preserve
  their existing JSONL; they do not collect missing external assets.
- Opaque encrypted compaction cannot be decoded. Updated portable exports mark
  removed compaction state even if an entire checkpoint disappeared. Exact
  active-context conversion then fails, rather than resurrecting older history.
- `--history-policy visible` explicitly recovers readable history, labels it as
  recovery in the destination, and may be much larger than the source active
  context. It does not reproduce hidden summaries or recover missing parents.
- Unfinished tool calls fail by default. `--repair-interrupted` adds a marked
  historical error result with outcome UNKNOWN; it never executes the tool.
- Unknown versions/fields, conflicting graphs, orphan tool results and stale
  reference projections are rejected. No model-name or tool-name equivalence is
  invented between the two CLIs.

Conversion and diagnostic analysis currently have a 64 MiB per-transcript limit.
Large native Codex transfers retain their existing limits, but get an explicit
analysis-limit warning instead of a misleading continuity certification.

## Embedded Images And PDFs

Run `./install-media.sh` once to install pinned Pillow/PDFium dependencies in
`~/.local/share/csl/media-venv`. Set `CSL_MEDIA_PYTHON=/absolute/venv/bin/python`
for a different dedicated interpreter. Core commands do not import these packages.

User images (PNG/JPEG/static GIF/WebP), user PDFs and images/PDFs in tool results
retain original bytes and SHA-256 in canonical metadata. Claude user PDFs remain
native documents. Codex PDFs and tool PDFs become extracted text plus page PNGs;
scanned pages remain visible. Hash-bound projections detect edits/substitutions
on reconversion instead of silently claiming original retention. Assistant-output
assets are not supported by this profile.

Limits: 8 MiB per original asset, 32 MiB aggregate original media and 32 MiB
projected media, 32 documents, 20 pages per PDF, 200,000 extracted characters per
PDF; images are at most 8192 pixels per dimension and 20 million pixels. PDF pages
render at up to 1600 pixels/96 dpi. Corrupt/protected PDFs fail explicitly.
Serialized canonical output is limited to 64 MiB.

Decoding uses a disposable directory, minimal credential-free environment,
15-second wall timeout, 8 CPU seconds and 1 GiB address-space limit. On Linux,
`CSL_MEDIA_SANDBOX=auto` (default) uses bubblewrap when installed: no network,
read-only decoder/runtime mounts, no user home/project/auth mounts. Set
`CSL_MEDIA_SANDBOX=required` for untrusted inputs; absence or namespace failure
then fails closed. If bubblewrap is absent, auto warns and uses process/resource
isolation only, which is **not an OS security sandbox**. Explicit `process` is
for trusted inputs or CI. Keep decoder dependencies/security patches maintained.

## Diagnose Before Continuing

```bash
csl doctor SOURCE_UUID --json
csl doctor ~/Downloads/handoff.csl.zip --json
csl doctor SOURCE_UUID --native --json --model MODEL --context-window 200000
csl doctor SOURCE_UUID --native --expect-text "latest agreed marker" --absent-text "excluded sibling marker"
```

The report separates four evidence levels:

| Level | Meaning |
| --- | --- |
| Structure | JSONL, graphs and paired compaction metadata were checked |
| Static active context | The supported checkpoint/branch was selected; not proof that the installed CLI will select it |
| Native replay | Installed CLI reconstructed a request against a rejecting localhost server, in disposable homes |
| Live continuation | Always `not-tested` here; no provider inference/semantic recall was performed |

Native replay reports the installed CLI version, item/text counts and transport
assertion failures by index, not message bodies. It uses fake keys, isolated
`HOME`, `CODEX_HOME`, `CLAUDE_CONFIG_DIR` and an empty project, and stops before
generation. It does not read/copy your login or run historical tools. A native
compaction request can also be observed; its request path is reported, but a
successful compacted response is not fabricated.

The isolated environment intentionally excludes the recipient's real AGENTS,
plugins, MCP schemas, local settings and other prompt overhead. Thus even a
successful native reconstruction is **not** a guarantee of context fit or model
availability in the real environment. `--expect-text` checks transport, not what
a real model recalls. No compatibility claims extend to every historical CLI
version, account mode or backend provider.

Token estimates use text characters / 4 and are explicitly approximate. Images,
opaque state, tokenizer behavior and tool schemas can make them inaccurate.
`--context-window` is a user-supplied risk threshold, not a model catalog lookup
or a change to CLI configuration. No guessed token estimate blocks an import.

For an exact, explicit **text character** budget use `--max-context-chars N` on
convert/import/receive/doctor. It rejects oversized reconstructed text, including
cached receives. If static context cannot be reconstructed, the budget cannot
be enforced and the operation fails; doctor can use native measurement instead.
No hidden context is cut to satisfy a budget.

Native imports always print a continuity preflight and warnings. Invalid paired
metadata fails before installing any sessions. Missing ancestry, lost opaque
state, analysis limits and large-context risk remain visible limitations. An
opened UI alone is never reported as proof that the next model turn will work.

## Verification

### Historical tools in Codex's visible history

Conversion through canonical v2 to Codex now includes display-only tool events,
tested with Codex 0.166.0 on Linux. The CLI shows these under the deliberately
named `csl_imported_history` server: **this is a historical display adapter, not
an installed MCP server or an execution of the imported call**. CSL registers no
server, tool, permission or credential. Names, JSON/custom-text arguments, call
IDs, textual results and error flags come from the source history. Parallel calls
retain their individual correlations. Canonical/model history remains in the
native `response_item` records; display events do not become additional messages.

Codex's MCP-shaped display requires a duration field; **its displayed zero is an
unknown-duration placeholder, not a measured latency**. Each projected JSONL event
records its historical-only provenance, and end events record the duration caveat.
Omitting/nulling that field caused 0.166.0 to omit the tool items in isolated tests.
Non-text result blocks get an explicit display placeholder while their native
content remains preserved. This projection does not claim to render image/PDF
tool results faithfully. References and phases remain in canonical/native history.

Unknown canonical blocks, orphan results and unfinished calls still reject before
destination publication; CSL invents neither results nor completion. Repeated
same-CLI imports or canonical conversion do not accumulate display projections.
Secret review includes duplicated display arguments, including business fields
named `id` or `signature`; review remains partial overall.

The change applies when creating Codex history **through canonical conversion**.
It does not retrofit arbitrary existing Codex histories, modern native tool item
types or every native clone/import path. Readable UI history is not a new proof
of model continuation; the existing model benchmark is separate.

```bash
python3 -m unittest discover -s tests -q
CSL_RUN_CODEX_NATIVE_TESTS=1 CSL_RUN_CLAUDE_NATIVE_TESTS=1 python3 -m unittest discover -s tests -q
```

Synthetic tests cover all four routes, corrected decisions, tool-only facts,
source-policy quarantine, canonical restore, explicit recovery/repair, receiver
cache separation and size guards. Native tests capture requests in both CLIs
without paid endpoints. The public coverage matrix remains synchronized by tests.

Optional decoder/schema tests (synthetic only):

```bash
~/.local/share/csl/media-venv/bin/python -m pip install -r media-test-requirements.txt
CSL_RUN_MEDIA_TESTS=1 CSL_MEDIA_SANDBOX=required ~/.local/share/csl/media-venv/bin/python -m unittest discover -s tests -q
```

See [live verification](LIVE_VERIFICATION.md) for the separately authorized,
budgeted model continuations and measured results.
