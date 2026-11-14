# CSL Bridge for macOS — source prototype

This directory contains a native AppKit interface for the experimental Codex
bridge. **No validated app bundle is available yet.** Compilation, clean-device
installation and GUI interaction remain unverified. Real Linux–Mac LAN tests used
the [CLI connector](../docs/BRIDGE.md), not this app.

The interface has connection and activity views. It selects an already-loaded
Codex conversation, preserves its account and runtime, and starts only its own
connector. An explicitly selected existing bridge can be adopted without replacing
it; closing the app stops its own connector, not one it adopted. No conversation,
native server, account or model turn is created for discovery.

## Prerequisites and boundaries

The prototype is designed to bundle a private Python 3.12 runtime and the CSL
library, without relying on Apple Python, Homebrew, uv or the user's PATH at run
time. That independence must still be verified in a native build. Development
requires macOS command-line build tools and an existing standalone Python 3.12
distribution. Architecture and minimum macOS support are established by actual
build/test evidence, not the source code's deployment target.

Peer networking must already be configured and authorized. The app does not enable
SSH, open ports, create a relay or implement automatic pairing. There is no global
autostart. Runtime availability, connector state and remote application response
are shown separately: a live PID or SSH banner alone does not establish readiness.
Internet coordination has not been validated.

## Build from a fixed source commit

On a Mac with the prerequisites, choose a new output directory:

```sh
python3.12 macos/build_app.py --source /path/to/checkout --source-sha FULL_COMMIT_SHA \
  --runtime-root /path/to/python-standalone-3.12 --output /path/to/new-output
```

The builder is designed to produce an app, ZIP, manifest and SHA256 checksums with
local ad-hoc signing. It does not provide Developer ID signing or notarization.
Do not disable Gatekeeper as a distribution procedure. Its empty-HOME/PATH selftest,
linkage checks and signature validation must pass on the actual Mac. Offscreen
AppKit rendering does not replace interaction testing in a real desktop session.

Source packaging uses `git archive` of explicitly allowed tracked files at the
exact commit, excluding private state, skills, credentials, tests and evidence.
An export without Git requires a separately pinned `SOURCE-MANIFEST.json` hash
via `--source-manifest-sha256`; a commit label alone cannot verify exported bytes.

## Intended use after a validated build

Open the app and select an existing conversation. The executable also offers:

```sh
'/path/CSL Bridge.app/Contents/MacOS/CSLBridge' connect
```

It uses the saved conversation, current `CODEX_THREAD_ID`, or the only loaded
conversation; ambiguity requires selection. `status`, `stop`, `events` and
`connection-info` inspect or control the selected setup. `--bridge-home` explicitly
selects an existing bridge home; no private laboratory configuration is autodetected.

`connect --approve-communication` explicitly installs only the selected communication
and query MCP tools, with a corresponding UI button. It does not change the model,
global approvals, shell permissions or credentials. `mcp-rollback` restores only
the app's own recorded MCP section, refusing to overwrite a later unrelated change.

For an already-authorized SSH profile, `transport-run --transport-profile
/path/to/private-profile.json` supervises a foreground SSH child with keepalives and
bounded reconnect backoff; `transport-status` reports its state. The private profile
names `ssh_alias` and an owned `0600` `ssh_config` file containing the approved host
pin, forwards and public identity/agent selection. Do not embed private keys or
tokens. This supervisor has not yet been validated on the target Mac; it does not
resend tasks, install a global service or prevent physical suspension. An
authenticated remote application response is still required to establish readiness.
