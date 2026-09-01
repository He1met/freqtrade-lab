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

## Local Research Console: bounded Codex, Search, Development, and one-shot Holdout

The Research Console keeps the Strategy Library routes on the same loopback
server and adds a small page at `http://127.0.0.1:8765/console`. One fixed
`CHECK_DATA` child, one bounded Codex Candidate generation, either Search
round, one approved Candidate's fixed `DEVELOPMENT` backtest, or its explicitly
authorized Holdout continuation can occupy the same single slot; a concurrent
start is rejected. For generation, the browser may submit
only a Profile id, an optional same-Profile approved parent id, a bounded idea,
an optional strategy family, and an optional expected failure mode. It cannot
supply an executable, working directory, arguments, prompt template, model,
environment, command, or output path.

Prepare one private runtime directory outside this repository, then start the
single service with an existing schema-v1 database, frozen Pilot root, and an
optional Search-only campaign root. Before the first Search action, the Search
root must be outside Git, owned exclusively by this service, mode `0700`, and
contain only its already-prepared `acquisition/` directory. The browser cannot
submit, replace, or discover this path.

```bash
mkdir -p /absolute/private/path/freqtrade-lab-console-runtime
chmod 700 /absolute/private/path/freqtrade-lab-console-runtime
test -d /absolute/private/path/search-campaign/acquisition
chmod 700 /absolute/private/path/search-campaign

python3 scripts/serve_research_console.py \
  --database /absolute/private/path/freqtrade-lab-workspace/lab.sqlite \
  --runtime-root /absolute/private/path/freqtrade-lab-console-runtime \
  --pilot-root /absolute/private/path/frozen-pilot \
  --search-root /absolute/private/path/search-campaign \
  --freqtrade-python /absolute/private/path/freqtrade-2026.7-venv/bin/python \
  --freqtrade-source /absolute/private/path/clean-freqtrade-2026.7 \
  --artifact-root /absolute/private/path/freqtrade-lab-workspace/artifacts \
  --port 8765
```

`--search-root` is optional. When it is absent, stale, invalid, or not an exact
frozen 30-day `freqtrade-lab-retained-search-data-v2` input, only the Search
card reports `BLOCKED_DATA`; the Console, Codex, and Development capabilities
remain available according to their own preflight checks. A completed root
stays read-only at its verified terminal state and cannot be rerun. A valid
fresh root carries exactly one two-round campaign. Round 1 accepts
one to three approved mechanism seeds and may select a negative-return parent.
The page then locks that parent into the existing Codex card: the user generates
one child at a time, reviews its source, and explicitly approves or rejects it.
Round 2 accepts one to three approved single-factor children. Both rounds share
one fixed budget of at most six attempts; there is no third round, automatic
child loop, Hyperopt, or threshold rescue.

Search completion freezes either a finalist or a no-finalist terminal result;
neither result proves profitability, robustness, or tradability. Selecting a
finalist for Development changes only the page selection. Development starts
only after a separate user click, and Search never automatically opens
Development, Holdout, Holdout Stress, Release, or trading. Every Search action
is read-only across all six schema-v1 business tables and creates no
`ResearchRun`, execution, or Release. The explicitly requested Codex generation
between rounds retains its existing, separate `generation_runs`/`candidates`
write contract.

Preflight always probes the public numeric-loopback origin configured by
`--webserver-base-url` (default `http://127.0.0.1:8080`). A stopped service is
shown as `UNAVAILABLE`, never `READY`. The optional `--frequi-base-url` and
`--frequi-results-root` pair is separate: it enables the existing Strategy
Library detail links under the same safety rules as before. Preflight only runs
local capability checks; it does not invoke a Codex model, read credentials,
download data, run Freqtrade research, open Holdout, or create a Release. A
`SUCCEEDED` CHECK_DATA status only means the frozen data contract passed its
existing technical check. Codex generation uses the startup-frozen binary and
optional `--codex-model`, an isolated Git-external workspace, a fixed
read-only/no-tool CLI contract, controlled stdin, strict JSON/AST validation,
and one PENDING Candidate. `APPROVE` only makes that Candidate visible to the
Strategy Library; it does not run Freqtrade, create a ResearchRun, set a
verdict, prove safety or profitability, or authorize trading. PENDING and
REJECTED Candidates stay out of the Strategy Library.

The Development action accepts exactly one browser field: `candidate_id`. At
the same `BEGIN IMMEDIATE` consumption boundary it rebinds the current approved
source SHA, completed generation report, frozen Profile/request lineage, and
the versioned `BOUNDED_CAUSAL_STRATEGY_V1` 5m allowlist. It then creates one
`ResearchRun` and exactly one `DEVELOPMENT` execution. The child receives a
copied physical Development-only data view and no Pilot root, acquisition
directory, Holdout values, Holdout receipt, Search input, FreqUI path, or
Release/trading action. The economic Gate is frozen to
`POSITIVE_DEVELOPMENT_V1`: trades >= 30, profit >= 0.5%, profit factor >= 1.1,
and max drawdown <= 5%. Failure produces `COMPLETED / REJECTED`; success leaves
`PENDING` with `verdict = NULL` and
`next_phase = HOLDOUT_AUTHORIZATION_REQUIRED`. Both Holdout states remain
`SEALED_UNREAD`, with no later-phase execution rows. A missing or changed Pilot
root, exact Freqtrade Python, or clean source checkout is reported as
`BLOCKED_DATA`; the Console and Codex generation remain available.

Only that exact `PENDING / PENDING` Run exposes `AUTHORIZE_HOLDOUT`. The POST
body is exactly `{ "action": "AUTHORIZE_HOLDOUT" }`; browser-supplied paths,
timeranges, fees, scenarios, thresholds, commands, or output locations are
rejected. Authorization is consumed once and starts one private child that
runs `HOLDOUT` and then `HOLDOUT_STRESS` without rerunning Development. The two
later executions and final Run state are attached in one `BEGIN IMMEDIATE` only
after both artifacts and the three-scenario contract validate. Success keeps
`verdict = NULL` for human review and creates no Release. Cancellation,
timeout, nonzero exit, or restart never retries and never leaves partial
later-phase metrics or result paths. The page links to the Strategy Library
detail using the exact Profile, Candidate, and ResearchRun ids.

If a startup-safe `--artifact-root`, `--frequi-base-url`, and a separate
disposable `--frequi-results-root` are all configured, completed artifacts are
copied there best-effort with create-exclusive semantics. A missing destination
or any pre-existing entry makes presentation unavailable; it does not overwrite
files and does not roll back the completed ResearchRun.

Normalized state/events and private raw child logs
stay under `--runtime-root`; the page never returns raw output or local paths.
The process owner locks the frozen runtime directory inode itself; there is no
unlinkable lock-file fallback. State and stdout checks use no-follow, bounded
descriptor reads, and state receipts use descriptor-scoped atomic writes. A
graceful server shutdown that confirms the whole owned process group is gone
records `INTERRUPTED` without a confirmation latch.
The Console never initializes a missing database: `/console` remains available,
SQLite is shown as `UNAVAILABLE`, and Strategy Library reads fail closed. If a
restart recovers an unclosed task, or a reaped leader leaves a process group
that cannot be safely signalled or confirmed gone, the runtime stays latched at
`INTERRUPTED_NEEDS_CONFIRMATION`; the Console has no browser confirmation action
and will not start another child from that runtime. Confirm the old process state
outside the Console, then use a new private runtime directory.

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

## Low-level Bounded Evolution V1 Search engine

`screen-search` is the Search-only Gate for a new V2 campaign. It accepts one
30-day Search window and one to three SHA-bound Candidates, runs only the
existing isolated Freqtrade screen, and emits no database row or later-phase
authorization. The Console above is the user entrypoint for the two-round
workflow; this command documents the reused low-level engine and requires an
already frozen campaign contract:

```bash
PYTHONDONTWRITEBYTECODE=1 /path/to/freqtrade-2026.7-venv/bin/python \
  scripts/run_bounded_research_pilot.py screen-search \
  --campaign-root /absolute/path/outside-git/search-campaign \
  --freqtrade-python /path/to/freqtrade-2026.7-venv/bin/python \
  --freqtrade-source /path/to/clean/freqtrade-2026.7
```

The campaign root contains `campaign.json`, append-only `trials.jsonl`, retained
Search result directories, and—when Search terminates—one write-once
`search-terminal.json`. Temporary runner input and isolation directories are
removed after each round. The root must stay outside Git. Its `acquisition/`
input uses `freqtrade-lab-retained-search-data-v2` provenance with only
`search_timerange`; it freezes the exact dependency versions and SHA/size/row
receipts for config, snapshots, and Search-only data. A contract containing
Development, Validation, Holdout, or Stress references is rejected before any
Candidate screen, as is a source data file containing post-Search rows.

`campaign.json` freezes `schema=freqtrade-lab-bounded-evolution-search-v2`,
`campaign_id`, Freqtrade `2026.7`, `round`, the exact 30-day
`search_timerange`, `data_provenance_sha256`, `budget.maximum_attempts=6`,
`ranking`, `finalist_gate`, the prior parent/receipt binding, and one to three
Candidates. Every Candidate
binds its id, class, mechanism, relationship, optional changed factor, parent
SHA, relative strategy path, and strategy SHA-256. Round 1 requires distinct
`MECHANISM_SEED` mechanisms. After its write-once round receipt, use the printed
receipt SHA and selected-parent identity to prepare round 2 `campaign.json`
containing only declared `SINGLE_FACTOR_CHILD` Candidates. There
is no third round and no more than six total attempts; duplicate source,
invalid syntax, and causal-template failure still receive a trial record and
consume budget.

The frozen ranking is net return after the configured base fee descending,
drawdown ascending, then Candidate id. PF is shown only as a diagnostic and is
not a rank or Gate input. A relative parent may have negative Search return and
is not a finalist. Only after round 2, at most one ranked Candidate becomes the
Search finalist when trades are at least 30, net return after the base fee is
strictly positive, and maximum drawdown is at most 10%. These are new V2
campaign rules; they do not revise any historical ADA/Pilot receipt.

Exit `0` means either that round 1 produced a parent brief or that round 2 froze
a Search finalist. Exit `3` means Search terminated with no parent/finalist;
contract or infrastructure failures exit `2`. The brief contains only campaign,
round/budget, Candidate identity/SHA, Search metrics or technical failure,
frozen ranking, and selected parent. It contains no acquisition or later-phase
path/value.

This command does not initialize SQLite, call the producer/importer, create
`workspace/` or `selected-input/`, open later-phase receipts, set a verdict, or
create a Release. Internally the reused low-level runner still calls its
existing `DEVELOPMENT` enum while using the Search timerange; this is only an
engine label. Protocol phase B is a separate one-shot Validation that would map
to the existing database `DEVELOPMENT` scenario, and this Search command never
enters it. B/C integration is intentionally not implemented by this slice; the
existing final `run` command and its one-shot later-phase safety boundary remain
unchanged.

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
