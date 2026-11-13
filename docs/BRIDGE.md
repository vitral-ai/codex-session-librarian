# Experimental Agent Coordination

This private candidate adds optional `csl bridge` commands for coordinating
existing Codex agents. A followup starts an idle agent in its own conversation;
a message enters active work at a runtime boundary. Progress and completed turns
return automatically. `wait` blocks on events rather than asking a model to poll.
Interrupt targets an exact delegated turn; a later followup continues the same
conversation. A completed turn is not proof that its technical conclusion is valid.

This is an experimental integration, not a supported cross-account Codex feature.
Native Codex **0.167.1** has been exercised with synthetic loopback Responses
backends, protocol clients and the actual terminal UI. Real inference, Mac, SSH to
another computer, and same/different-account operation have **not** been validated.
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

An app-server `--listen unix://PATH` endpoint was tested. An arbitrary managed
daemon's control socket or `app-server proxy` is **not** interchangeable with that
endpoint without verification. A standalone TUI using `--no-daemon` is not
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
that machine's owner. SSH/login integration remains untested in this candidate.

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
