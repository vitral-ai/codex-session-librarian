# Experimental Agent Coordination

This private candidate adds optional `csl bridge` commands for coordinating
existing Codex agents. A followup starts an idle agent in its own conversation;
a message enters active work at a runtime boundary. Progress and completed turns
return automatically. `wait` blocks on events rather than asking a model to poll.
Interrupt targets an exact delegated turn; a later followup continues the same
conversation. A completed turn is not proof that its technical conclusion is valid.

This is an experimental integration, not a supported cross-account Codex feature.
Native Codex **0.167.1** has been exercised with synthetic loopback Responses
backends, protocol clients and the actual terminal UI. Two installed Linux
containers also passed real restricted SSH, simulated network interruption,
recovery and latency controls. Native model tools reached the connector through
the optional MCP adapter in both containers. Real inference, native macOS/Windows,
SSH to another physical computer, and same/different-account operation have
**not** been validated.
Synthetic answers in the laboratory are fabricated controls of the real runtime,
not evidence of model behavior or real colleague collaboration.

## Initial Setup

Use Python 3.11+ on a system with Unix domain sockets and `fcntl`. Keep an explicit,
private bridge home separate from Codex homes, histories and authentication. The
core installer does not start or configure a bridge, service, daemon or timer.

Each participating conversation must already be loaded in its owner's chosen
app-server, accessible through a private **WebSocket-over-Unix** endpoint. The
bridge checks `thread/loaded/list` and rejoins that runtime. It never creates a
thread, imports history, starts another runtime or adopts login credentials.
Keep the owner's local UI available for approvals; the bridge never answers them.

An app-server `--listen unix://PATH` endpoint was tested. Native **0.167.2** was
also tested in an isolated Linux lab with no model calls: its default existing
control endpoint is `$CODEX_HOME/app-server-control/app-server-control.sock`,
which can be a symlink to a shorter private path. That control endpoint accepts
WebSocket framing. Resolve the explicit endpoint before connecting, especially
on Darwin where the original rendezvous path may exceed the Unix path limit.
The pinned 3122 candidate driver also passed when given the resolved path.

The official `app-server proxy --sock PATH` relays **raw bytes** through its
stdin/stdout; it does not translate JSON lines into WebSocket frames. The optional
Python `Runtime(path, proxy_executable=owner_selected_codex)` transport preserves
the HTTP upgrade and masked WebSocket frames over those pipes. A synthetic
0.167.2 check confirmed the same already-loaded thread through both transports;
closing the proxy left the server alive. This launches only a transport child,
never a native server or replacement agent. Plain JSON sent directly to proxy
stdin is an invalid test of this WebSocket endpoint. See the official
[0.167.2 proxy dispatch](https://github.com/openai/codex/blob/rust-v0.167.2/codex-rs/cli/src/main.rs)
and [byte-relay implementation](https://github.com/openai/codex/blob/rust-v0.167.2/codex-rs/stdio-to-uds/src/lib.rs).

These checks do not establish access to an arbitrary daemon, account or Mac.
First confirm the owner-selected socket and that the actual conversation is
already in `thread/loaded/list`; do not load a thread just to make this check pass.
A standalone TUI using `--no-daemon` is not
automatically attachable. Its owner would have to stop it at a safe boundary and
host the **same** conversation in a compatible runtime, then verify continuity.
Never start another server against a conversation that another process owns.

Choose names and actual existing thread UUIDs locally. For example, with
`ALICE_BRIDGE_HOME`, `ALICE_RUNTIME_SOCKET` and `COORDINATOR_THREAD_UUID` set to
your own explicit locations and selected conversation:

```sh
csl bridge --home "$ALICE_BRIDGE_HOME" init --id alice --runtime-socket "$ALICE_RUNTIME_SOCKET"
csl bridge --home "$ALICE_BRIDGE_HOME" agent coordinator --thread "$COORDINATOR_THREAD_UUID"
```

Bob independently initializes his own bridge as `bob` and registers `worker`
with his existing conversation. He keeps his own Codex tools, configuration,
permissions, account and consumption. Knowing a UUID, using the same login, or
being on the same LAN does not grant access to the other computer.

Configure each peer offline, explicitly naming which **local** agents and
operations that peer may access. The following gives Bob access only to Alice's
coordinator. Bob configures the reciprocal entry allowing Alice's operations on
his worker. `watch` carries progress/final events; it cannot read native histories.

```sh
csl bridge --home "$ALICE_BRIDGE_HOME" peer bob --ssh-alias bob-bridge \
  --allow-agent coordinator --allow-op followup --allow-op send_message \
  --allow-op status --allow-op interrupt --allow-op receipt --allow-op watch --allow-op agents
```

The SSH adapter uses a fixed `csl-bridge-receiver` command and JSON on stdin.
Owners must separately install that optional executable on the trusted host's
PATH and provide preauthorized SSH access. Use a dedicated restricted/forced
command whose trusted environment supplies `CSL_BRIDGE_HOME` and
`CSL_BRIDGE_PEER`. The peer identity comes from this local configuration, not
from a sender field in the message. The forced command must accept only the fixed
receiver command, disallow shell/forwarding/PTY access, and use normal verified
host keys. No program here edits `authorized_keys`, SSH settings or permissions.

Do not use an unrestricted SSH key as a substitute for this boundary: a remote
user who can choose the receiver's environment or execute arbitrary commands
already has broader OS authority. Each direction's trusted setup belongs to
that machine's owner. Restricted SSH has been tested in isolated Linux
containers; real colleague devices and Codex-account integration remain untested.

For a synthetic same-UID laboratory only, `peer --lab-home DIR` selects another
explicit bridge home instead of SSH. This does not authenticate a real person,
account or remote device.

Start the connector explicitly in a terminal for the session on each side:

```sh
csl bridge --home "$ALICE_BRIDGE_HOME" run
```

It remains in the foreground. Ctrl-C stops the connector and its private IPC
endpoint, not the native agent's work. It installs no global listener or autostart.
Configuration changes require stopping this connector. If the selected runtime
or conversations are not already available, state remains disconnected; it
does not start a substitute. Local IPC is private to the OS user; programs with
that user's full privileges are inside the local trust boundary.

## Coordinator And Worker

For tools used **by a model**, prefer the optional stdio MCP adapter. Sandboxed
shell commands can be denied access to the connector's Unix socket even when
the file is inside the writable workspace. Do not broadly enable command
network access to work around that boundary. Terminal/operator CLI calls remain
available separately.

Configure the adapter explicitly for the existing local agent, after registering
that conversation and starting its connector. This initial setup grants only the
bridge's existing operations, not shell, filesystem, runtime or login APIs:

```toml
[mcp_servers.csl_bridge]
command = "/absolute/path/to/context-session-librarian/csl-bridge-mcp"
args = ["--home", "/absolute/private/bridge-home", "--agent", "coordinator"]
required = true
tool_timeout_sec = 25
```

Use the worker's own fixed agent name on its side. Reload the local MCP
configuration through the supported Codex interface before sending work. The
adapter never changes configuration itself or starts a substitute conversation.
Its tools are `followup_task`, `send_message`, `send_progress`, `wait_agent`,
`list_agents`, `agent_status`, `interrupt_agent`, and `operation_receipt`.
Source identity and home are fixed by the local configuration; model arguments
cannot replace them. Messages remain remote data subject to the receiver's
mandate. Selected text with possible secrets is rejected; there is no persistent
allow-secrets setting. Waits and other tool calls can run concurrently.

The native runtime can request local approval before a side-effecting MCP call,
including `send_progress`. A laboratory with no approval UI can therefore pause
even when the selected operation is permitted by bridge configuration. The
bridge never accepts that approval or treats a peer message as local consent.
The runtime owner must inspect and decide the native request locally. A
one-call approval does not establish unattended operation or persistent trust.

For an explicit initial local grant limited to communication tools, print a
profile for review without applying it:

```sh
csl bridge --home "$BOB_BRIDGE_HOME" mcp-config --agent worker --approve-tool send_progress
```

The output binds the existing local agent/home, exposes the selected message
tools plus read-only queries, keeps the server default at `writes`, and sets
only the selected tool's `approval_mode` to `approve`. No configuration is
written or reloaded. The owner must review and apply the profile locally;
this is an explicit initial grant to that bounded tool, not consent derived
from a peer message. `send_message` can be selected separately. Task activation
and interruption are excluded from this communication profile. Peer allowlists,
active-task binding, fixed source identity and secret checks still apply.

Native 0.167.1 with a synthetic backend verified that `auto` still prompted
for `send_progress`, while a per-tool `approve` allowed that tool and left
an unselected side-effecting tool requiring approval. This does not change
shell policies or require false read-only annotations. See the official
[per-tool MCP configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

### Current Caller Without A Runtime Endpoint

If the caller's existing UI exposes shell tools but no compatible runtime
endpoint, an explicit client can send work and return progress/finals through
its `wait` tool results. Register the caller's actual conversation UUID for
local provenance; it does not provide runtime access or authentication:

```sh
csl bridge --home "$ORIGIN_HOME" init --id origin --client-only
csl bridge --home "$ORIGIN_HOME" agent coordinator --thread "$ACTUAL_CALLER_THREAD_UUID"
csl bridge --home "$ORIGIN_HOME" peer worker-host --ssh-alias worker-bridge \
  --ssh-config "$PRIVATE_SSH_CONFIG" --allow-agent coordinator \
  --allow-op watch --allow-op status --allow-op agents --allow-op receipt
csl bridge --home "$ORIGIN_HOME" run
```

The SSH configuration must be an owned private regular file. The receiver can
configure this origin using `peer origin --receive-only` and its own explicit
permissions: the origin initiates requests and watches; no reverse SSH access
or origin listener is needed. The worker publishes progress/final normally.
The caller sends and waits using the same commands below, in its actual
conversation. It retains stable operation IDs, receipts and event cursors.

This client never attaches to a native conversation, launches a model, or creates
a replacement coordinator. Its status is `tool-client`; it rejects incoming
activation, steering and interruption of the caller. An explicit `wait` result
delivers events to the calling model. Asynchronous injection into a caller that
is busy elsewhere, or waking that caller when idle, is **not** provided by this
mode. It is a partial integration for testing a real current caller, not full
runtime coordination equivalence.

For the specific tool host that exposes `functions.exec`, `yield_control()` and
`notify()`, [current_caller_collector.js](../experiments/bridge/current_caller_collector.js)
is a reviewable bounded collector. The existing caller runs it itself, with its
own origin home and consumed cursor. It leaves the tool invocation alive,
waits without inference, and emits remote events as late tool outputs while
the caller can continue other work. It sends no assignments, changes no policy,
and never addresses a different caller. Stop the cell to cancel collection;
an outstanding CLI wait ends within its bounded timeout. Durable bridge events
can be replayed from the last consumed cursor.

A synthetic delayed notification was observed in the implementer's active
conversation during another tool operation, before any explicit cell wait.
The actual coordinator's collector integration remains pending review/test.
These helpers are supplied by that tool host, not a documented general Codex
app-server or MCP push-to-model API. The snippet does not establish delivery
while the caller is idle or after the tool invocation/session has ended.

Use selected UTF-8 text in a file or stdin (`--text-file -`). Bodies never enter
SSH command strings or Codex CLI arguments. No entire history, binary attachment,
repository or credential file is collected. References may be ordinary text;
they are not automatically fetched.

From Alice's existing coordinator conversation, a tool can call:

```sh
csl bridge --home "$ALICE_BRIDGE_HOME" followup --from coordinator --peer bob --to worker \
  --request-id "$TASK_UUID" --text-file selected-request.txt
csl bridge --home "$ALICE_BRIDGE_HOME" send_message --from coordinator --peer bob --to worker \
  --text-file selected-clarification.txt
csl bridge --home "$ALICE_BRIDGE_HOME" agents --peer bob
csl bridge --home "$ALICE_BRIDGE_HOME" status --peer bob --to worker
csl bridge --home "$ALICE_BRIDGE_HOME" wait --agent coordinator --after 0 --timeout 20
```

`TASK_UUID` is a fresh stable UUID chosen before sending. Followup returns a
receipt with request/thread/turn IDs. Reusing the same ID and content returns
the receipt; changing the content under that ID is rejected. A message to an
idle agent stays pending without starting generation, then enters automatically
when that conversation becomes active. This is not a manually consulted inbox.

While Bob's worker is running the delegated task, its local tool can send progress:

```sh
csl bridge --home "$BOB_BRIDGE_HOME" progress --from worker --task-id "$TASK_UUID" \
  --text-file selected-progress.txt
```

That event returns automatically to the originating coordinator. If it is
waiting, its wait returns; if it is actively working, the runtime receives the
event at a safe boundary. If idle/disconnected, the event is retained and delivered
on its next activation. No model is started just to announce every update.
Turn completion returns the final text/state automatically by the same route.
Advance the local `wait --after` cursor only after consuming the returned event;
retrying a wait with the old cursor rereads it without repeating work.

To interrupt, use the exact current delegated turn from the receipt/status:

```sh
csl bridge --home "$ALICE_BRIDGE_HOME" interrupt --peer bob --to worker --turn-id "$TURN_UUID"
```

`interrupt_requested` is an acknowledgement, not confirmation of cessation.
Wait for a final event with `status: interrupted`. A fresh followup later uses
the same registered conversation, context and tools.

## Recovery And Limits

Messages are remote agent data, never system/developer instructions or approval
decisions. The receiver's original mandate and local permissions still apply.
The peer has no API for shell commands, policy changes, accounts, arbitrary
filesystem reads, all conversations, or approvals. Permissions are per peer,
operation and registered local agent. Interrupt also requires a matching
delegated task/turn.

Bridge data uses private SQLite transactions, one connector per home and durable
IDs. Chronology uses local sequences, not clocks shared across machines. Result
events stay retained; there is no automatic deletion or history synchronization.
Transport loss does not cancel work. If a request becomes `uncertain`, query its
receipt rather than sending another task:

```sh
csl bridge --home "$ALICE_BRIDGE_HOME" receipt --peer bob --operation-id "$TASK_UUID"
```

On native reconnection the connector checks native client-message IDs and turn
history for evidence before updating uncertain state. Recovery inspects at most
200 recent turns in each explicitly registered conversation; missing evidence
remains uncertain. It never silently replays an invocation or guarantees
exactly-once execution across a crash. A receipt `not_found` is not authority to
create a replacement task while the prior outcome is unresolved.

Event watch requests block up to 15 seconds and reconnect with bounded backoff;
tool waits block at most 20 seconds. They do not spend inference to poll. There
is no automatic chain of new assignments on receipt of a result. The owner
controls when to delegate again and remains responsible for scope and cost.

Selected outgoing text has partial secret detection. Findings stop the send;
`--scrub-secrets` applies to that one selected text only. It is not persistent
permission to retain secrets or a guarantee that all secrets are removed.
Automatic final text with detected findings is withheld while completion status
still returns. Review locally before sending selected evidence. Diagnostics do
not print bodies, credentials or account configuration; explicit read/wait
outputs contain the selected remote content and its provenance.

## Reproduce The Confined Laboratory

The normal synthetic tests do not launch Codex or SSH:

```sh
python3 -m unittest discover -s tests -p test_bridge.py -v
```

With Codex 0.167.1 installed, these explicit laboratory commands start only
temporary app-servers, private Unix sockets and loopback HTTP backends. They
use fabricated provider responses, isolated homes/environments and no model
credentials, personal sockets or authentication. Each process is stopped at
the end. Reports and synthetic traces are retained in the printed temp directory.

```sh
python3 experiments/bridge/runtime_gate.py
python3 experiments/bridge/connector_gate.py
```

The first checks join, concurrent input, steering, interruption, protocol UI
approval routing and reconnect. The second runs two native engines with the
production connector: delegation, clarification, progress waking wait,
automatic final delivery, idle-message semantics, interruption and recovery.
An additional Linux PTY gate exercises the actual terminal UI with the same
synthetic backend:

```sh
python3 experiments/bridge/tui_gate.py
```

Passing these gates does not complete acceptance with real Codex models or
establish Mac, SSH or cross-account compatibility. Restarting a connector may
resume previously authorized pending followups; it does not create new assignments.
