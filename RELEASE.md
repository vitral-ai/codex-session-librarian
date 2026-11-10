# Release operation and published state

## Version records

### v0.2.1 — release candidate

This patch release adopts the visible name **Context Session Librarian (CSL)**
and simplifies the README around installation, finding conversations and transfers.
The `csl` command, `csl.vitral.ai`, provider coverage, formats, IDs and storage paths
remain compatible. The canonical repository is now
[`vitral-ai/context-session-librarian`](https://github.com/vitral-ai/context-session-librarian).
It adds no new backup or transfer capabilities.

Backup remains experimental, manual and Linux/Codex only, with externally
installed age v1.3.2 and operational/external recovery recipients. Positive
system-keyring/headless operation is unvalidated; scheduling, automatic retention
and historical re-encryption are not included. Published v0.1.x/v0.2.0 tags and
notes remain unchanged.

The producing CSL version is part of the backup fingerprint. Updating to 0.2.1
therefore starts a fresh capture instead of reusing objects from a different
producer version. Old checkpoints retain their original fingerprints and key
requirements; finish pending runs or rotation plans with their producing version
before updating. This patch does not re-encrypt old backups.

Validation belongs to this candidate's own fixed SHA: full media/native/migration
opt-in suite, isolated-prefix install/version/help and offline synthetic demo.
Actual results and the published commit belong to the corresponding GitHub
Release; no earlier result is attributed to this candidate. Preparation alone
does not establish publication.

### v0.2.0 — authorized release candidate

Luis authorized publication on2026-11-10. The owner selects and publishes the exact
reviewed commit after checks; this record is preparation until the
[v0.2.0 Release](https://github.com/vitral-ai/codex-session-librarian/releases/tag/v0.2.0)
exists. It is a normal version release with an explicitly experimental backup
feature. Existing v0.1.0/v0.1.1 tags and notes must not be changed.

Scope: existing library/transfer commands plus backup F0–F3: manual Linux/Codex
native/portable encrypted checkpoints, bounded containers, logical-head
incrementals, partial coverage, durable resume, fencing and future recipient
rotation. External pinned age1.3.2 is optional for core CSL and required for backup;
CSL does not install it. Manual stdin/memory/FD external-key recovery has synthetic
and bounded backend evidence. A system-keyring reference fails closed if unavailable;
positive keyring/headless operation is not validated. F4 timers, F5 retention/GC,
historical re-encryption, native-sanitized and new human pilots are not included.

Release validation must name its own fixed SHA: full media/native/migration opt-in
suite, isolated-prefix installation/version/capabilities/help and offline synthetic
demo. Earlier phase results remain attached to their own commits. The release
owner records final SHA, CI, publication date and clean tag-install result in the
GitHub Release; local preparation alone is not proof that a tag is published.
No private evidence directories, credentials, keys or real histories are assets.

### Earlier published versions

[v0.1.1](https://github.com/vitral-ai/codex-session-librarian/releases/tag/v0.1.1)
includes the historical-tool display, secret-review and recall corrections from
main. Exact publication SHA, date and CI are recorded in that GitHub Release.
The tag is official only once the Release exists; a prepared version string is
not publication. Runtime validation: 268 tests with native/media/migration opt-ins.

[v0.1.0](https://github.com/vitral-ai/codex-session-librarian/releases/tag/v0.1.0)
was published November 5, 2026 from
`edd05bb20eb145dea6178d548f1363b9516102af`, with its 253-test runtime record.
Its tag and notes remain unchanged; it does not include the later display/recall
corrections. Transfer to Vitral preserved its repository and Release identity.

The PR #9 historical 260-test result belongs to that earlier code, not all
subsequent main commits. Display, structural fidelity and model continuation
remain distinct checks. The current human pilot stays pinned to v0.1.0 unless
its version is explicitly changed; never mix participant versions silently.

## Procedure for a future authorized release

1. Obtain a scoped release decision. Select and record the exact upstream SHA;
   never substitute a moving main. Review license, version, changelog and scope.
2. Verify regressions, isolated installation and synthetic demo at that SHA.
   Do not count skipped tests as passes or attribute a prior run to another commit.
3. Verify the proposed tag does not already exist. Publish only the selected SHA
   and reviewed notes; never overwrite or retag an existing version. No private
   histories or test credentials may be release assets.
4. Install from the published tag in a fresh isolated environment. Check version,
   resolved SHA and demo. Align README, web and user documentation with reality.

Use the operator's own authorized GitHub identity (Manunruks uses gh-manunruks).
Repository access does not itself authorize a new version, a transfer or scope
expansion. Package-registry publication requires its own plan and verification.

## Native evidence gate

Ordinary CI covers Python 3.11/3.13 and optional media in process mode; it does not
by itself establish native CLI loading or migration E2E. The manual isolated native
workflow pins Codex 0.166.0 and Claude Code 2.1.308, enables native/migration opt-ins
and requires bubblewrap for media. Use synthetic temporary homes, no personal
credentials and no model inference. Record actual results, not workflow existence.
Paid continuations are a separate explicitly authorized stage.
