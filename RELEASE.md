# Release operation and published state

## Version records

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
