# CSL Backup F0 laboratory

Experimental, synthetic-only prerequisites for spec 0.2 + clarifications 0.2.1.
Not a backup implementation, supported CLI, encrypted recovery product or evidence
that F1/E1 has passed. Based on official v0.1.1
`318332bfe73c5b585651b39b9bd258927e65df22`. No secret-review branch changes.

## Reproduction

```sh
python3 -m unittest discover -s tests -p test_backup_f0.py -v
python3 -m experiments.backup_f0.run --out .local/backup-evidence/f0/NEW-RUN \
  --native --age-dir /EXPLICIT/ISOLATED/age-v1.3.2
```

The runner refuses an existing output directory and generates its own synthetic
histories. No source history selector or general plaintext-backup switch exists.
`--native` uses bubblewrap with networking disabled and synthetic A hidden for
read-only Codex `thread/read`; no turn/start or model requests. age trial uses
fresh synthetic identities in memory/FD only, never private material in evidence.
No installation is performed; missing dependencies are errors.

`contracts.py` emits ten draft JSON schemas and positive/negative vector
definitions. It implements only the schema subset used by these definitions;
it is not a general JSON Schema validator. Catalog cross-field checks are Python
invariants in addition to structural schemas. Publication/version identities are
UTF-8 sorted-key compact JSON with integers only (`csl-json-v1`), no Unicode
normalization. Namespace is fixed in source and a golden UUID/hash vector is tested.
Schemas, namespace and limits remain candidates until the F0 review accepts them.

The object descriptor excludes native UUIDs, titles, paths, plaintext hashes and
secret values. Detailed catalogs are encrypted in the proposed product, not exposed
through this synthetic experiment. Later evidence events are local, observer- and
asset-bound; catalogs retain immutable as-of evidence. Restore-intent is local and
reserves UUID/destination/hash before publication; the actual restore engine is F1.

`control.py` uses a local bare Git repository to exercise compare-and-swap and
non-force advances, including paused A/new epoch B/resumed A. It is not proof of
server clocks, repo rules or live GitHub lease expiration. `backend.py` tests lost
responses, conflicting objects, incomplete assets and cold catalog resolution in
a synthetic directory. No destructive remote operation exists.

## Live experiment: do not rerun blindly

`remote.py` is pinned to the authorized private synthetic repository
`manunruks/csl-backup-validation-20261109`, repo ID `1452103289`. It refuses a
nonempty release list. It uses only `gh-manunruks`, does not configure login/helper,
and does not delete anything. Requests use `X-GitHub-Api-Version: 2026-03-10`.

Its planned mutations are three synthetic releases, two tiny plaintext fixture
assets and a synthetic control branch. An initial sentinel deliberately establishes
the synthetic repository's latest; subsequent object/catalog releases explicitly
send `make_latest: "false"` and must not replace that sentinel. These are not CSL
software releases. Check current inventory with the coordinator before ANY retry;
a failed command may already have created remote resources.

Budget for ALL F0 experiments combined: five releases, ten assets, ten MiB. The
plaintext fixtures are controlled synthetic labels only, not a mode usable for
real data. Live outcomes and exact IDs are in the separate evidence directory.
The initial cold test uses fresh variables discovered from listing, not isolated
HOME B or a product restore; those results must not be described as E1.

`cold.py` adds a separate read-only B process with fresh HOME/CODEX_HOME, all F0 A
state hidden by tmpfs, and an externally authorized identity validated in memory
by the coordinator's private helper. The credential enters B only via stdin;
it is not put in argv, env, auth files or evidence. B uses read-only HTTPS requests
bound to the exact synthetic repo and does not forward authorization on asset
redirects. The outcome is cold synthetic retrieval, still not encrypted E1.

## Scale assumptions and limits

`scale.py` enumerates 729 combinations of session count, horizon, mean size,
changed fraction, interval and daily growth. Seed 20261109 shuffles the enumeration;
aggregate outcomes use explicit formulas, not observed user behavior.

- Inventory fixed at N; initial run uploads N, later runs ceil(N*fraction).
- Whole-session uploads; no compression or binary deltas assumed.
- Daily mean bytes grow by `(1+growth)**day`; uniform per-session size assumption.
- One release/object + one release/checkpoint, two assets/release (data + descriptor).
- New objects/catalogs downloaded in full; reuse gets a lightweight query.
- Full verification of current heads and of retained history at 30-day boundaries
  are separate size upper estimates, not the same scope.
- Control minimum assumes acquire + batched durable intent + commit. Sensitivities
  include one intent commit/object and 60s renewals for hour-long runs; four REST
  writes per blob/tree/commit/ref transition. A per-run estimate omits unbounded
  retries and is not an API upper bound. Primary budget also includes read calls.
- Wrapper `gh-manunruks` performs an identity lookup per invocation: measured here,
  not included in the generic adapter estimate. A future adapter must count it or
  avoid a subprocess per logical call without changing authorized identity.
- Listing assumes 100 releases/page, 2048B metadata/release and 2 requests/second
  ONLY as sensitivities. Actual memory/time and provider behavior must be measured.
- Upload time sensitivity assumes 10MiB/s, excludes latency and verification.
- GC scan/page counts and grouping-by-100 sensitivity do not implement retention,
  authorize deletion, or adopt a redesign.

`container_comparison()` additionally quantifies actual packing into bounded
64MiB containers, reducing both asset and release writes. Logical version keys,
UUIDs and per-session receipts would remain individual; an encrypted catalog would
need container/member/hash bindings. It was initially an offline alternative;
Manunruks then authorized the bounded prototype and ADR002/contract0.2.2. It is not
yet a supported backup implementation. Partial restore may decrypt 64x the requested
member bytes; retention can pin the whole container. Unchanged members retain old
references instead of forcing repack/reupload. Oversize individual members require
the dedicated `oversized_single` layout with final ciphertext <=256MiB, or explicit
failure beyond that. Normal64MiB is also a final-ciphertext cap, not raw member sum.
Actual ciphertext is checked before any upload; tests cover +/-1 byte boundaries.

`encrypted_pack.py` used the last two authorized releases and four additional
assets to publish a synthetic two-member encrypted container, opaque descriptors
and encrypted catalog. Cold B receives only external recovery key and authorized
transport credential over stdin. It verifies all member/container bindings after
one download, with A hidden. Inventory is now5 releases/6 assets: no further
mutation/retry is authorized within the original release budget. This is F0, not E1.

These figures are projections, not a remote year-long benchmark or unlimited
viability claim. Content-write bursts and first-run volume matter independently
of annual averages. Streaming/indexed discovery may reduce listing costs but has
not been implemented or measured by this experiment.

## Primary references checked 2026-11-09

- [Releases REST](https://docs.github.com/en/rest/releases/releases): pinned create
  field is string `make_latest`, including `"false"`; list pagination is bounded.
- [Git refs REST](https://docs.github.com/en/rest/git/refs): `force:false` enforces
  fast-forward, not a built-in lease or expected-old-SHA API parameter.
- [API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions):
  explicitly pin the request header and record the selected version.
- [Rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api):
  distinguish primary budget, secondary point/concurrency limits and generally
  80 content-generating requests/minute, 500/hour; endpoint-specific or undisclosed
  limits may be stricter. Live headers are authoritative for effective quota.
- [Release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases):
  assets under 2GiB, up to 1000 assets/release. This is not a backup durability SLA.
- [Immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases):
  provider immutability changes asset/tag mutation behavior; client no-overwrite
  alone does not make the repository WORM. No settings were changed in F0.
- [age v1.3.2](https://github.com/FiloSottile/age/releases/tag/v1.3.2) and
  [format](https://age-encryption.org/v1): maintained CLI, X25519 recipients, opaque
  encrypted payload. Isolated binary supplied by the coordinator; archive SHA256
  `cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10` was verified
  by him against the official release API; signatures/attestations not verified.
