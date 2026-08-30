# freqtrade-lab

A small, local-first research workbench for recording Freqtrade strategy lineage, research runs, backtest evidence, and releases.

The repository provides the SQLite schema v1 foundation, a fail-closed single
artifact importer, and a narrow three-scenario bundle importer for Freqtrade
2026.7, a synchronous three-scenario producer, and a local read-only strategy
library. The producer can run one bounded Freqtrade research Candidate; that
technical completion does not prove that any strategy is profitable.

## Quickstart: trusted local Candidate

Use persistent absolute paths outside this Git repository. The Candidate source
must be local code that you selected and reviewed; the acquisition command uses
only the fixed public OKX data endpoints described below.

```bash
FTLAB_FREQTRADE_PYTHON=/absolute/path/to/freqtrade-2026.7-venv/bin/python
FTLAB_FREQTRADE_SOURCE=/absolute/path/to/clean/freqtrade-2026.7
FTLAB_INPUT_ROOT=/absolute/persistent/path/okx-xrp-input
FTLAB_WORKSPACE=/absolute/persistent/path/freqtrade-lab-workspace
FTLAB_CANDIDATE=/absolute/path/to/ReviewedCandidate.py
FTLAB_RESEARCH_SPEC=/absolute/path/to/research-spec.json

PYTHONDONTWRITEBYTECODE=1 "$FTLAB_FREQTRADE_PYTHON" \
  tests/fixtures/freqtrade_2026_7/producer/fetch_okx_public_data.py \
  --output-root "$FTLAB_INPUT_ROOT" \
  --strategy-file "$FTLAB_CANDIDATE" \
  --research-spec "$FTLAB_RESEARCH_SPEC"
```

The input root is new and local-only; do not commit it. Run the complete
three-scenario producer and atomic database import with one research command:

```bash
python3 scripts/run_research_candidate.py \
  --freqtrade-python "$FTLAB_FREQTRADE_PYTHON" \
  --freqtrade-source "$FTLAB_FREQTRADE_SOURCE" \
  --input-root "$FTLAB_INPUT_ROOT" \
  --workspace "$FTLAB_WORKSPACE"
```

On success the producer prints this directly executable page command and the
URL `http://127.0.0.1:8765/`; it does not start a background service:

```bash
python3 scripts/serve_strategy_library.py \
  --database "$FTLAB_WORKSPACE/lab.sqlite" \
  --artifact-root "$FTLAB_WORKSPACE/artifacts" \
  --port 8765
```

The workspace contains the existing schema-v1 SQLite database and unique
per-run directories below `artifacts/`. A missing database is initialized; an
existing database is validated before Freqtrade runs, and an Artifact output is
never replaced. `COMPLETED` and three `SUCCEEDED` executions mean only that the
technical evidence loop completed; they are not a Judge or a profitability,
tradability, or capital-safety claim.

## Scope

Schema v1 contains exactly six business tables:

- `research_profiles`
- `generation_runs`
- `candidates`
- `research_runs`
- `backtest_executions`
- `releases`

The project intentionally starts without an ORM, migration framework, task queue, authentication, or multi-user platform layer.

## Initialize a database

Use a disposable or explicitly chosen path while developing:

```bash
python3 scripts/init_database.py --path /tmp/freqtrade-lab.sqlite
```

The default path is `workspace/lab.sqlite`; `workspace/` is local runtime data and is not tracked by Git.

## Produce one real three-scenario research run

`scripts/run_research_candidate.py` is the user-initiated producer entrypoint.
The preset form above resolves the selected Candidate and fixed data contract
from the existing retained provenance and research spec. It runs exactly
Development, Holdout, and Holdout Stress in that order, using a clean Freqtrade
`2026.7` checkout at commit `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`.
The original fully explicit form remains available for compatibility:

```bash
python3 scripts/run_research_candidate.py \
  --freqtrade-python /path/to/freqtrade-2026.7-venv/bin/python \
  --freqtrade-source /path/to/clean/freqtrade-2026.7 \
  --config /path/to/local-producer-root/config.json \
  --data-dir /path/to/local-producer-root/data/okx \
  --strategy-path /path/to/local-producer-root/strategies \
  --strategy-file /path/to/local-producer-root/strategies/StrategyTestV3Futures.py \
  --strategy StrategyTestV3Futures \
  --research-spec /path/to/local-producer-root/research-spec.json \
  --data-provenance /path/to/local-producer-root/retained-data-provenance.json \
  --market-snapshot /path/to/local-producer-root/market_snapshot.json \
  --leverage-tiers /path/to/local-producer-root/isolated_tiers_snapshot.json \
  --development-timerange 20260801-20260804 \
  --holdout-timerange 20260804-20260807 \
  --stress-fee-multiplier 2 \
  --output-dir /path/to/new-three-scenario-bundle \
  --database /path/to/existing-schema-v1.sqlite
```

In explicit mode, `--output-dir` must not exist and `--database` remains
optional, never inferred, and never initialized. With it, the fully validated bundle is imported as one
`COMPLETED` ResearchRun and three `SUCCEEDED` executions sharing one
`research_run_id`; `verdict`, `scenario_passed`, and runtime return-code/log
fields remain `NULL`. Without it, the command stops after atomically publishing
the manifest, three ZIP/meta/provenance units, and their hashes.

The three final archive stems are `backtest-result-development-01`,
`backtest-result-holdout-02`, and `backtest-result-holdout-stress-03`. Their
numeric suffixes make the ZIP/meta pairs discoverable by the fixed Freqtrade
`2026.7` Backtest history scanner while keeping the three scenarios distinct.

The real runner is fixed to a deny-by-default `/usr/bin/sandbox-exec` profile.
Each scenario receives separate owned `HOME`, `TMPDIR`, and empty `user_data`
directories inside the temporary work root; no external user-data directory is
read or written. Before any Candidate import, a separate deny-by-default Git
sandbox permits only the exact CommandLineTools Git executable to inspect the
supplied checkout. The producer requires the fixed clean tag/commit, exports
only tracked `freqtrade/` bytes with `git archive`, disables Git replacement
objects, verifies the fixed official tree OID, rejects special archive members,
and computes a deterministic source-tree SHA-256. Each scenario can
read only that exported package snapshot, not `.git`, ignored files, or other
checkout content; the runner verifies the tree hash before imports and again
after the backtest. Package/dependency versions and official Freqtrade method
identities are checked inside the scenario sandbox before the Candidate is
imported. The runner also rejects additional or unknown config fields, dynamic
pairlists, credentials, a strategy directory containing anything except the
SHA-bound selected strategy, input symlinks, mismatched local-data hashes, and
overlapping scenario contracts. Process spawning is not permitted, every
scenario has a fixed one-hour timeout, Python-level engine output is bounded,
and native ZIP member/count/expansion limits are checked before decompression.
Each scenario receives an owned temporary data view whose stop is exclusive,
so the Development end candle cannot become the first Holdout candle.

Candidate code has an explicit integrity trust boundary: the selected strategy
runs in the same Python process as Freqtrade and the adapter. The sandbox limits
its readable/writable paths and denies network access, but it does not prove
result integrity against a deliberately adversarial strategy that monkeypatches
the running engine. Use this CLI only with a SHA-bound strategy that you have
reviewed; each produced provenance unit records that limitation. The tracked
GPL fixture strategy satisfies that reviewed-input boundary for integration
testing only.

Known scenario, validation, sanitization, and database failures publish no
partial ResearchRun, and temporary raw results are removed. For an asynchronous
interrupt around SQLite commit, the producer compares database row identities:
it removes the bundle only when the database is visibly unchanged; if the
database changed or cannot be read, it reports the outcome as unknown and keeps
the validated bundle so a committed artifact locator cannot be broken. The
final bundle uses an exclusive atomic rename and never replaces a concurrently
created output path. Every artifact provenance binds the exact producer and
runner file bytes as well as the exported Freqtrade source tree. The runtime
currently requires macOS `/usr/bin/sandbox-exec` and the exact CommandLineTools
Git executable.

### Local-only OKX input fallback

`PORTABLE_RETAINED_FIXTURE=BLOCKED_LICENSE`: this public repository does not
redistribute OKX OHLCV, mark, funding, market, or leverage-tier data. The
tracked producer fixture therefore contains only sanitized inputs, exact
metadata/hash receipts, and a manual acquisition helper. This is based on the
redistribution restriction in the
[OKX API Agreement §9.4](https://www.okx.com/en-gb/help/okx-api-agreement), not
on a claim that public endpoints are inaccessible.

From an exact clean Freqtrade environment, a user may deliberately create a
new local-only producer root outside the repository. Supplying the optional
Candidate pair selects reviewed local code instead of the tracked integration
fixture, rewrites only the copied config strategy name, and binds all selected
bytes into the existing retained provenance:

```bash
PYTHONDONTWRITEBYTECODE=1 /path/to/freqtrade-2026.7-venv/bin/python \
  tests/fixtures/freqtrade_2026_7/producer/fetch_okx_public_data.py \
  --output-root /path/to/new-local-only-producer-root \
  --strategy-file /path/to/ReviewedCandidate.py \
  --research-spec /path/to/research-spec.json
```

This command is networked; tests exercise its safety functions without making
network requests. It has no credential inputs, disables environment proxy and
`.netrc` discovery, rejects redirects, blocks non-allowlisted requests before
I/O, records response hashes but not raw bodies, validates exact
Python/dependency versions plus the clean Freqtrade tag/commit using the exact
CommandLineTools Git executable, and writes a matching local
`retained-data-provenance.json`. Review its printed receipt/provenance hashes
before using the root above. Future public responses may differ from the Issue
#9 verification hashes; the output remains local-only and must not be committed.
Exact reviewed evidence is documented in
[`tests/fixtures/freqtrade_2026_7/producer/PROVENANCE.md`](tests/fixtures/freqtrade_2026_7/producer/PROVENANCE.md).

## Import one verified backtest artifact

Issue #2 supports only the frozen Freqtrade `2026.7` format verified at commit
`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`. The three-member ZIP and its
same-stem `.meta.json` and `.provenance.json` must already be inside a
controlled artifact root, and the target `backtest_executions` row must already
exist:

```bash
python3 scripts/import_backtest_artifact.py \
  --database /path/to/lab.sqlite \
  --artifact-root /path/to/controlled-artifacts \
  --archive backtest-result-YYYY-MM-DD_HH-MM-SS.zip \
  --research-run-id <existing-research-run-id> \
  --scenario DEVELOPMENT \
  --strategy StrategyTestV3Futures \
  --freqtrade-version 2026.7 \
  --provenance-sha256 132b65ebdf236940a2da645ec1ef26c1b23aedc5287416ad021b725da0648d3b
```

The importer does not run Freqtrade, infer a version, create an execution, or
evaluate whether a scenario passed. It verifies provenance and every ZIP member
hash against the caller-provided trusted provenance receipt, then binds the
selected `report.strategy[...]` result, sanitized config, and strategy source
to the existing Candidate, ResearchProfile, and execution. The same-stem meta
must exist, parse as strict JSON, and match its anchored hash; the importer does
not reinterpret its business fields. It validates the structured provenance
`version`, `tag`, and `commit`, not the embedded version-command text. The
supported boundary is deliberately exact: public unauthenticated `www.okx.com`
evidence, `okx/futures/isolated`, one or more nonzero trades, `5m`, and the
pinned Freqtrade version/commit.

The existing Candidate class and source SHA-256, profile pair set and execution
timerange must match. Each reported trade fee must equal the sanitized config's
configured fee; the execution must also satisfy
`fee_rate = profile.taker_fee_rate * fee_multiplier`. Non-stress scenarios use
multiplier `1.0`; `HOLDOUT_STRESS` uses the profile stress multiplier, which may
also be `1.0` under schema v1. The timerange/timeframe/fee identity must still
select exactly one scenario, so an ambiguous same-period artifact fails closed.

Only clean `PENDING` executions under a `RUNNING`, no-verdict research run at
the matching `*_BACKTEST` stage are accepted. `RUNNING`, `FAILED`, and other
non-pending executions remain immutable. A successful import sets
artifact-backed metrics and `status=SUCCEEDED`, but leaves `return_code`,
stdout/stderr paths, `finished_at`, and `scenario_passed` as `NULL`: the frozen
artifact does not prove those values. Here `SUCCEEDED` means the artifact was
accepted into the existing execution, not that the strategy passed research
criteria or is profitable.

The fixture fee is a configured parser-fixture assumption, not an observed or
public OKX account fee rate. The importer validates the frozen artifact before
opening a transaction and either updates the one existing row atomically or
leaves all six business tables unchanged. Artifact acquisition, offline
generation, sanitization, license, and raw/final hashes are documented in
[`tests/fixtures/freqtrade_2026_7/PROVENANCE.md`](tests/fixtures/freqtrade_2026_7/PROVENANCE.md).
The product parser checks the externally anchored provenance hash, the shallow
public-OKX source declaration, and artifact/contract hash bindings. It does not
re-run the one-time acquisition, offline-generation, sanitization, or license
audit recorded in the fixture evidence, and the receipt is not a digital
signature or independent proof of market truth.

## Import one complete research bundle

Issue #6 adds the strict assembler/importer for a complete read-only research
summary. A strict manifest references exactly one Development, one Holdout, and
one Holdout Stress artifact from the same controlled directory:

```bash
python3 scripts/import_research_bundle.py \
  --database /path/to/initialized-lab.sqlite \
  --bundle-root /path/to/controlled-three-scenario-bundle \
  --manifest research-bundle-v1.json
```

The command validates the manifest, all three artifacts, and their shared
strategy/profile contract before opening a database transaction. It then
creates or exactly reuses the named ResearchProfile and source-identical
Candidate, creates one ResearchRun and three `SUCCEEDED` executions, and only
then finalizes the run as `COMPLETED`. Any validation, collision, or database
failure rolls the transaction back. It does not initialize a missing database.
Running the same valid bundle again deliberately records a new ResearchRun and
three new executions while reusing the exact Profile and Candidate; the command
is not an idempotent synchronization tool.

`COMPLETED` means that the three artifact identities were assembled, not that
the strategy passed a Judge. The ResearchRun `verdict` and each execution's
`scenario_passed`, runtime return code, stdout/stderr paths, and execution
timestamps remain `NULL`. The ingestion timestamp on the GenerationRun and
ResearchRun records this local assembly lifecycle, not when Freqtrade executed
the backtests. Because the frozen ZIP is the only retained config/source
container, `config_path` and `strategy_path` are explicit `zip+file://...!/`
member locators rather than fictional standalone paths. `command_json` is `[]`
because the artifact does not attest a replayable command line.

The tracked technical Gate manifest is
[`tests/fixtures/freqtrade_2026_7/research-bundle-v1.json`](tests/fixtures/freqtrade_2026_7/research-bundle-v1.json).
Its public-data acquisition boundary, fixed version/commit, scenario mapping,
fee assumptions, and exact artifact hashes are documented in
[`BUNDLE_PROVENANCE.md`](tests/fixtures/freqtrade_2026_7/BUNDLE_PROVENANCE.md).
`StrategyTestV3Futures` is an upstream internal test strategy; its fixture PnL
is integration evidence only and must not be treated as economic validation or
trading advice.

## View the local strategy library

Start the one-process, server-rendered read-only UI against an explicitly chosen
schema-v1 database:

```bash
python3 scripts/serve_strategy_library.py \
  --database /path/to/lab.sqlite \
  --artifact-root /path/to/controlled/backtest-artifacts \
  --port 8765
```

Open `http://127.0.0.1:8765/`. The corresponding JSON list is available at
`http://127.0.0.1:8765/api/strategies`. The server is fixed to loopback and has
no `--host` option; it is a personal local view, not an authenticated network
service. It opens SQLite with `mode=ro` and `query_only=ON`, refuses to create a
missing database, and validates the schema before listening. It does not modify
the main database or business records. SQLite may still create or manage its
normal `-wal`/`-shm` sidecar files when the database uses WAL mode, so its
directory must remain writable; this UI does not claim filesystem-level
immutability.

`--artifact-root` is the only directory from which evidence ZIP files may be
downloaded. It may be omitted when only the list and detail views are needed;
downloads then remain visibly unavailable. When configured, the server holds a
descriptor for that exact directory, opens each path component without
following symlinks, requires an ordinary `.zip` no larger than 4 MiB, and
verifies both ZIP structure and the imported `archive_sha256`. It never returns
the stored host path or derives the download filename from it.

Every card is scoped to one Research Profile. A unique default or the only
Profile is selected automatically. When several Profiles exist without a
default, the page asks for a selection and the API returns `409` until an exact
`profile_id` is supplied; it never combines status, summaries, or counts across
Profiles.

The current status and latest usable summary have separate meanings. A newer
`RUNNING`, failed, rejected, or incomplete ResearchRun remains the current
status but does not hide an older complete three-scenario summary. When those
two Runs differ, the card explicitly labels the metrics as a non-current summary
and shows its completion time. A usable
summary requires Development, Holdout, and Holdout Stress executions from the
same completed ResearchRun, all `SUCCEEDED`, with every card metric present.
The page shows only Holdout return/drawdown/PF/trades, Development return,
Stress return, and completed/passed counts. Passed means
`status=COMPLETED AND verdict=PASSED`; `NULL` is never displayed as a numeric
zero. Freqtrade's `profit_factor=0.0` with zero losses is labeled “无亏损样本 / 不可直接解释” instead of ordinary PF `0.00`.

The detail link carries the exact `profile_id`, `candidate_id`, and
`research_run_id` represented by the card. The detail page never silently
switches to a newer Run: it reads only that Run's fixed Development, Holdout,
and Holdout Stress slots, marks missing slots and metrics as `UNKNOWN`, and
shows newer or failed/interrupted Runs separately in history. Expanded metrics
are limited to the typed database columns plus explicit wins/draws/losses from
`metrics_json`; it does not expose commands, stdout/stderr, runtime directories,
or database artifact paths.

An active Release badge means only that the displayed summary Run has an
unarchived Release. Neither that badge nor a completed backtest summary proves
profitability, trading suitability, or fund safety.

### Optional FreqUI entry

The detail page can optionally open a real local FreqUI general Backtest page.
Start Freqtrade `2026.7` in `webserver` mode with FreqUI installed, then start
the strategy library with both optional settings:

```bash
python3 scripts/serve_strategy_library.py \
  --database /path/to/lab.sqlite \
  --artifact-root /path/to/frozen-artifacts \
  --frequi-base-url http://127.0.0.1:8080 \
  --frequi-results-root /path/to/disposable/user_data/backtest_results \
  --port 8765
```

The two FreqUI flags are a pair. The URL accepts only the exact numeric
loopback origin `http://127.0.0.1:<port>`. The results directory must already
exist and must be separate from, not above, and not below the frozen Artifact
root. This matters because FreqUI can rename or delete history results. Never
point FreqUI at the canonical/frozen evidence directory.

The project deliberately has no synchronization service. For a result that you
want to inspect, make a one-time ordinary-file copy of its native ZIP and the
same-stem `.meta.json` directly into that Freqtrade instance's
`user_data/backtest_results`. Do not use a symlink or hardlink, and do not copy
the same-stem external JSON. The strategy library stays read-only and checks
that both disposable copies match the imported SHA-256 evidence before it
shows an active link.

The link always opens only `<base>/backtest`. FreqUI `3.1.1` has no supported
single-result deep link, so the detail page shows the exact filename and
strategy and asks you to choose them manually under **Load Results**. The Lab
does not read or store a FreqUI username, password, or token. Its daily Gate is
limited to public loopback `ping`, installed UI version, the HTML entry page,
and local copy identity; the authenticated history/result check is confined to
the one-time sanitized integration smoke recorded in
[`docs/frequi-integration-smoke.md`](docs/frequi-integration-smoke.md).

With either flag missing, an unsafe directory, an unreachable Webserver, no
installed UI, or a missing/mismatched ZIP/meta pair, startup or the scenario
entry fails closed with a visible reason. The normal strategy library remains
usable when both FreqUI flags are omitted.

## Run tests

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --with pytest \
  python -m pytest -q -p no:cacheprovider
```

Tests use temporary databases. Do not use a real research database or commit
generated SQLite files, logs, credentials, or runtime backtest artifacts. Only
small, sanitized fixtures with frozen provenance and reviewed hashes belong in
the repository.

## Delivery order

Development proceeds in small, dependent slices:

1. Parse one verified, sanitized Freqtrade backtest artifact into the existing schema.
2. Assemble one real, complete three-scenario ResearchRun atomically.
3. Show the latest honest three-scenario summary in a local strategy library.
4. Add strategy details, research history, and restricted artifact download.
5. Optionally open the general FreqUI backtest page when a real loopback instance is available.
