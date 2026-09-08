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

## Current research policy (new batches from 2026-09-08)

- Read `docs/protocols/perp-autonomous-policy-v1.json`, the latest perpetual report and the Git-external scheduler state at each new research session. Issue #162 owns this migration and first slice.
- Active trading research is BTC/ETH USDT linear perpetual only, 1h, initial nominal leverage 1x. Spot #139/#155/#161 and other assets are archived research scopes; do not restart their acquisitions or forward strategy scoring from historical README examples or old scheduler prompts.
- New research uses an approximately 20% drawdown target as a diagnostic, not an automatic 20.1% rejection. Old frozen risk verdicts and actual production protections remain unchanged.
- The user's 2026-09-08 authority permits bounded public acquisition, finite transient retries, research code, isolated native backtests and project research scheduling without repeated per-step approval. No credentials, sensitive DBs, paid APIs, account access, orders, live deployment or production risk increase.
- Use the existing native Freqtrade engine and thin file-based policy/factor/report/checkpoint artifacts; no new business tables or platform services are needed. Preserve historical exposure and all old result evidence. Only one market calculation worker.
