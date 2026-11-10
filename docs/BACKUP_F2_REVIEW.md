# CSL Backup F2: incremental heads and recovery candidate

2026-11-10. Base F1 closure `11ae61a279e3db5a35d131b490abadc096c24c54`.
Branch `feat/backup-f2-heads-recovery`, isolated implementation worktree.
Technical candidate within AUTH-019, subject to owner review. No software release,
push, real-data activation, timer, retention or F3/F4/F5 gate is claimed here.

## Delivered behavior

The writer publishes encrypted catalog2 logical heads; readers accept catalogs1/2
and immutable physical schema1 containers. A1+B1 in P1 followed by A2 in P2 restores
exactly A2+B1, while old checkpoints still restore A1. Manifests and historical
capture/integrity dates are not rewritten. Asset identities, memberships, source,
profile, recipients, native hashes, unique heads and coverage counters are checked.

Coherent source hash/state/producer fingerprint controls reuse. Lightweight
asset/envelope checks establish available, preserve full verification dates and
expose30day debt without automatic full downloads/jobs. Local observations/events
and run summaries are separate from immutable catalog evidence. Missing-local
heads remain protected, stale last-good is explicit, partial never replaces the
complete pointer and partial restore requires opt-in. No current success is a
failed run. Duplicate local UUIDs do not select an arbitrary winning file.

Durable encrypted plans occupy two extra assets in the checkpoint draft, for
four assets per CP. Opaque control binds source/run/baseCP/generation; no transcript
or ciphertext enters Git control. Accepted uncertain writes resolve stable IDs,
download/decrypt and adopt exact logical bindings; no overwrite/blind POST retry.
Remote-plan resume after journal loss uses only demonstrable uploaded bytes. It
reports the interrupted cut, never source bytes captured later. Unavailable old
bytes become explicit partial/failure.

Each explicit resume takes a new fencing generation, including when the previous
process of that same run is paused. Artifact reservation epoch and pointer commit
epoch are separate. Another source completing within the same set does not retire
a pending source whose own baseCP remains unchanged; active other writers,
retired/misbound intentions or superseded baseCP block takeover.

Capture budgets precede further copying; coherent excluded-agent headers avoid a
full copy. ZIP verification/extraction streams members. A measured quadratic
URL-password scheme scan was fixed with a token-start guard and compatible prefix
handling. Detector rules2 invalidates reuse; unrelated canonical JSON rules remain
unchanged. Existing capture/age/download ownership, ZIP preflight, native
metadata-only quarantine, profile checks and restore receipts remain covered.

## Verification and limitations

Private evidence: `.local/backup-evidence/f2/`; no keys or real histories in Git.
The live trial ran on prefreeze dirty modules with detector rules1. Later guards,
status summaries, multisource takeover refinement and detector rules2 have local
regressions; do not attribute the live execution to a SHA created afterwards.
A fixed final-code full suite and source/artifact seal are recorded separately.

| Requirement | Evidence | Result/scope |
| --- | --- | --- |
| F2-T01 hash vs mtime/size | `test_backup_incremental` + live bootstrap/reuse/change | Same content reuses; same-size byte change captures a new version. |
| F2-T02 producer/state changes | rule-version/archive tests; prior checkpoint restore | New keys; prior bytes still addressable. Profile/recipient resume mismatch blocks. |
| F2-T03 evidence levels | availability/date tests, local events, run summaries; cold restore | Referenced control, available metadata, full hashes and per-member installed receipts remain distinct. |
| F2-T04 full30d debt | synthetic2099 clock and manual verify test | Due visible; no automatic ciphertext download or date rejuvenation. |
| F2-T05 uncertain writes/journal loss | transport state machine + live interruption/resume | Every accepted POST response-loss boundary adopts one asset; real uploaded pack recovers without local journal. |
| F2-T06 exact interrupted cut | local fault injection + live A3→currentA4 | Restores A3, fresh_capture=false; never invents missing bytes. |
| F2-T07 partial/deletion/corruption | local malformed/upload-failure/tamper/deletion tests | Complete pointer preserved; explicit stale/missing-local/failure counts; no overwrite. Live remains happy recovery, not remote destructive negatives. |
| F2-T08 origins/fencing | same UUID/source separation, old writer, same-run takeover, other-source takeover | Old execution fenced; other-source free-set progress does not strand valid pending source. Local state-machine tests, not live multiwriter scheduling. |
| F2-T09 restore receipts | inherited F1 plus P1/P2 old/new restoration | Exact head selection and cross-checkpoint UUID reuse/conflict; sources intact. |
| F2-T10 memory/I/O/costs | `scale-32mib-02.json`, live costs/ledger | Measured local warm-cache probe and bounded real API use; no multi-GB remote benchmark. |

Focal candidate:88 backup tests plus19 secret tests, including29 new backup and
one new detector regression versus F1. Prefreeze full suite:353 tests, no skips
or failures,156.790s (`regressions-01`). Final fixed-SHA full suite remains the
candidate's decisive regression record; this prefreeze count is not substituted.

Real-age local scale:100707331bytes of synthetic fixtures (three~32MiB members),
two captured plus excluded agent,67138220captured bytes and67159750final ciphertext
bytes in two containers. Capture/pack/decrypt/full member hashing:2172ms; Python
traced peak2323455bytes; process `/proc` VmHWM27960→29876KiB. Logical I/O:
537561651read/268584134write bytes, warm cache (`read_bytes/write_bytes` zero).
Reduced budget captured one, failed one before copying, excluded one; source
hashes unchanged. `ru_maxrss` inherited an unrelated~2.9GiB high-water baseline
and is explicitly not used as the probe allocation claim.

Preserved failures: initial scale probe interrupted after prolonged CPU; isolated
16KiB non-URL scheme regex took~0.124s. First corrected probe completed work but
its harness tried to serialize float seconds with the deliberately integer-only
canonical serializer; reporting integer milliseconds corrected the harness. Both
logs remain. No output was deleted to conceal a failure.

## Bounded live evidence and costs

`live-01`: real age1.3.2, selected own GitHub identity manunruks/351611265,
private product repository1452127356. Four CPs and three physical packs added
**7releases/22assets/75614bytes**. Final accumulated F0–F2 inventory across both
authorized repositories: **20releases/44assets/189632bytes**, under40/80/50MiB.
No DELETE/settings/perms/login changes or new repositories. Prior F0 untouched.

Cold B was initially empty; A was hidden. It received external private identity
only through stdin and its own GET-only memory transport. Restored exactly two
heads A3+B1 while current A was A4; no obsolete A1/A2 extra. Repeat used the same
UUIDs; wrong key exit3 preserved copies; latest cached failure remained visible.
Native Codex0.167 reader/default/archived picker passed without network/generation.
No keyring/headless claim, no portable live trial in this phase, no paid inference.

Product transport:600 GitHub CLI invocations,46 binary downloads/190734bytes,
22 asset uploads/75614bytes. Prefreeze `metadata_calls=554` includes22 uploads;
normalized metadata-only=532. Laboratory inventory:33 observations of BOTH repos,
66 metadata GETs and66 wrapper identity GETs. Product wrappers add600 identity GETs;
helper initialization adds1 and explicit session identity API/user check adds2.
A-side total1335 GitHub calls; cold broker adds41 GETs/143185response bytes,
zero failures/write attempts:1376 counted GitHub calls altogether. CDN redirect
GETs are additional and not counted. `costs-reconciled.json` preserves corrections
to the original harness counters (two explicit resume inventories and final
inventory were initially omitted). These are actual trial costs, not a quota.

Reuse reduces payload uploads, not control overhead. This small trial's bootstrap
needed133 JSON requests plus9 binary downloads before wrappers; reuse needed93
JSON requests plus8 small binary/envelope/catalog downloads and zero container
ciphertext downloads. Grouping still controls physical writes, but these counts
must not be presented as a sustained1000-session/hour benchmark or F0 model proof.

## Candidate handoff

See the final private regression result and source/artifact seal for fixed commit,
commands, environment and hashes. Owner review decides F2 closure. No later phase
was started and no personal timer/retention/custody was activated.
