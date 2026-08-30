# freqtrade-lab

A small, local-first research workbench for recording Freqtrade strategy lineage, research runs, backtest evidence, and releases.

The repository provides the SQLite schema v1 foundation and one fail-closed
Freqtrade 2026.7 artifact importer. It does not run Freqtrade, expose a web UI,
or prove that any strategy is profitable.

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

## Run tests

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --with pytest \
  python -m pytest -q -p no:cacheprovider
```

Tests use temporary databases. Do not use a real research database or commit generated SQLite files, logs, credentials, or backtest artifacts.

## Delivery order

Development proceeds in small, dependent slices:

1. Parse one verified, sanitized Freqtrade backtest artifact into the existing schema.
2. Show the latest honest three-scenario summary in a local strategy library.
3. Add strategy details, research history, and restricted artifact download.
4. Optionally open the general FreqUI backtest page when a real loopback instance is available.
