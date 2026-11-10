# Synthetic F2 validation

Only controlled fixtures and disposable identities, no real histories or auth
copies. Keys remain in memory/stdin/FD and are discarded after the trial. This
harness is not an installed backup service. Product flow is in `docs/BACKUP.md`.

`live.py` uses real product engine, optional age1.3.2 and the explicitly selected
`gh-manunruks`, bound to private product repository1452127356. It reuses F1's
bounded transport/inventory and GET-only cold-B broker. Before every release or
asset POST the inventory of BOTH authorized F0/F1 repositories is reobserved
against the accumulated40releases/80assets/50MiB ceiling. No DELETE/settings/login
changes, real histories, paid model calls or software release publication.

A complete trial adds seven encrypted backup releases and22assets: bootstrap
pack+checkpoint, reused checkpoint, changed-head pack+checkpoint, interrupted
accepted pack+checkpoint resumed without local journal. Each CP has four assets
(plan+envelope and catalog+envelope). The plan does not get another release.
The one cold B receives external identity and own authorized GET-only transport;
A is hidden. It restores A3+B1 from the interrupted cut while current source is
A4, then repeats without new UUIDs and tests wrong-key failure/native visibility.
This establishes those bounded cases, not all providers/profiles or keyring/headless.

```bash
python3 -m experiments.backup_f2.live \
  --out .local/backup-evidence/f2/live-01 \
  --age-dir /EXPLICIT/ISOLATED/age-v1.3.2 \
  --identity-helper /EXPLICIT/PRIVATE/api_memory.py
```

Do not blindly rerun: accepted writes can outlive a failed client response.
Inspect ledger and stable intentions first. Evidence includes failures unchanged.
Wrapper identity GET/user and inventory metadata GETs are additional to product
transport counters. Cold broker bytes/calls and CDN redirects are separate.

`scale.py` uses three synthetic32MiB members: two eligible plus an excluded agent,
real age and no remote transport. It measures full capture/pack/decrypt/hash,
Python allocations, Linux `/proc/self/status` VmHWM/RSS and logical `/proc/self/io`.
A reduced budget proves refusal before the second eligible copy. It is a warm
local filesystem probe, not disk throughput, network or multi-GB benchmarks.
`ru_maxrss` can inherit an unrelated parent high water value; the evidence reports
that baseline explicitly and uses process `/proc`/tracemalloc for allocation claims.

```bash
python3 -m experiments.backup_f2.scale \
  --out .local/backup-evidence/f2/scale-32mib.json \
  --age-dir /EXPLICIT/ISOLATED/age-v1.3.2 --mib 32
```

The initial scale attempt found quadratic scheme retries in the existing URL
password regex for long non-URL tokens. It was interrupted and recorded. A token
start guard with compatible prefix handling fixes the measured case; detector
RULES_VERSION2 forces new version keys. The original interrupted log and a later
harness float/canonical-output failure remain in private evidence. The latter was
fixed by reporting elapsed milliseconds as an integer, without changing the core
canonical serializer's contract.

Full regressions use the existing optional media interpreter, isolated native
probes and explicit opt-ins; no commercial inference:

```bash
CSL_RUN_MEDIA_TESTS=1 CSL_RUN_CODEX_NATIVE_TESTS=1 \
CSL_RUN_CLAUDE_NATIVE_TESTS=1 CSL_RUN_MIGRATION_E2E_TESTS=1 \
CSL_MEDIA_SANDBOX=required CSL_MEDIA_PYTHON=/EXISTING/media-venv/bin/python \
/EXISTING/media-venv/bin/python -m unittest discover -s tests -v
```
