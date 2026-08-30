# freqtrade-lab

A small, local-first research workbench for recording Freqtrade strategy lineage, research runs, backtest evidence, and releases.

The repository currently provides the SQLite schema v1 foundation only. It does not yet run Freqtrade, expose a web UI, or prove that any strategy is profitable.

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
