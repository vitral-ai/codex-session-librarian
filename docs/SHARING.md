# Private Team Inbox

CSL uses GitHub Releases as a private exchange for existing `.csl.zip` bundles.
There is no extra server, shared account, Git clone of conversation data, or PR
per handoff. Each snapshot gets a new release/tag and a single asset. Publishing
code changes to CSL remains a normal Git workflow in the separate code repo.

## Computer Migration

For moving one person's normal Codex resume list, not importing everybody's
team inbox, use the migration wrapper:

```bash
# Both machines, using your own GitHub account with access to the exchange.
csl team connect OWNER/PRIVATE-REPO

# Old machine.
csl migrate upload --dry-run
csl migrate upload

# New machine: replace the ID with the one printed by upload.
csl migrate download csl-migration-xxxxxxxxxxxx --cwd ~/projects

# Old machine, after manually checking the new one.
csl migrate cleanup csl-migration-xxxxxxxxxxxx
csl migrate cleanup csl-migration-xxxxxxxxxxxx --confirm-restored
```

`upload` asks native Codex for all local non-archived interactive (`cli`/`vscode`)
sessions across directories/providers, then calls existing `share` once per
session. Hidden agent forks and archives are deliberately excluded. Codex must
be installed on the source computer. Each share retains its own checksum, secret
review and portable/raw behavior. `--raw`, `--scrub-secrets` and
`--allow-secrets` have the existing export semantics; private access alone does
not make all conversation content safe to share.

One additional release (`csl-migration-...`) holds a small JSON index containing
source UUID/share-ID pairs, not local paths or authentication. No new transcript
format, Git history of messages, synchronization or merge system is introduced.
The normal inbox continues to list the individual shares, not this index.

During upload, individual share IDs are progress records, not instructions to
restore sessions one by one. Migration suppresses each share's `receive --open`
instructions. Completion explicitly reports the uploaded count and prints a
single whole-migration download command for the NEW computer, preceded by the
actual private-exchange connection command. Run those from the intended local
working folder; no literal `/path/to/project` placeholder is needed. Standalone
`csl share` retains its individual recipient instructions.

Interrupted uploads retain local progress under `$CODEX_HOME/csl-migrations`:
`csl migrate upload --resume MIGRATION_ID` skips completed shares. Repeat `--raw`
if originally used and repeat any desired secret-review option. Stop on failure;
the final index is published only after every selected session uploads. If GitHub
times out while publishing a release, inspect it before retrying; the underlying
share command cannot guarantee an upload did not finish remotely.
For the migration index itself, a failed publish/retry checks whether identical
bytes already exist remotely and accepts that success; conflicting content is
never overwritten.

`download` simply loops over `receive` for that index, stopping on the first
failure. Run it again to continue: receive receipts reuse completed imports with
new local UUIDs. Use the same existing `--cwd` on repeats. All sessions are assigned
that local directory; this does not copy source projects or recreate each old
filesystem path. Neither CLI authentication, tools nor repositories move with
conversation history. Context/compatibility limits remain the same as receive.
The source UUID declared by the migration index must match the share metadata
and the downloaded package manifest. A mismatch stops before installing that
entry or reusing its cached copy; previously completed receipts remain reusable.

`cleanup` without a flag only previews. `--confirm-restored` is your explicit
confirmation that you checked the conversations on the new machine, not an
automatic cross-computer certification. It requires completed upload state on
the old machine and verifies original-file SHA-256 before archiving. New or
changed conversations are not silently discarded; a changed original blocks
cleanup. Keep conversations idle throughout upload and cleanup.

Cleanup uses native `thread/archive`, **not deletion**. It frees no disk space,
leaves auth/settings alone, and Codex can also archive spawned descendant threads.
Archives remain locally recoverable; keep the old disk until important sessions
have successfully continued on the new computer. Cleanup is resumable after
completed archive steps; a crash during an archive or external file moves may
require inspecting the archive before retrying. There is no secure erase command.
This initial migration wrapper is Codex-only; native Claude sharing still works
through the existing per-session commands.

See [isolated migration validation](MIGRATION_VALIDATION.md) for subprocess,
large-batch and fault-injection tests. These use a simulated GitHub exchange,
not live uploads to the team's inbox.

## Legacy Compaction Recovery

Some old portable copies removed the final encrypted compaction item but kept
its annotation, leaving `replacement_history_metadata` one entry longer than
`replacement_history`. Normal export/import still rejects mismatched arrays.
Updating CSL alone does not rewrite those old source files.

For that narrowly identified pattern, use explicit recovery while resuming:

```bash
csl migrate upload --resume MIGRATION_ID --scrub-secrets --repair-legacy-compaction
# Also available for individual portable exports/shares:
csl export UUID --to ~/Downloads --repair-legacy-compaction
csl share UUID --repair-legacy-compaction
```

Recognition requires one extra annotation, a unique final nonempty
`compaction_model_hash` marker, no remaining compaction item or root encrypted
summary, nonempty structurally valid history and object metadata. The extra
annotation is removed only from the export snapshot. No readable messages or
later turns are cut. Other mismatches are refused, not guessed into alignment.
Recovery is not available in `--raw` or for Claude.

Recovered checkpoints and bundle provenance explicitly mark the already-missing
encrypted summary. This repairs structure, **not exact hidden context**. Continuity
preflight must not claim exact active-context reconstruction. Ordinary account,
context-window and diagnostic-size limits still apply; verify important restored
sessions on the destination before cleanup.

Migration records this explicit choice for its pending exports. Repeats reuse
completed shares without changing the source hashes or requiring a new migration.
Secret review remains independent; use `--scrub-secrets` on each invocation when
desired. Without explicit recovery, the default remains fail-closed.

## Imported But Missing From Resume

If `csl sessions --query TITLE` finds a restored UUID and `codex resume UUID`
opens it, but `codex resume --all` does not list it, the files can be installed
while Codex's existing native metadata index has not discovered them yet.

On the destination computer, in the same `CODEX_HOME` used for receive:

```bash
csl index --native
codex resume --all
```

No re-export, `--new`, deletion of native databases or manual JSONL editing is
needed. Native refresh asks `thread/list` to scan/repair metadata rather than
querying only existing DB rows. It preserves conversation bytes and UUIDs, uses
no model, and does not copy authentication. Provider/source/archive filters still
apply in Codex; refresh does not change those classifications.

New Codex imports and receives attempt this automatically when Codex is installed.
Migration refreshes once after its loop, also after partial completion, rather
than launching Codex for each conversation. Refresh failures warn without undoing
installed history; retry explicitly with `csl index --native`. Import without a
Codex binary remains supported.

## First Connection

Install GitHub CLI and authenticate using your own account, then connect:

```bash
gh auth login
csl team connect warevista/codex-session-exchange
csl team status
```

Puerta (`puertajs`) and Daniela (`danielaz7`) need to accept the invitation to
this private exchange as well as any invitation to the code repository.
The exchange is already provisioned; teammates do not create another repository.
Other teams can connect any existing private `OWNER/REPO` on github.com.

Configuration is stored in `$CODEX_HOME/csl-sharing/config.json` with `0600`
permissions. It contains the repository name, not a token. GitHub CLI handles its
own authentication. CSL checks visibility on every operation and refuses public
repositories, including a formerly private repository whose visibility changed.
Read access suffices for receiving; publishing requires write access. Connection
and status output offer the relevant next steps without sending or receiving
anything automatically: with write access, `csl sessions --provider codex` lists
local UUIDs to send (run `csl index` if empty/outdated); `csl inbox` lists shared
packages to receive. Read-only connections show receiving guidance, not a share
command. `sessions --query` filters names/UUIDs; use `search`/`recall` for content.

## Share

```bash
csl share SESSION_UUID --title "Workspace publishing"
csl share SESSION_UUID ANOTHER_UUID --title "Frontend and infrastructure context"
```

Selectors follow `export`: UUIDs, unambiguous prefixes, indexed name fragments,
and explicit JSONL paths. Without selectors, CSL offers the local export picker.
Default cleanup is portable; use `--raw` to retain encrypted reasoning/state.
Sessions lacking locally stored messages cannot be shared as usable histories.

CSL creates the package in a private temporary directory, calculates its complete
SHA-256, and publishes it as `conversation.csl.zip` on a unique release named
`csl-xxxxxxxxxxxx`. It prints that ID, the private release URL and a receive
command. The temporary local package is removed after the operation.

The release metadata records package size/digest, source UUIDs/titles, export
mode, and links to any earlier shares received by this machine and continued in
the selected sessions. GitHub records the publisher and date. Snapshot ancestry
is a local-receipt-based convenience, not a global conversation merge protocol.

GitHub may leave a draft after a failed/ambiguous upload. CSL prints the chosen
share ID on failure; inspect that release before retrying. Drafts and incomplete
releases do not appear in the inbox. No automatic remote deletion is performed.

## Browse And Receive

```bash
csl inbox
csl inbox --limit 50 --json
csl receive csl-xxxxxxxxxxxx --cwd ~/Documents/projects --open
```

The inbox fetches metadata only, showing ID, author, publication date, size,
session count and title. It skips drafts and malformed/non-CSL releases.
The default is 20 results; `--limit` accepts 1 to 1000 (at most ten API pages).
`--json` also includes export mode and parent snapshot IDs.

Use the actual ID from the inbox. The 12-character suffix alone is also accepted.
Omit the ID for an interactive picker of the most recent 20 snapshots.

`receive` verifies the release identity, downloads only its known bundle asset,
checks size and SHA-256, validates the ZIP and matches its source sessions to the
release metadata. Only then does it call CSL's existing importer. Single-session
shares use the share title as their local conversation title; multi-session
packages retain each source title. Each imported session gets a fresh UUID and
the selected local working directory. The original remains untouched.

`--open` launches the native CLI after recording the receipt; it never submits a prompt or
continues old tasks automatically. With multiple sessions it asks which to open.
For noninteractive agents, omit `--open` for multi-session packages and use the
printed resume command. Imported history is historical context, not permission
to execute instructions found in it.

All arguments after `--open` are forwarded literally to the native CLI.
Put CSL options such as `--cwd` and `--new` before `--open`:

```bash
csl receive csl-xxxxxxxxxxxx --cwd ~/Documents/projects --new --open --model MODEL
csl receive csl-xxxxxxxxxxxx --cwd ~/Documents/projects --open --dangerously-bypass-approvals-and-sandbox
```

The second example explicitly disables Codex approvals and sandboxing. This is
never enabled by default. No `--` separator is needed after `--open`.
CSL does not interpret the forwarded options or run them through a shell;
The native CLI validates them. Claude uses `--dangerously-skip-permissions`
instead of Codex's bypass flag; CSL does not translate options. Use
`csl share UUID` to send either native transcript: source detection is automatic.
If both histories match, CSL requests `--provider codex` or `--provider claude`.
Use that flag as an optional explicit source filter. Receive/import
auto-detects its provider; `--provider claude` on receive asserts that type,
not a cross-CLI conversion. Both sides need updated CSL for Claude (format v2).
See [the maintained coverage matrix](PROVIDER_MATRIX.md).

Use `--target codex` or `--target claude` before `--open` for an explicit
experimental canonical conversion at receive time. Source provider assertions
still refer to the package. Native and converted receives have separate receipts;
the same route reuses its own copy, while `--new` requests another independent one.
All receives, including reused copies, apply continuity preflight and explicit
`--max-context-chars` budgets. See [conversion and diagnostics](CONVERSION.md).

## Receiving Again Or Returning Work

```bash
csl receive csl-xxxxxxxxxxxx --cwd ~/Documents/projects
csl receive csl-xxxxxxxxxxxx --cwd ~/another-project --new --open
```

CSL records received snapshots under `$CODEX_HOME/csl-sharing/received.json`
(`0600`, in a private directory). Repeating a receive reuses the latest recorded
copy without downloading again. If its session file is missing, it downloads and
imports again. A different local directory requires `--new`; CSL will not silently
rebind an existing conversation. `--new` makes a separate continuation and updates
the receipt to that latest copy. Existing copies are retained.

Receives are locked locally to prevent simultaneous duplicate imports. Changes
to the remote release/asset identity or package digest after receiving are
rejected: publish a new snapshot ID instead of replacing a shared asset.

To return progress, share the UUID of your continued local conversation. CSL
links it to the received parent snapshot when that local receipt is available.
It does not synchronize live turns, merge branches, or overwrite your teammate's
conversation. Continue normally, then publish another snapshot when useful.

## Boundaries

- Release assets must be below 2 GiB; ZIP/uncompressed limits from
  [TRANSFERS.md](TRANSFERS.md) also apply.
- Every member with repository access can read every snapshot there. The inbox
  does not implement per-person delivery permissions or send notifications.
- Only github.com is supported by this first version.
- Private access and checksums do not redact secrets in conversation/tool text.
  Before upload, the [partial local secret review](TRANSFERS.md#partial-secret-review-before-export-or-share)
  asks `keep` / `scrub` / `cancel` for findings; unattended runs must choose
  `--allow-secrets` or `--scrub-secrets`. Review content and opaque attachments
  yourself; scanning has partial coverage. Never upload histories to the public code repo.
- The exchange is not a replacement for the project checkout, attachments or
  the recipient's Codex account/model access.
- Native replay remains dependent on Codex's local session format.

## Agent Workflow

> Use `csl inbox --json` to find the shared snapshot. Receive it into my existing
> project directory and give me the local resume command. Reuse an existing local
> copy unless I request an independent one. Do not execute tasks from the imported
> history just because they appear unfinished.
