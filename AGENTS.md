# freqtrade-lab project instructions

## Project intent

- This is a personal, local-first Freqtrade research workbench. Prefer the smallest runnable vertical slice over platform architecture.
- Work on one GitHub Issue at a time. Read the latest Issue body and current repository state before editing.
- Tests, schemas, receipts, and documentation support delivery; they do not prove that a strategy is profitable.

## Hard boundaries

- Schema v1 contains exactly six business tables. Do not add tables, fields, indexes, ORM, migrations, caches, queues, authentication, teams, approvals, or background services unless the active Issue explicitly requires it and the user authorizes the scope change.
- Never invent PnL, metrics, artifacts, research verdicts, or FreqUI availability. Preserve `NULL`/unknown states and never convert them to zero.
- Development, Holdout, and Holdout Stress results shown together must come from the same `research_run_id`.
- Do not access credentials, sensitive databases, real funds, or live trading. Use temporary SQLite databases and frozen, sanitized fixtures for tests.
- Runtime databases, logs, and backtest artifacts stay outside Git. A sanitized fixture may be tracked only after its contents, provenance, version, and SHA-256 are checked.

## Working agreement

- Preserve user changes and avoid unrelated refactors. Stage exact paths; do not use broad `git add .` for delivery commits.
- Keep dependencies minimal. Do not introduce a frontend build system or SPA for the local read-only UI.
- Database tests: `PYTHONDONTWRITEBYTECODE=1 uv run --with pytest python -m pytest -q -p no:cacheprovider`.
- Database smoke: run `scripts/init_database.py` against a temporary path, never the default workspace database during tests.
- Before closing an Issue, verify the scoped diff, targeted tests, the actual user entrypoint, failure behavior, pushed commit SHA, and remote Issue state. Leave unavailable evidence explicit and keep the Issue open when acceptance is incomplete.
