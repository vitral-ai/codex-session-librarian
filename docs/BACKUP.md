# Encrypted backup: development manual

Experimental Linux/Codex functionality in this development branch, not included
in published v0.1.1. Manual full checkpoints are implemented in F1; incremental
reuse, scheduling and retention are later cuts, not implied by these commands.
No real-data activation or new software release is authorized by this document.

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
manual-stdin tests does not establish unattended custody.

## Proposed operator flow on this branch

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
Proposed budgets include10000 sessions,16MiB catalog,2GiB/run and1h/run, not SLA.
Small restores can download much more than one session; retaining one member keeps
its entire container. No automatic repack or remote deletion is implemented here.

## Maintenance

Version reuse binds source bytes/state, origin, profile, recipients, secret policy,
producing CSL version, `csl_backup_format.EXPORTER_VERSION` and
`csl_secrets.RULES_VERSION`. Bump exporter/rules versions whenever semantics change,
even before a release; no Git checkout is needed at runtime. New producer versions
invalidate reuse, but the reader does NOT require equality with its current CSL
version to load an older compatible schema/profile. A format change still requires
an explicit adapter/schema decision, not a version-number bypass.

See [F0 review](BACKUP_F0_REVIEW.md), [container ADR](BACKUP_ADR_002_CONTAINERS.md)
and the separate synthetic F1 evidence. No universal compatibility, secret
detection, durability SLA, WORM behavior, forensic erase or recovery without keys
is claimed. Project files, external dependencies, auth and installed tools are not
included. Admins can remove remote data; downloaded ciphertext cannot be revoked.
