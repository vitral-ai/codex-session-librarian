# F3 local future-rotation validation

`rotation.py` runs the product backup/rotation/restore methods with real pinned
age1.3.2, four disposable in-memory synthetic identities, an in-memory FakeStore
and FakeControl. It creates no GitHub releases/assets and makes zero GitHub calls.
This is crypto-real/local evidence, not a live GitHub or keyring/headless trial.

```bash
python3 -m experiments.backup_f3.rotation \
  --out .local/backup-evidence/f3/local-age-final \
  --age-dir /EXPLICIT/ISOLATED/age-v1.3.2
```

The first epoch has operational+external recipients, then a reviewed plan rotates
both public recipients for future versions. Old ciphertext stays identical.
New versions get a new profile epoch and full initial verification, without reuse
of old-only ciphertext. Two initially empty destination homes in the same Python
process restore with old/new external identities respectively; neither operational
identity is passed to restore. These are not separate cold processes or a source
filesystem sandbox. There is no new native-client/model continuation claim.

Wrong epoch and absent identities must fail without changing installed copies;
repeat restores retain UUIDs. Invalid public-recipient checksums must fail the
real-age probe without config/control mutation. The public plan, epoch map,
synthetic catalogs, source hashes and source HEAD are saved. Private identities
remain in memory/memfd and are discarded; they are never logged or saved.

`tests/test_backup_keys.py` adds fake-store fault/state tests for full plan binding,
config/producer/set-generation staleness, source ambiguity, active/expired lease,
old writer/resume fencing, accepted-CAS response loss, local install/receipt failure,
local edit conflicts, later-rotation rollback rejection, epoch map validation,
profile policies, offline listing and CLI stale exit5. These mocks establish state
semantics, not real GitHub API timing or private-key custody.

Historical re-encryption and native-sanitized are not selected; F3-T05 is N/A.
No DELETE, permission changes, timers, auth copies, real histories or paid inference.
The last remotely observed accumulated laboratory ledger remains F2's20 releases,
44assets and189632bytes. F3 adds zero; it does not pretend to have reobserved
availability remotely. The global40/80/50MiB ceiling is not reset.
