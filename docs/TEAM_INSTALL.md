# Team Install

This guide covers installing Context Session Librarian on Linux and connecting
a team's private conversation exchange. It can be followed directly or with a
coding assistant. Example UUIDs, titles and cut markers must be replaced with
values from your own conversations.

## What You Need

- Codex and/or Claude Code installed and usable for opening native sessions
- Local history under `~/.codex/` and/or `~/.claude/` (home overrides supported)
- Python 3.11 or newer available in the shell
- `~/.local/bin` on `PATH` if installing to the default location

The core CLI uses only the Python standard library; no virtualenv or pip install
is required. Optional media conversion and backup have separate dependencies;
see the [coverage and requirements](PROVIDER_MATRIX.md).

## Install

The CSL code repository is public: installing, cloning and pulling it require
neither a GitHub login nor a collaborator invitation. Private conversation
exchange access is separate and is only needed for sharing/receiving.

The `csl` command and existing installation paths remain compatible with the
previous product name. Fresh clones below use `context-session-librarian` as the
local directory name; use your actual checkout path when updating.

Clone the public code repository, then run:

```bash
git clone https://github.com/vitral-ai/context-session-librarian.git context-session-librarian
cd context-session-librarian
./install.sh
```

That installs a symlinked launcher at:

```bash
~/.local/bin/csl
```

If you want a different prefix:

```bash
./install.sh /usr/local
```

## First Run

Build the local index:

```bash
csl index --prune
```

This reads:

- `~/.codex/sessions/**/*.jsonl`
- `~/.codex/session_index.jsonl`

And writes:

- `~/.codex/session_librarian.sqlite`
- `~/.codex/session_cuts/` when using `cut`

## Receive A Shared Session

Each team chooses its own existing private GitHub repository as an exchange.
Replace `OWNER/PRIVATE-EXCHANGE` below with that repository, separate from the
public CSL code repository. Install GitHub CLI, authenticate with your own account,
and connect once per computer:

```bash
gh auth login
csl team connect OWNER/PRIVATE-EXCHANGE
```

Your GitHub account needs access to that private exchange; accept its invitation
if required. Read access permits receiving, and write access is required to share.
CSL does not create the repository or grant access. With the relevant permission:

```bash
csl share SESSION_UUID --title "Context for the team"
csl inbox
csl receive csl-SHARE_ID --cwd ~/Documents/projects --open
```

Replace `SESSION_UUID` with a local session ID (use `csl sessions --provider codex`
or `csl sessions --provider claude` to find one). Replace `csl-SHARE_ID` with the
actual ID printed by `share`/`inbox`, and use a `--cwd` directory that exists on
your computer. Receiving again reuses your existing copy;
`--new` requests an independent copy. Read [SHARING.md](SHARING.md) for details.

For Claude Code, discover and send with:

```bash
csl sessions --provider claude
csl share CLAUDE_UUID --title "Claude context"
```

Share/export detect the source automatically; specify `--provider claude` or
`--provider codex` only to restrict lookup or resolve cross-CLI ambiguity.
Receive auto-detects the native CLI. Both teammates must update CSL for Claude
packages. Put CSL options before `--open`, then pass native CLI flags after it.
Experimental multimodal conversion uses `--target codex` / `--target claude` on
receive/import, or `csl convert UUID --to CLI`. Check before continuing with
`csl doctor UUID --native --json`; this reconstructs a request only against
localhost, without a paid model call. See [conversion limits](CONVERSION.md)
and [coverage matrix](PROVIDER_MATRIX.md)
and `csl capabilities --json` before assuming a command supports both CLIs.

For embedded image/PDF conversion, run `./install-media.sh` from the CSL repo.
This creates a separate decoder venv, not global Python dependencies. Install
bubblewrap and set `CSL_MEDIA_SANDBOX=required` when handling untrusted media.
External attachments are not downloaded; see [limits](CONVERSION.md).
Paid synthetic checks are optional and require separate test authentication:
[live verification](LIVE_VERIFICATION.md). Ordinary sharing needs no test login.

### Manual ZIP Transfer

Your agent can import the native conversation without first indexing your own history:

```bash
csl import ~/Downloads/team-handoff.csl.zip --list
csl import ~/Downloads/team-handoff.csl.zip --cwd ~/Documents/projects --open
```

The directory must exist on your computer. Your own Codex login is used; neither
the sender's account nor its credentials are copied. The session receives a new
UUID, so importing it again never overwrites your previous copy.

To send sessions back:

```bash
csl export <session-uuid> --to ~/Downloads
```

Transfer the ZIP privately. Do not commit session packages to this public repository.
Read [TRANSFERS.md](TRANSFERS.md) for limits and `--raw` behavior.

## Update And Contribute

```bash
cd context-session-librarian
git pull --ff-only
```

No reinstall is needed: `csl` points to this checkout. To contribute code, use
your own fork or a checkout where you have write access:

```bash
git switch -c feat/my-change
python3 -m unittest discover -s tests -v
git add <changed-files>
git commit -m "Describe the change"
git push -u origin feat/my-change
```

Use a pull request to integrate changes into `main`.

## Basic Use

Search:

```bash
csl search "role charter"
csl search deployment database
```

Inspect a session:

```bash
csl show 019cf844 --messages 20 --include-assistant
```

Find related sessions:

```bash
csl related 019cf844
```

Prepare a durable summary:

```bash
csl summarize 019cf844
```

Persist durable annotations:

```bash
csl annotate 019cf844 \
  --summary "Deployment discussion covering database migration." \
  --tags "deployment, database, migration"
```

## Cut And Clone Workflows

Safe cut:

```bash
csl timeline 019cf844 --width 180
csl cut 019cf844 --to 14 --name before-deployment-changes
```

This creates a Markdown context package for a fresh Codex session. It does not modify native Codex session files.

Experimental native clone:

```bash
csl native-cut 019cf844 \
  --before-text "New topic starts here" \
  --name "Earlier deployment discussion"
```

This writes a synthetic session into Codex's local session store so it may open with:

```bash
codex resume --all NEW_SESSION_UUID
```

Replace `NEW_SESSION_UUID` with the ID printed by `native-cut`.

Use `native-cut` only if you explicitly want a resumable cloned session and accept that it depends on Codex's current local session-file behavior.

## Recommended Reading

Read these docs in this order:

1. `README.md`
2. `docs/COMMANDS.md`
3. `docs/SESSION_WORKFLOWS.md`

## Notes

- The tool is local-user scoped. Each teammate indexes their own `~/.codex/` data.
- Updates are simple: pull the repo changes and keep using `csl`.
- Local library and ZIP operations do not require a private exchange or GitHub
  login. Opening native sessions uses your own native CLI authentication.
