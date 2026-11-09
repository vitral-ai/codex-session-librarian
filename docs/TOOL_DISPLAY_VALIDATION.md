# Historical tool display validation (issue #7)

This correction is included in v0.1.1. The v0.1.0 references below identify its
unchanged earlier baseline, not the new patch release.

Base: published `v0.1.0`, commit
`edd05bb20eb145dea6178d548f1363b9516102af`. This fix is a later change; it does
not change the existing tag or claim the released version already includes it.

## Confirmed behavior

The frozen `tool-only` and `tool-errors` Claude fixtures used in the competitive
benchmark are included under `tests/fixtures/benchmark-*-claude.jsonl`. Source
records and markers are synthetic. Their historical commands are never executed.
The prior CSL conversion loads in Codex 0.166.0, but `thread/read` omits its tool
arguments/results. New conversions emit display-only MCP-shaped events under
`csl_imported_history` while preserving native `response_item` model history.

`tests/test_tool_display.py` verifies:

- Both benchmark fixtures: canonical roundtrip equality and unchanged source hashes.
- Completed JSON function/custom-text calls, parallel/reversed results, errors,
  Unicode/escaping, phase preservation and correlation IDs.
- No accumulated projection/model duplication across three canonical conversions
  or repeated same-CLI imports.
- Unknown/incomplete states rejected before destination creation.
- Secret scrub of duplicated display arguments, including arbitrary business
  fields named `id`/`signature`, and valid rebuilt ZIP checksums.
- Real Codex `thread/read`: exact expected tool-item count, markers, call IDs,
  historical-server label and `completed`/`failed` states in three scenarios.

The native probe only initializes the app server and calls `thread/read`; there
is no `turn/start`, model generation, account credential, active MCP server or tool
execution. Network access is disabled by an outer bubblewrap namespace. Imported
source files are hashed/compared before and after. These are visibility checks,
not a new paid model-continuation benchmark.

## Reproduction

On 2026-11-05, the full suite passed **260 tests (260 unique IDs), no skips** in
168.176 seconds using the opt-ins and isolated environment below. This includes
the existing F01–F05 regressions and seven added tool-display tests. One earlier
full run had three errors: the base test interpreter lacked reportlab, and two
subtests left credential-shaped display arguments in a supposedly clean fixture.
The final run uses the decoder venv as the runner and the fixture now clears both
representations; secret scanning was not relaxed. This is scoped evidence, not a
guarantee for other CLI versions or universal conversion fidelity.

Run ordinary regressions with `python3 -m unittest discover -s tests -v`.
Native/media/migration coverage requires Linux, bubblewrap, installed Codex
0.166.0 / Claude Code 2.1.308 Linux executables and the optional decoder venv.
Use the **ELF executables**, not the npm Codex JavaScript wrapper. In a clean
checkout, supply their local paths to this wrapper:

```python
import sys
from pathlib import Path
sys.path.insert(0, 'benchmarks/consolidation')
from sandbox import run

codex_elf = Path('/path/to/native/codex')
claude_elf = Path('/path/to/native/claude')
decoder_venv = Path('/path/to/media-venv')
Path('cli-bin').mkdir(exist_ok=True)
for name in ('codex', 'claude'):
    (Path('cli-bin') / name).touch(exist_ok=True)
Path('media-venv').mkdir(exist_ok=True)
result = run(Path.cwd(), ['/mnt/media-venv/bin/python', '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
    cwd='/mnt', timeout=260,
    extra_env={'PATH': '/mnt/cli-bin:/usr/bin:/bin',
        'CSL_RUN_CODEX_NATIVE_TESTS': '1', 'CSL_RUN_CLAUDE_NATIVE_TESTS': '1',
        'CSL_RUN_MIGRATION_E2E_TESTS': '1', 'CSL_RUN_MEDIA_TESTS': '1',
        'CSL_MEDIA_PYTHON': '/mnt/media-venv/bin/python', 'CSL_MEDIA_SANDBOX': 'required'},
    readonly_binds=[(codex_elf, '/mnt/cli-bin/codex'),
        (claude_elf, '/mnt/cli-bin/claude'), (decoder_venv, '/mnt/media-venv')])
print(result.stdout + result.stderr)
raise SystemExit(result.returncode)
```

The wrapper hides private homes, clears inherited environment and disables the
network. Only supplied CLI binaries and decoder dependencies are mounted back.

## Bounds and renderer adaptation

Codex 0.166.0 silently omits these tool display items when `duration` is absent or
null. A numeric zero makes them visible. Accordingly zero means **unknown duration
required by the renderer**, explicitly recorded in each end-event's provenance
and documented in `CONVERSION.md`; it is not measured tool execution time.

Non-text tool-result blocks use an explicit visible placeholder, while native
content stays preserved. No new canonical schema, guessed tool exit code or active
tool registration is introduced. This applies to canonical-to-Codex conversion,
not all pre-existing native histories or modern tool-item types. The historical
server name is a label, not evidence that a matching MCP server existed.
