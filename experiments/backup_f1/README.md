# Synthetic F1 validation

The product manual/limits are in `docs/BACKUP.md`. This laboratory is not a
general history export utility or installed service. All fixtures and keys are
synthetic, no paid model inference, no personal auth copies, no remote DELETE.

`live.py` is pinned to the authorized private repo
`manunruks/csl-backup-e2e-20261109`/1452127356. It uses real product engine, age1.3.2
and GitHub through gh-manunruks for A. A GET-only in-memory Unix transport feeds
the actual CLI in isolated B with only external recovery identity over stdin.
It cannot create remote resources from B or forward auth to redirected CDN hosts.
This is a temporary test transport, not new runtime architecture for CSL.

Every release/asset mutation reobserves BOTH F0 and F1 inventories against the
shared40-release/80-asset/50MiB ceiling. No blanket retry or automatic cleanup.
Uncertain writes can have completed: inspect the ledger/server before repeating.

Do not run it casually: a complete native+portable trial consumes four releases
and eight assets even though bytes are tiny. Initial runs and failures remain
in `.local/backup-evidence/f1/`, excluded from Git. Private synthetic identities
are deliberately not persisted, so discarded-key fixtures are not reusable for
future decrypt tests. Do not replace that with stored real keys.

`native_check.py` uses read-only Codex0.167 app-server methods in a network-disabled
namespace. It gets the native source filter enum from that CLI's generated schema,
checks archived/structured-agent/default picker distinctions, and treats quarantine
as exact evidence/N-A native rather than reanudadable history. It does not execute
turn/start, tool calls, or infer model recall.

Historical `live-03` used six sources in native clean B, then portable in that same
B. Current harness has evolved to include metadata-only; those later conditions
are NOT retroactively claimed in old evidence. See the F1 review for exact scope.
