# Changelog

## Unreleased

No changes recorded after the v0.2.0 candidate. Publication is established by its
GitHub Release/tag and exact selected SHA, not this file alone.

## 0.2.0 — 2026-11-10

Normal release preparation; the **backup feature is experimental**. F0–F3 are
included; F4 scheduling, F5 retention/GC and new human recovery pilots are not.
Existing v0.1.0/v0.1.1 tags, notes and participant versions remain unchanged.

- Add Linux/Codex manual encrypted backups with exact native and explicit portable
  profiles, bounded immutable age containers and encrypted detailed catalogs.
  Archives are included; agent forks are opt-in. Metadata-only native states are
  preserved/quarantined without invented messages. Local secret policy defaults
  to stop; retain requires explicit acceptance and scrub requires portable.
- Add conversation/version-key incrementals with explicit logical heads, separate
  complete/partial pointers, honest stale/missing-local coverage and verification
  debt. No deletion propagation, mtime-only reuse or automatic repacking.
- Add durable encrypted plans, stable uncertain-write adoption, distributed resume,
  multiple source identities and fenced execution generations. Restore verifies
  selected bytes before installation and retains per-member receipts/conflicts.
- Add reviewed future-only public-recipient rotation, private local epoch maps,
  plan/config/producer/generation binding and crash reconciliation. Old checkpoints
  retain their key dependencies; no historical re-encryption or revocation claim.
- Harden exclusive capture/age/download destinations and ZIP preflight/streaming;
  bound URL-password scanning on long non-URL tokens (detector rules2).
- Require externally installed optional pinned age1.3.2 and explicit operational/
  external recovery recipients. Synthetic manual stdin/FD recovery is tested;
  positive keyring/headless operation remains unvalidated. No timer is installed.

Phase evidence and release fixed-SHA validation are documented in `docs/BACKUP.md`,
F0–F3 technical reports and `RELEASE.md`. Synthetic/local mocks, real-age tests and
bounded live backend evidence have distinct scopes; none establishes universal
native/model continuity, WORM availability or production custody.

## 0.1.1 — 2026-11-09

Release readiness: 268-test runtime validation, plus exact publication commit CI,
clean tag installation and synthetic demonstration recorded in GitHub Release.
v0.1.0 remains unchanged. Existing human pilot stays pinned to v0.1.0 unless
its study version is explicitly changed; do not mix participant versions.

- Index readable function/custom tool results and include them in default recall,
  with historical call IDs/source lines and matching excerpts in long results.
  Refresh older cached indexes once without losing annotations. Keep derived
  SQLite data/sidecars private; do not execute historical calls or decode opaque
  content. This correction is not included in v0.1.0.

- Project supported completed historical tool calls/results into Codex 0.166.0's
  visible history during canonical conversion, with explicit
  `csl_imported_history` labeling, preserved correlation/errors, and documented
  unknown-duration display placeholders. Native model history remains unchanged.
- Review/scrub duplicated historical display arguments as business data so native
  metadata exclusions cannot leave sensitive `id`/`signature` values behind.
- Add frozen benchmark regressions, repeated-import/roundtrip checks and isolated
  native visibility assertions. This correction is not in the published v0.1.0 tag.

## 0.1.0 — Published 2026-11-05

Published as tag `v0.1.0` at `edd05bb20eb145dea6178d548f1363b9516102af`;
253-test runtime validation record. The initial license/secret-review PR was merged on November 4;
consolidation PR #6 was merged on November 5 at
`4c7dee029a4525491307030998b79baa0b25a7e0`. Publication tags and dates are recorded
in [GitHub Releases](https://github.com/vitral-ai/codex-session-librarian/releases),
not inferred from this heading. Publication must target the exact selected, verified commit.

- Scope secret-scan identity exclusions to native metadata instead of arbitrary
  tool arguments, and parse embedded JSON arguments before sanitizing them.
- Reject user text with reserved native policy prefixes when conversion cannot
  preserve it without reclassifying history; keep historical policy quarantined.
- Verify migration source identities against release metadata and package manifests,
  including cached receives.
- Publish imported histories through private staging and exclusive atomic links,
  so interrupted copies cannot expose partial native JSONL. Retain and report
  already completed imports after a later batch failure.
- Add a manual, model-free native-validation workflow with fixed CLI versions,
  explicit migration opt-in and required media sandboxing.

- Clarify batch-upload completion: suppress per-session recipient instructions
  and print one whole-migration restore command with the completed session count
  and current-folder guidance, without a placeholder project path.

- Explicit `--repair-legacy-compaction` recovery for old Codex portable copies
  with one orphaned final summary annotation. Pending migration exports can
  recover without resending completed shares; source files and readable turns
  remain intact, and missing hidden context is explicitly labeled.

- Refresh Codex's native resume-picker metadata after import/receive and once per
  migration restore attempt. Add `csl index --native` for already-imported sessions
  that open by UUID but are absent from a running picker's database-only view.
  No history rewrite, UUID changes, direct native DB edits or inference.

- Codex batch migration: `migrate upload`, `download` and confirmation-gated
  archival cleanup, reusing the existing private share/receive exchange.
- Resumable uploads, idempotent downloads and source checksum guards; normal
  interactive sessions are selected without including archives or agent forks.
- Stable recency pagination prevents timestamp-tied sessions being skipped;
  identical already-published migration indexes recover from lost responses.
- Added 12 isolated subprocess migration scenarios, including 125-session
  restore/cleanup and a cold 257-session listing. See
  [migration validation](docs/MIGRATION_VALIDATION.md).

## Initial licensed preparation — 2026-11-02 (historical)

Prepared 2026-11-02. Publication and tag are pending until the release commit is
verified and the corresponding GitHub Release exists. This file is not proof of
publication. Native transcript formats and cross-CLI conversion remain experimental.

### Included

- Apache-2.0 license with Vitral attribution and a distinct CLI `--version`.
- Codex local library: lexical search, evidence-oriented recall, inspection,
  native working forks and archived clones.
- Native Codex and Claude Code ZIP/private-exchange handoffs. Imports create new
  local identities; credentials, project files and installed tools are not copied.
- Explicit canonical-v2 conversion of supported text, completed tools, references,
  embedded images and PDFs. Optional media decoding stays outside the core CLI.
- Local export/share secret review: keep, scrub or cancel for each detected value;
  `--allow-secrets` and `--scrub-secrets` are explicit non-interactive alternatives.
  Scrub edits the output copy, preserving source files and rebuilding checksums.
- Fixed loss of assistant tool-call phase in Claude/canonical → Codex → Claude.
- Reproducible synthetic demo and recorded bounded live validation.

### Verification and limits

See [compatibility evidence](docs/COMPATIBILITY_VALIDATION.md),
[demo](demo/README.md) and the [provider matrix](docs/PROVIDER_MATRIX.md).
Do not infer universal context recovery, compatibility with future CLI versions,
Claude library/search parity, or safe-to-share status from a successful transfer.
Secret scanning is partial and does not redact opaque/binary attachments.

The release regression suite runs in CI on Python 3.11 and 3.13, with separate
core/media jobs. Native localhost loader checks and explicitly paid synthetic
continuations provide separate evidence; CI alone does not establish live recall.
