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

- Read `docs/protocols/perp-autonomous-policy-v3.json`, `docs/research-knowledge/perp-autonomous-v3.json`, `docs/protocols/perp-dispatch-policy-v1.json`, the latest perpetual report and the Git-external scheduler state at each new research session. Issue #162 owns this migration and first slice.
- Budget is cumulative across policies: 8 exploration variants per UTC day / 28 per UTC week; every 3 finished rounds is a review checkpoint, not a round cap. Fixed candidate acceptance and one-shot confirmation have separate bounded budgets, one market worker. Keep the fixed confirmation reservation plus at most one priority short development task, with no more than two active mechanisms. Use the appended dispatch entrypoint for enqueue/claim, preserve the same writer lock, and give due confirmation and timely data/intent maintenance priority. Finish/report and continue a justified successor when budget and real gates permit. Daily idea ranking is not a one-round-per-day restriction. Preserve V1 frozen code, protocols, results and consumed budget.
- Active trading research is BTC/ETH USDT linear perpetual only, 1h, initial nominal leverage 1x. Spot #139/#155/#161 and other assets are archived research scopes; do not restart their acquisitions or forward strategy scoring from historical README examples or old scheduler prompts.
- New research uses an approximately 20% drawdown target as a diagnostic, not an automatic 20.1% rejection. Old frozen risk verdicts and actual production protections remain unchanged.
- The user's 2026-09-08 authority permits bounded public acquisition, finite transient retries, research code, isolated native backtests and project research scheduling without repeated per-step approval. No credentials, sensitive DBs, paid APIs, account access, orders, live deployment or production risk increase.
- Use the existing native Freqtrade engine and thin file-based policy/factor/report/checkpoint artifacts; no new business tables or platform services are needed. Preserve historical exposure and all old result evidence. Only one market calculation worker.

## Dispatch improvement authorized 2026-09-09

- Keep `lab/perp_schedule.py`, the V3 budget policy, observer binding, fixed candidate and confirmation consumers at their existing frozen hashes. New dispatch admission is a separately installed version, not a rewrite of those identities.
- Use `scripts/perp_research_status.py` to distinguish confirmation waiting, actual computation and priority exploration. A 90-day `WAITING_DATA` reservation does not mean the whole system is blocked.
- New exploration must bind the admitted exposed-development manifest and actual row timestamps. Never use the fixed confirmation window prices, signal directions, trades, equity or reports as exploration features or selection input. Runtime maintenance may check receipt identity, timing and completeness only.
- Before market execution, finish targeted synthetic checks and freeze actual code/data bindings. Preserve superseded unstarted preparation receipts and source snapshots when a pre-execution verifier correction requires a new binding. No rename or different output path resets a started experiment.

- The active heartbeat performs bounded public-source discovery once after 09:00 Asia/Shanghai daily and at most one supplementary discovery after an empty exploration terminal. Reuse the just-completed daily batch when inputs did not change. Each batch permits at most 6 queries, 8 pages and 10 active minutes, with immutable daily runtime receipts and preserved partial usage; maintenance and ready experiments come first. Source popularity is not economic evidence.
