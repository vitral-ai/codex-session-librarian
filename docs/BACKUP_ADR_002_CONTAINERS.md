# ADR 002: bounded encrypted containers for logical conversation versions

Status: accepted as a technical direction for F0 evaluation/prototype by Manunruks
on 2026-11-09; overall F0 gate still under review. Contract clarification 0.2.2.
This specific resolution is NOT attributed to a separate decision by Luis.
It remains within AUTH-019, the existing GitHub candidate and F0 scope.

## Context

A release + two assets per logical version projects at least3015 content writes
for a1000-session bootstrap, before per-object intentions or lease renewals. This
conflicts with the proposed one-hour run and documented general content creation
reference. Reducing product scope to100 sessions would not resolve the use case.

Putting many independent assets in fewer releases alone still needs one upload
per asset. Therefore compare grouping payloads, not just release metadata.

## Decision and identity

Group logical version snapshots into bounded encrypted containers for the same
set/source/profile/recipient configuration. No cross-set/source/profile dedup.
Keep version_key, logical UUID/member ID, provenance and restore receipts per
conversation. A container is a distinct physical storage identity, not a new
conversation or replacement for version_key.

Encrypted catalog entries bind logical version/member to container ID, asset ID,
ciphertext hash/bytes, member path/length/plaintext hash. An encrypted manifest
inside the container repeats the binding; recovery checks both and each member.
Exterior descriptors/control expose only opaque operational IDs, cipher, lengths
and ciphertext digests; no plaintext/native UUID, paths or conversation titles.

Current F0 layout schema represents one container; product F1 must compose it into
the complete checkpoint schema, not mistake a two-member experiment for the full
backup engine. Restore validates all selected required containers before session
installation. Download/decrypt each container once per operation, even for multiple
members; receipts and UUID collision/reconciliation remain per logical session.

## Size limits and packing

- Normal container maximum is64MiB of FINAL ciphertext, including ZIP, manifest
  and age overhead, not64MiB of member bytes. Reserve packing headroom and check
  actual final bytes before upload. Exact limit and +/-1 boundaries are tested.
- Preserve the prior256MiB physical object limit: an individual member that cannot
  fit a normal container can use a dedicated `oversized_single` container, one
  member only, final ciphertext at most256MiB.
- If final ciphertext exceeds256MiB, fail explicitly (or eligible failure in F2
  partial flow); never silently split, truncate, exclude or relabel as complete.
- F0 prototype uses tiny synthetic members; it proves encrypted format/bindings,
  not a sustained throughput or near-capacity packing benchmark.

Future changes go into new containers; references to unchanged logical versions
remain in older containers. No automatic repacking or overwrite. Repacking, if
ever chosen, creates a new container and newly verified bindings, never edits old
ones. No delta format is introduced.

## Retention and trade-offs

GC can remove a container only when ALL its members are unreferenced by retained
catalogs, pins, active intentions or protected checkpoints. A single referenced
member keeps the whole container alive. Cannot free just one encrypted member.
No automatic repack to reclaim space; future F5 must account for this reachability
and physical-byte granularity. No remote DELETE authorized by this ADR.

For1000x1MiB snapshots and64MiB grouping, the offline model estimates16 containers,
34 assets and127 writes including intent per physical container, versus7015
with intent per old physical object. A100-member incremental run estimates two
containers/six assets/29 writes. These are formulas, not measured API throughput.

Single-member restore can download/decrypt up to64MiB, about64x for a1MiB member;
metadata/age overhead is additional. Tiny members can see greater ratios. Initial
upload payload bytes are not reduced absent compression; API counts are reduced.
Individual versions remain reusable but retention can keep more obsolete bytes.

## Validation and remaining gate

New structural/semantic negatives reject duplicate members, path traversal,
cross-source entries, unknown layouts, multi-member oversized containers, and
final ciphertext beyond its layout limit. Schemas/fixtures are experimental.

The bounded live prototype may use only the two remaining authorized F0 releases:
encrypted pack and encrypted catalog, with opaque descriptors. It must cold-read
two members in B using only external recovery key and own authorized transport
credential in memory, with A hidden and no operational private key, journal or
catalog copied. Actual result/inventory goes in separate evidence; no blind retry
when a mutation may already have completed.

F0 gate remains subject to review of evidence, clocks/fencing/backend bounds and
profile usefulness. F1 still needs operational keyring custody, atomic native
installation/visibility and complete E1, not merely crypto or hash success.


## F2 accepted refinement: logical heads and recoverable intentions

Within AUTH-019, Manunruks accepted schema2 encrypted catalogs with explicit
logical heads (container/member/hash/version), while physical manifests stay
schema1 and immutable. New readers accept catalogs1/2; old readers reject2.
P1 containing A1+B1 remains unchanged when P2 captures A2: a new catalog selects
A2+B1 and restores exactly those heads. Old A1 remains recoverable from its old
checkpoint, without being an extra restored conversation in the new checkpoint.
Every referenced container is a GC root even if only one member remains selected;
no automatic repack or remote deletion is introduced.

A checkpoint reserves one draft release early, uploads encrypted `plan.age` and
an opaque plan envelope, and later adds encrypted catalog plus its envelope.
Thus F2 uses four assets/checkpoint, rather than F1's two. No separate plan release
or conversation data/ciphertext in the Git control branch. The control contains
opaque run/checkpoint/source IDs, base checkpoint and generation bindings only.
Drafts are not healthy/restorable. Existing accepted ciphertext is adopted only
after decrypting and matching the intended logical bindings, never overwritten.
Lost journal recovery uses the remote encrypted plan and only demonstrable bytes.
Missing never-uploaded bytes become explicit partial/failure, not current recapture.

A new resume execution acquires a new fencing generation, including for the same
run ID. Checking only owner=run ID would allow a paused previous process to wake
and write. Artifact reservation epoch stays immutable; a fenced pointer records
both that artifact epoch and the new commit generation. Compare base complete CP
and current CAS epoch before takeover; stale renewals/commits fail. A second
base-source checkpoint binding protects newer partials of the same source while
allowing another source to progress. Decrypted plans must match every reserved
intention ID, both bases and artifact epoch before acquiring/writing; a valid
envelope alone cannot substitute another checkpoint.

Incremental reuse carries old integral timestamps and records new lightweight
availability separately. Full verification due after30days is visible and deferred
until explicit verification/restore; there is no background job. Evidence in each
catalog is immutable as-of publication; later local observer/asset/hash events do
not alter previous catalogs or claim another environment's restored state.
