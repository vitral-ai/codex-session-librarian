# Context Session Librarian

**A Vitral project · Apache-2.0 · [csl.vitral.ai](https://csl.vitral.ai)**

Find, reopen, clone, and share native Codex conversations from your terminal or
coding agent. CSL also transfers native Claude Code conversations and offers
experimental conversion between the two CLIs. It works with conversation history,
including supported tool records, rather than just a summary. See the
[command and compatibility matrix](docs/PROVIDER_MATRIX.md) for exact coverage.

## Install

Requires Linux and Python 3.11+. The core CLI uses only the Python standard
library; no virtualenv or pip installation is needed. Confirm tag availability in
the [v0.2.2 Release](https://github.com/vitral-ai/context-session-librarian/releases/tag/v0.2.2)
before using the tagged installation below.

```bash
git clone --branch v0.2.2 https://github.com/vitral-ai/context-session-librarian.git context-session-librarian
cd context-session-librarian
./install.sh
csl --version
```

Make sure `~/.local/bin` is on `PATH`. The installer prints
the installed launcher's version and warns if your shell resolves `csl` to a
different installation. Keep the checkout: the installed launcher
points to it. You can choose another installation prefix with `./install.sh PREFIX`.
Context Session Librarian was previously named Codex Session Librarian; the
`csl` command and existing installation paths remain compatible.

Opening a conversation requires its native CLI and your own authentication.
Local search and ZIP transfers need no GitHub account or paid model calls.
Team exchange additionally requires [GitHub CLI](https://cli.github.com/).
For development, clone without `--branch v0.2.2` in a separate directory;
see [release history](CHANGELOG.md) for published changes.

## Find And Reopen A Conversation

Build a local Codex index, then search for a discussion and reopen its UUID:

```bash
csl index
csl recent --limit 20
csl recall "database migration"
csl search database migration
csl show SESSION_UUID --messages 20 --include-assistant
csl show SESSION_UUID --tail 10 --include-assistant --reverse
codex resume --all SESSION_UUID
```

Search uses local SQLite and lexical ranking, not embeddings. It indexes readable
messages and supported tool text; opaque/media content is not searchable text.
The private index may contain sensitive conversation and tool output. Default
indexing covers active sessions; `index --sessions-dir` can include archives.
Use `csl cockpit` for an interactive browser.

`show` reads the full JSONL history:
`--tail N` selects the last N messages after role filtering, then `--reverse`
reverses that selection. Omit `--include-assistant` for user messages only.

Inspect a copy or fork with `csl why SESSION_UUID WORDS` to
include inherited evidence, marked `[inherited]`; `--exclude-inherited`
shows only evidence created in that session. Global searches exclude inherited
evidence by default to reduce duplicate copies. For tool output, use words from
the result and `--type tool_result` to select the evidence category.

If an imported conversation opens by UUID but is missing from Codex's resume
picker, run `csl index --native`. Imports request this native refresh automatically
when Codex is installed. See the [command reference](docs/COMMANDS.md).

## Transfer A ZIP Without GitHub

```bash
csl export SESSION_UUID --to ~/Downloads/handoff.csl.zip
csl import ~/Downloads/handoff.csl.zip --list
csl import ~/Downloads/handoff.csl.zip --cwd ~/work/project --open
```

Use an existing local project directory. Selectors can be UUIDs, unambiguous
prefixes, indexed names or JSONL paths; multiple selectors can share one ZIP.
`--list` validates and inspects without importing. Imports create new UUIDs and
leave originals unchanged. Omit `--open` to import without launching the native CLI.

Export/share performs a **partial secret scan** of readable text. Findings need
a per-value terminal decision, or explicit `--allow-secrets` / `--scrub-secrets`
for unattended use. Interactive `scrub-all` scrubs every detected
value in the current review; replacing earlier `keep` decisions requires
confirmation. Binary and opaque attachments are not scanned. Review the
contents before sharing; see [secret review and limits](docs/TRANSFERS.md#partial-secret-review-before-export-or-share).

Default portable export removes encrypted reasoning/state while preserving
conversation and tool history. This is **not secret redaction**. `--raw` keeps
opaque encrypted content, which may not work with another account. A transfer ZIP
is separate from the encrypted backup feature below. See [portable transfers](docs/TRANSFERS.md).

## Share Through A Private GitHub Exchange

Each person connects with their own GitHub account to an existing private
exchange repository, separate from this public code repository:

```bash
gh auth login
csl team connect OWNER/PRIVATE-EXCHANGE
csl share SESSION_UUID --title "Database migration handoff"
```

On the receiving computer:

```bash
csl inbox
csl receive csl-SHARE_ID --cwd ~/work/project --open
```

Use the actual `csl-xxxxxxxxxxxx` ID printed by `share` or `inbox`. Packages are
GitHub Release assets; you do not need to clone the exchange or commit ZIPs.
Receiving the same snapshot reuses your local copy; add `--new` for another
independent copy. `csl inbox --json` fetches metadata without downloading transcripts.

Put CSL options before `--open`: everything after it goes literally to the native
CLI. CSL does not add approval or sandbox bypass flags. See
[team sharing](docs/SHARING.md) and [team installation](docs/TEAM_INSTALL.md).

## Claude Code And Conversion

Discover and transfer Claude Code conversations with:

```bash
csl sessions --provider claude --query "backend"
csl export CLAUDE_UUID --to ~/Downloads
csl share CLAUDE_UUID --title "Backend handoff"
```

Export/share searches both local histories and detects the CLI. If both match,
select `--provider codex` or `--provider claude`. Receive/import detects the CLI
from the package: `--provider` asserts its source, it does not convert it.
Search, recall and cut commands remain Codex-only. Both sides need a CSL version
with Claude transfer support; inspect `csl capabilities` for coverage.

Conversion is explicit and **experimental**:

```bash
csl convert SESSION_UUID --to claude --cwd ~/work/project
csl receive csl-SHARE_ID --target codex --cwd ~/work/project
```

The supported profile includes text, completed tools, references, embedded images
and PDFs. Unsupported assets and opaque context are rejected rather than silently
discarded. Image/PDF conversion needs the optional isolated decoder installed with
`./install-media.sh`; untrusted media should require Linux bubblewrap via
`CSL_MEDIA_SANDBOX=required`. External paths, URLs and file IDs are not collected.
See [conversion, decoder dependencies and continuity limits](docs/CONVERSION.md).

Successful import or `csl doctor SESSION_UUID --native --json` does not prove live
model recall or that the history fits every model's context. Doctor checks request
reconstruction in isolated homes against localhost without generation.
[Live verification](docs/LIVE_VERIFICATION.md) is a separate, explicitly paid,
synthetic-only operation.

## Experimental Encrypted Backup

Manual encrypted backup is **Linux/Codex only**. It supports incremental
checkpoints and recovery, separately from ZIP export, team sharing and migration.
Installing CSL does not activate backups or collect personal histories.

Backup requires an externally installed, verified **age v1.3.2**, GitHub CLI,
an existing private repository, and two distinct public recipients: operational
and external recovery. Keep the recovery private key outside the protected
computer. **Losing both private identities makes recovery impossible**; repository
access alone cannot decrypt a backup. Private identities are supplied through
manual stdin/memory/FD or a system-keyring reference. Positive system-keyring and
headless operation have not been validated in this release.

The default secret policy stops on detected findings. Retaining them requires
explicit risk acceptance; scrubbing requires a portable profile and changes only
output copies. The scanner cannot guarantee that all secrets are detected.
Before updating CSL, finish pending backup runs and recipient-change plans with
their original version. The first backup after a version update captures local
conversations again; older checkpoints still require their original recovery keys.
Changing recipients affects future backups and does not revoke access to earlier
ones. There are no backup timers, automatic retention/garbage collection or
historical re-encryption. Follow the [backup setup and recovery manual](docs/BACKUP.md)
before using this experimental feature.

## Move Or Fork Conversations

For a computer migration, connect both computers to the same private exchange,
stop writing to old conversations, then use `csl migrate upload --dry-run` before
uploading. Download using the printed migration ID and an existing local project
directory. Check restored conversations before cleanup: cleanup **archives, never
deletes**, unchanged originals and does not free disk space. Migration excludes
archives and non-interactive agent sessions. See [migration instructions](docs/SHARING.md#computer-migration).

For an independent local continuation or a shorter history:

```bash
csl native-clone SESSION_UUID --name "Independent continuation"
csl timeline SESSION_UUID
csl native-cut SESSION_UUID --before-text "Later topic starts here" --name "Earlier discussion"
```

These create new native sessions. `native-sanitize` removes encrypted reasoning
from a new local copy. Agent and archived visibility options organize the native
picker; they are not access control. See [clone and visibility details](docs/COMMANDS.md#native-clone).

## What Transfers Preserve

Packages contain conversation/tool records, provenance and supported embedded
assets. They do not collect project repositories, installed tools, authentication
files or external attachments. A fork may reference missing parent history;
CSL reports this and cannot reconstruct absent records. Metadata without messages
cannot restore a conversation.

Each continuation is independent: transfer is a snapshot, not live synchronization
or automatic merging. Historical paths still refer to the sender's computer.
Checksums detect corruption, not sender authenticity. Imported history is context,
not permission to execute old instructions; native replay depends on the current
CLI format and available model/provider.

## Try An Isolated Demo

From the checkout, without a model login or personal histories:

```bash
python3 demo/demo.py --repo . --out /tmp/csl-demo.json
```

It creates synthetic fixtures, exports and inspects a ZIP, imports a new native
session and checks experimental Claude-to-Codex conversion. See [the demo](demo/README.md).

## Development And Documentation

CSL reads `$CODEX_HOME` (default `~/.codex`) and keeps its search index at
`session_librarian.sqlite`. Claude transcripts use `$CLAUDE_CONFIG_DIR/projects`
(default `~/.claude/projects`). Shared exchange settings and receipts live under
`$CODEX_HOME/csl-sharing` for both CLIs. Credential files are not copied.

Run the standard-library test suite with isolated synthetic fixtures:

```bash
python3 -m unittest discover -s tests -v
```

Optional `CSL_RUN_CODEX_NATIVE_TESTS=1` and `CSL_RUN_CLAUDE_NATIVE_TESTS=1` enable
isolated native checks without model generation or real credentials. See
[compatibility maintenance](docs/COMPATIBILITY_MAINTENANCE.md) for details.

- [Command reference](docs/COMMANDS.md)
- [CLI/provider coverage](docs/PROVIDER_MATRIX.md)
- [Session workflows](docs/SESSION_WORKFLOWS.md)
- [Portable ZIP transfers](docs/TRANSFERS.md)
- [Private GitHub sharing](docs/SHARING.md)
- [Conversion and continuity](docs/CONVERSION.md)
- [Experimental encrypted backup](docs/BACKUP.md)
- [Release history](CHANGELOG.md) and [release records](RELEASE.md)
