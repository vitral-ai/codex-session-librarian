# Historical tool-result retrieval

Correction included in v0.1.1, based on main
`3a6dfe42b9bc7b8c715ed22096a21a9306303bf0`; **not in published v0.1.0**.
Code and regression-test identity is recorded by the containing PR/commit.

The previous parser extracted selected commit facts from function results but
did not index arbitrary readable result text. Default recall also restricted
matches to messages. Preserve and retrieve are distinct contracts: retained
facts could therefore be absent from default recall without historical loss.

## Behavior

- Index string results and text/input_text/output_text blocks from native
  function_call_output and custom_tool_call_output as tool_result evidence.
- Include that type by default in recall, below assistant-final weighting;
  preserve explicit turns-only and type filters. Show source line/call ID and an
  excerpt around a matching query term, including near the end of long output.
- Do not execute historical calls or treat result text as fresh authorization.
  Source files remain unchanged. Non-text/opaque objects are not stringified,
  fetched or decoded. Missing/truncated result rows do not invent evidence.
- On the next `csl index`, parser revision triggers one refresh of old cached
  files even if size/mtime did not change. Upsert preserves durable annotations;
  subsequent runs skip unchanged current entries without duplicate hits.
- Derived indexes store readable private history, not sanitized sharing data.
  Database and SQLite sidecars are owner-only. Export secret review remains a
  separate operation; no claim of universal secret detection is introduced.

## Reproduction

```sh
python3 -m unittest discover -s tests -p test_recall_tool_results.py -v
csl index
csl recall remembered-result-clue
csl recall remembered-result-clue --type tool_result
```

Six focused tests cover function/custom errors, text/media separation, source
hash, line/correlation, filters, an old index without revision, annotation
preservation, repeat indexing, a multi-megabyte output with an end marker,
truncation, no historical execution and private derived files.

Full local suite: 268 tests passed with no omissions in181.189seconds, all native
Codex/Claude, migration and media opt-ins enabled with required media sandbox;
outer bubblewrap network disabled. Tested Linux executables: Codex0.166.0,
ClaudeCode2.1.308. Six focused tests were repeated after neutral synthetic-label
and help-text adjustments. Ordinary CI and native opt-in coverage remain distinct.

A separate frozen synthetic pilot fixture was compared without modifying its
bytes: released0.1.0 did not show its tool-only fact in default recall; this
correction does. The fixture and private answer key are not published here.
This does not change the fixed-version human pilot or establish human usefulness.

Indexing full readable outputs increases local derived-data storage and search
work. The large regression is synthetic (about2.25MB), not a performance claim
for all archives. This adds no embeddings, model calls, remote service or new
agent adapter. It is a Codex library-index change, not Claude advanced search.
