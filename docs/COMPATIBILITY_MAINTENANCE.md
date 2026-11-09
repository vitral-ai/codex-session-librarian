# Compatibility maintenance

Accountable reviewer: Manunruks, Open Source & AI Ecosystem Lead at Vitral.
The implementer owns regression fixtures and version pins for each assigned change;
an independent reviewer checks whether public claims match the evidence.
This responsibility does not promise support for every future internal format.

## Verified scope

| CLI / version | Environment | Operations and limits | Evidence |
| --- | --- | --- | --- |
| Codex 0.166.0 | Linux x86_64 | Local library, native transfers/forks; explicit conversion/migration remain experimental | Native load, regression and synthetic continuation evidence |
| Codex 0.167.0 | Linux x86_64 | v0.1.1 candidate: native load/display/import/migration regression paths; conversion remains experimental | 268-test isolated suite on 2026-11-09, no skips; no new model-continuation claim |
| Claude Code 2.1.308 | Linux x86_64 | Basic discovery and native transfer; explicit conversion experimental; advanced library/search not integrated | Localhost request reconstruction and separate synthetic continuation evidence |
| Other CLI versions | Not established | Do not infer support from a successful JSON parse | Record tested or unverified per operation |
| macOS / Windows | Not established in this validation | No support certification from Linux runs | Dedicated tests required before changing claims |

The complete command matrix remains [PROVIDER_MATRIX.md](PROVIDER_MATRIX.md),
checked against `csl_capabilities.py`. The version table does not override
operation/content restrictions, opaque-state limits or account/backend evidence.

## Lightweight review mechanism

Use existing core/media CI plus the manual `Isolated native validation` workflow.
For each release and any change to adapters, native formats, version pins or
capability declarations, the reviewer checks:

1. Exact source SHA, actual installed CLI/runtime/decoder versions and clean inputs.
2. Structural/semantic regressions and negative cases, including F01–F05.
3. Native CLI loading/reconstruction separately from model continuation.
4. Command matrix, README and website against the measured version/operation profile.
5. Result logs including skips/failures, risk owner and next action.

When a new native CLI version is proposed, test its fixed version against existing
fixtures before extending the matrix. Failures first become reproducible drift
reports; do not silently reinterpret unknown records or update public support claims.
Commercial inference is not required for normal CI or format-drift detection.

Periodic review can reuse the same workflow; no remote database, persistent service
or new platform is needed. A timed automation needs explicit scope, cadence and
validity before activation. No indefinite scheduled surveillance is activated by
this document. Existing evidence remains versioned and is not relabeled as fresh.
