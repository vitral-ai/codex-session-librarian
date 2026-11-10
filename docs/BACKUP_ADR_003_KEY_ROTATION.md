# ADR003: reviewed future recipient epochs

Status: F3 technical candidate within AUTH-019 after F2 acceptance. Future-only
rotation selected by Manunruks; historical re-encryption and native-sanitized were
not selected. No new backend, algorithm, private-key store or unattended activation.

## Bind public plans, serialize future configuration

`backup keys plan/apply/list` acts on one existing local source. Plans enumerate
public recipients, profile/policy, affected/unaffected source IDs, current config
and producer hashes, old/new profile epochs, remote set generation and both
complete/latest-source checkpoint bases. A private local reservation binds the
entire canonical plan. Change any input and replan; no automatic normalization of
an obsolete plan into a different action. Planning has zero remote mutations.

Apply preserves profile/secret policy and existing profile-scoped risk acceptance.
Pinned age must accept the public recipients before applying. That probe does not
prove any private-key custody. No private material is read by rotation, no keyring
written and no old identity removed. Old external identities remain dependencies.

An atomic remote control CAS installs an opaque key-profile binding and a random
profile epoch while incrementing set fencing generation. Active writers block
rotation; expired paused writers lose their old token. Every subsequent lease
mutation checks the active crypto profile, so an old run cannot explicitly resume
and republish old recipients after the rotation. Crypto profile binding excludes
producer software versions; upgrades can create new versions within the same key
epoch. Plans still bind the full producer fingerprint and go stale across upgrades.

Control stores opaque IDs, config/plan/key-profile digests and operational dates,
not recipients, labels, keyring references, ciphertext or conversation data. A
stable rotation registry binds the applied result; this is an operation record,
not a remote verification/restoration event stream.

## Crash boundary and epoch identity

Before remote mutation, local intention reserves the exact proposed public config
and activation date. After CAS, local config is replaced atomically. An old local
config is blocked by the remote crypto binding until the same plan reconciles.
Accepted response loss, journal loss, config-write failure and receipt failure all
reconcile by stable plan/result IDs without a second rotation. Conflicting local
edits are not overwritten. Older plans cannot roll back a later active epoch.

New fingerprints carry `profile_epoch`. The updated reader accepts legacy
fingerprints without it and new fingerprints with a validated UUID. Older strict
F2 readers reject the new shape; existing old ciphertext/catalogs remain readable
by the new reader. Physical containers remain schema1; catalogs remain schema2.
A legacy epoch ID derives only from source/crypto profile, not software versions.

First post-rotation capture crosses an opaque checkpoint boundary: it skips
loading the previous epoch catalog, which the new operational private identity
need not decrypt. New eligible versions get new ciphertext and evidence. Old CP
pointers remain intact until a new complete CP commits; missing old local sessions
remain recoverable from old checkpoints with retained external identities rather
than being falsely copied into the new epoch's complete coverage.

## Cost and selected omissions

No releases/assets are created by plan/apply/list. Apply uses existing control
blob/tree/commit/ref writes plus revalidation/metadata checks; contention remains
bounded by Control. The F3 laboratory tests real age and two external epochs on
local synthetic in-memory transport/control, with zero GitHub calls/resources.
It does not claim a new live GitHub multiwriter or operational keyring trial.

Historical re-encryption is N/A: no extra historical bytes/API writes projected or
performed, no overwrite/GC, and no revocation promise. Native-sanitized is N/A:
no demand selected it, native remains byte-exact and native+scrub is rejected.
Portable scrub and explicit retain acceptance remain unchanged.
