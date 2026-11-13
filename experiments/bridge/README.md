# Confined Native Bridge Laboratory

Run only these explicit scripts from the repository root:

```sh
python3 experiments/bridge/runtime_gate.py
python3 experiments/bridge/connector_gate.py
python3 experiments/bridge/tui_gate.py
```

Requires an installed Codex CLI; exercised with 0.167.1. Each script starts real
app-server processes against synthetic loopback Responses backends in fresh
temporary homes. It does not use model credentials, inference, personal session
files or sockets, SSH, a Mac or a colleague's account. The third gate runs the
actual TUI in a Linux PTY against its synthetic native backend.

The backend emits fabricated text or a tool request whose approval is declined
by a protocol UI client. It never calls a model or authenticates an account.
The assertions inspect actual native thread/turn IDs, input reconstruction,
notifications and persisted history. The connector script uses the production
bridge implementation with explicit same-UID laboratory transport between two
native engines. Reports are not claims about real model/teammate behavior.

Scripts print the evidence directory and exit nonzero on a failed assertion.
All spawned native processes are stopped on completion; synthetic evidence is
retained for review. See [bridge setup and limitations](../../docs/BRIDGE.md).
