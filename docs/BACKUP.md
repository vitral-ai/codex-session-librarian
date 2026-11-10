# Experimental encrypted backup

Experimental Linux/Codex functionality prepared for v0.2.0; it was not included
in v0.1.1. Confirm the exact published tag/SHA in GitHub Releases. F1 provides
manual encrypted capture/restore; F2 adds
conversation-level incrementals, explicit resume, partial coverage and multiple
origins. F3 adds reviewed future recipient rotation; scheduling and retention
remain later cuts. Historical re-encryption and native-sanitized profiles are not
selected in this scope.
Installing CSL does not activate backups, timers or personal data collection.
The release is normal; this backup feature remains explicitly experimental.

## Scope and custody

Backup is separate from `share` and one-time `migrate`. It uses its own private
`$CODEX_HOME/csl-backup` configuration; it never inherits `csl team connect`.
Choose an existing private repository and authenticate separately with your own
GitHub account. CSL never creates accounts/repos, grants scopes, changes logins
or selects billing. All readers of the repository can obtain its ciphertext.

Objects AND detailed catalogs are encrypted using the optional pinned age CLI
v1.3.2/X25519. Install and verify it explicitly; CSL does not install dependencies.
Configure two distinct public recipients: operational and external recovery.
Keep the recovery private identity outside the computer being protected. Losing
both identities makes these backups unrecoverable. Private repository access is
not a substitute for custody or content encryption.

Operational custody can be an explicitly chosen manual stdin pipe or a reference
to a system keyring (`keyring:UUID`, `secret-tool lookup service csl-backup key_id UUID`).
CSL does not populate that keyring, generate keys, write private identities into
config/files/argv/env, or fall back to a plaintext key when lookup fails. A
headless/scheduled setup must prove keyring availability separately; passing
manual-stdin tests does not establish unattended custody. Positive system-keyring/
headless operation has not been validated; F4 scheduling is not included.

## Manual operator flow

Public keys below are placeholders. Do not put a private key on the command line.

```bash
csl backup init --repo OWNER/PRIVATE-REPO \
  --set-name "Personal work" --source-name "Work laptop" \
  --recipient PUBLIC_OPERATIONAL_RECIPIENT \
  --recipient PUBLIC_EXTERNAL_RECOVERY_RECIPIENT \
  --key-reference keyring:KEY_ID

csl backup run --set SET_UUID --dry-run
csl backup run --set SET_UUID
csl backup status --set SET_UUID
csl backup status --set SET_UUID --cached
```

`--github-cli` explicitly selects a GitHub CLI/wrapper executable; the default is
`gh` with that person's existing authentication. `--age-bin` selects the verified
age executable. No account switching is performed. Source IDs are random, not
hostnames. Repeating init with the same local labels/config reuses set/source;
material changes conflict rather than silently creating a second origin.
To add a distinct origin to an existing remote set, explicitly initialize with
`--set SET_UUID` and a new `--source-name`. This allocates a fresh source UUID;
it never adopts an old source by hostname. Use `--source SOURCE_UUID` when several
local sources or remote latest pointers would otherwise be ambiguous. Equal
native UUIDs from different sources are independent versions.

Archives are included. Agent forks are opt-in at init with `--include-agent-forks`.
Known Codex0.167 structured SubAgent sources are preserved, not converted to cli.
Other known noninteractive sources are reported as excluded; unknown shapes fail
explicitly. Native empty/metadata-only/pending sessions are preserved with their
limitations reported, without inventing messages; an unsupported installation is
quarantined. Portable export can reject an empty state it cannot represent.

## Policies and profiles

- `native-age-v1` preserves exact captured JSONL bytes, including opaque state;
  installed copies necessarily change UUID/cwd and may not reproduce hidden
  account-specific state. Native byte preservation is not portable model continuity.
- `portable-age-v1` uses the existing portable exporter, reserializes JSON and
  omits supported encrypted reasoning/state. Losses are recorded. It is a
  complementary representation, never silently substituted for byte-exact native.
- `--secret-policy stop` is default and blocks before remote writes if the partial
  readable-text scanner finds a possible secret. It does not guarantee absence of
  undetected/binary/opaque secrets.
- `retain` requires `--accept-retain-risk` at init and always remains encrypted.
- `scrub` requires explicit portable profile; it modifies only output copies and
  does not promise to sanitize opaque attachments. Native+scrub is rejected.

A failing eligible source produces explicit partial coverage when other eligible
sources succeed. `latest_partial` is separate from `latest_complete`; `restore
latest` continues to use the complete pointer. Restoring a partial UUID requires
`--allow-partial` and reports omissions/stale entries. No current successes means
a failed run, never a healthy draft. A locally missing conversation retains its
verified remote head and original observation date as `missing_local`, without
propagating a deletion. Exclusions, current captured/reused, failed, stale,
missing-local and protected counts are separate; protected is not eligible success.

No generic unencrypted-backup switch exists. Test plaintext stores are separate
synthetic harnesses, not an option for personal conversations.

## Restore without the old computer

```bash
csl backup discover --repo OWNER/PRIVATE-REPO
csl backup list --repo OWNER/PRIVATE-REPO

# Pipe a private identity from authorized external custody, never paste it in argv.
RECOVERY_CUSTODY_COMMAND | csl backup restore latest \
  --repo OWNER/PRIVATE-REPO --set SET_UUID --source SOURCE_UUID \
  --cwd ~/projects --identity-stdin
```

`RECOVERY_CUSTODY_COMMAND` is deliberately not a real command; use the custody
mechanism that was explicitly configured. Do not create a plaintext key file as a
workaround. The new cwd must exist. `latest` means the last complete checkpoint
of an unambiguous set/source, not GitHub's latest release or another person's run.
Explicit checkpoint UUID restore is also supported. `--dry-run` verifies without
installing. `discover --scan` is read-only unverified candidate discovery, not a
pointer repair or proof of recovery.

Every selected container is downloaded/decrypted and validated before session
installation. ZIP declared sizes, total size, paths, types and compression ratios
are checked BEFORE reading members; reads are bounded. Each container is fetched
once per operation even if it contains several sessions. Schemas and inner
repo/set/source/profile/recipients/member bindings must agree.

Native copies receive new UUIDs. Archives remain archived; agents retain their
source classification. Non-loadable state is retained in private quarantine and
is not claimed as successful model continuation. No historical tool executes, no
model opens, no old cwd is reconstructed and no backup config or timer is adopted.

Repeat restore reuses the verified local copy. A changed copy or different cwd
conflicts; `--new` explicitly creates another copy. Before publishing a session,
CSL durably reserves UUID/destination/expected installed hash. A crash after file
publication but before receipt reconciles that exact target instead of allocating
another UUID. Publication is atomic per session, not all-or-nothing for the batch.

## Evidence and limitations

```bash
csl backup verify CHECKPOINT_UUID --repo OWNER/PRIVATE-REPO --identity-stdin
csl backup verify CHECKPOINT_UUID --repo OWNER/PRIVATE-REPO --identity-stdin --native
```

Integrity means full ciphertext/manifests/member hashes verified, not model recall.
The optional native probe uses disposable localhost request reconstruction with no
paid generation and reports results separately. A structurally installed copy is
`native_unverified` until tested appropriately; hashes alone never imply native pass.

Catalogs remain immutable as-of evidence. Later verification/restore events are
private local records bound to observer, asset hash and, for restore, logical
member/version/installed UUID/hash. They are not another remote event service.
New B does not inherit A's later local verification history. Cached status labels
remote state unknown and recent failed attempts, not healthy because an old run
succeeded. Current control metadata alone is only a reference, not a new integrity
check. Historical captured/verified/restored times must not be rejuvenated by reads.

Normal ciphertext containers are at most64MiB including packaging/age overhead.
A dedicated `oversized_single` container can preserve one member up to the256MiB
final ciphertext limit. Beyond that, error explicitly; no splitting/truncation.
Product budgets include10000 sessions,16MiB catalog,2GiB/run and1h/run, not SLA.
Small restores can download much more than one session; retaining one member keeps
its entire container. No automatic repack or remote deletion is implemented here.

## Incrementals and durable resume

Catalog schema2 explicitly selects logical heads, each bound to an immutable
container/member/hash/version. If P1 has A1+B1 and P2 adds A2, the next checkpoint
selects A2+B1; restore never resurrects A1 merely because P1 remains referenced.
The reader still accepts schema1 catalogs (all members implicitly selected);
old readers reject schema2. Physical containers/manifests remain schema1.
Previous checkpoints and their capture/integrity dates are never edited.

Reuse compares the coherent captured source hash, origin, visibility and complete
producer fingerprint, never mtime/size alone. Each reused physical container gets
an existence/asset-ID/size/envelope binding check, reported `available`. This
preserves its previous integral verification date. `verification_due` becomes true
after30days under `light-each-run-full-30d-v1`; runs do not automatically download
the entire backlog. Manual `verify` and every restore read all selected containers
fully. Later checks create local observer/asset/hash events, not edits to catalogs.
Status returns local events separately from referenced remote control; a recent
failed attempt remains visible. No new recurring task is created.

Before release POSTs, private durable local state reserves run/checkpoint/object
IDs and encrypted object bytes. A draft checkpoint release receives `plan.age`
and `plan-descriptor.json`; it later receives `catalog.age` and `descriptor.json`.
That is **four assets per checkpoint**, plus two per new physical container.
A draft/plan is not a valid backup. New physical objects are downloaded, decrypted
and checked against the exact intended manifest before becoming published; the
catalog/envelope is verified before publication and the fenced control commit.
Uncertain POSTs resolve stable IDs and adopt remotely accepted bytes after full
logical binding verification, including randomized ciphertext; no overwrite.

```bash
csl backup run --set SET_UUID --source SOURCE_UUID --resume RUN_UUID
```

Resume targets the old cut and reports `fresh_capture: false`; changes to current
source files cannot silently change it. With local journal loss, remote control
identifies the encrypted draft plan. Already uploaded objects can be adopted; bytes
that were never uploaded and are no longer local cannot be invented. They become
explicit failures/partial coverage or a failed run. Resume requires the exact source
and producer fingerprint; reserved repo/set/source/run/checkpoint IDs, both base
checkpoint bindings and artifact epoch must exactly match the durable intention
before any acquisition/write. Resume rechecks reused remote references without
changing the old source observation dates. It does not recover/adopt a lost source configuration.
Do not delete local staging intentionally outside disposable test fixtures.

Every explicit resume acquires a **new epoch**, CAS-checking the current set
generation and the unchanged base complete checkpoint AND latest complete/partial source checkpoint. Another
source may have completed in between; that does not supersede this source. An
active different owner or a retired/misbound intention blocks resume. It fences a paused original execution of the same run,
as well as other sources. Artifacts retain their reservation `lease_epoch`;
control `catalog.lease_epoch` binds that immutable catalog and `commit_epoch`
records the currently authorized generation that committed the pointer. This lets
a new generation adopt a previously verified catalog without editing it. Ordinary
renewal requires an unexpired matching owner+epoch; no old writer reacquires itself.

Captures are admitted under the size/count budget before copying further files.
Coherent bounded native headers classify excluded agents before full capture;
unusual headers fall back to full validation. Verification/extraction streams member
bytes, rather than retaining all transcripts in RAM. Actual final ciphertext limits
still apply, with dedicated oversized single-member containers and no truncation.

Run `costs` reports uploaded/downloaded container bytes and transport call/byte
counters, including metadata/revalidation/control and plan/catalog/envelope traffic.
Upload bytes count attempted submissions; download bytes count received bytes.
Identity-checking wrappers, laboratory inventory checks and CDN redirects add their
own calls and are recorded separately by the laboratory. These are measurements,
not a provider quota or sustained throughput promise.

## Future recipient rotation (F3)

Rotation changes the future writer configuration for **one explicitly selected
local source**. It preserves profile, stop/retain/scrub policy and existing risk
acceptance. More than one local source requires `--source`; the plan lists affected
and unaffected remote sources. Nothing is inferred from hostname or an old history.

```bash
csl backup keys plan --set SET_UUID --source SOURCE_UUID \
  --recipient NEW_PUBLIC_OPERATIONAL_RECIPIENT \
  --recipient NEW_PUBLIC_EXTERNAL_RECOVERY_RECIPIENT \
  --key-reference stdin --out /PRIVATE/rotation-plan.json

csl backup keys apply --set SET_UUID --source SOURCE_UUID \
  --plan /PRIVATE/rotation-plan.json
csl backup keys list --set SET_UUID --source SOURCE_UUID
```

Public recipient placeholders above are not private identities. Optional
`--key-reference` chooses future stdin/keyring:UUID custody; omitted, the existing
reference remains. No keyring is populated, old identity removed or private key
generated. A pinned age encryption probe checks public-recipient acceptance;
it does not establish private-key possession, recovery or unattended custody.
The public epoch map is private local metadata; `keys list` works offline without
GitHub or age and does not claim that a key is currently available.

A reviewed plan contains public old/new recipients, profile/policy, source and
epoch IDs, exact current config/producer binding, current set generation, complete
and latest source checkpoint bindings, retained epoch dependencies and recovery
instructions. A private local reservation hashes the plan; edited public values
also require a new plan. Any set-generation, config, producer or source-state change
makes it stale (exit5), rather than changing the reviewed meaning. A valid active
writer blocks apply; an expired writer is fenced by a new generation.

Apply commits an opaque key-profile/epoch binding through the existing control
CAS chain, then atomically installs the future local config. Public recipients,
labels, keyring references and private material do not enter control. A durable
local intention and stable remote rotation ID let the same plan reconcile after
accepted-write/response loss, a crash before config write or before local receipt.
A conflicting local edit is preserved; a later rotation makes the older plan
inapplicable. Old writers and old pending resumes cannot publish with a superseded
crypto profile, even after acquiring a new execution generation.

The first run after rotation creates new ciphertext from current eligible source
files. It does not require the new operational identity to decrypt the old epoch's
catalog, does not reuse old-only ciphertext and does not invent freshness for
missing old local conversations. Old checkpoint UUIDs and encrypted assets remain
unchanged; their private identities are still required. If a new run has not yet
completed, `latest` can still refer to the old epoch and requires its identity.
Use an explicitly held external identity through stdin when recovering that CP.

The map records public recipients per profile epoch, known prior pointer UUIDs and
custody references; legacy entries are derived from local config, not an audit of
all historical objects. Keep every external identity needed by retained epochs,
and **test recovery of the retained checkpoints before retiring an operational
identity**. New objects have their own full verification and per-member restore
receipts; rotating does not inherit restored/native_passed from old ciphertext.

Historical re-encryption and a native-sanitized profile are N/A for this selected
cut. Native+scrub remains rejected; portable scrub stays explicit. No old asset is
overwritten/deleted, no old catalog rewritten and no downloaded ciphertext revoked.
Removing a future recipient does not remove that recipient's access to older bytes.
No timer, deletion permission, account change or new algorithm is introduced.

## Maintenance

Version reuse binds source bytes/state, origin, profile, recipients, secret policy,
producing CSL version, `csl_backup_format.EXPORTER_VERSION` and
`csl_secrets.RULES_VERSION`. Bump exporter/rules versions whenever semantics change,
even before a release; no Git checkout is needed at runtime. Detector rules2
bound URL scheme scanning to token starts, preserving password selection while
avoiding quadratic retries on long non-URL text. New producer versions
invalidate reuse, but the reader does NOT require equality with its current CSL
version to load an older compatible schema/profile. A format change still requires
an explicit adapter/schema decision, not a version-number bypass.

See [F0 review](BACKUP_F0_REVIEW.md), [container ADR](BACKUP_ADR_002_CONTAINERS.md)
and the separate synthetic F1 evidence. No universal compatibility, secret
detection, durability SLA, WORM behavior, forensic erase or recovery without keys
is claimed. Project files, external dependencies, auth and installed tools are not
included. Admins can remove remote data; downloaded ciphertext cannot be revoked.
