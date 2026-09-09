## PREREGISTERED — LTC_EXACT_GRID_DUAL_SMA_28_84_V1

Frozen before new market acquisition. Slug `ltc-exact-grid-dual-sma-28-84-v1`. Clean detached worktree `/Users/shenjianpeng/.codex/worktrees/1ad9/freqtrade-lab`; HEAD and live remote main `dc82c61fe8a27a654977344755c088412518d858`. Executor task `01a06e15-ffd9-7240-b492-9761a1285e98`; supervisor `01a05dcc-17fd-7972-9177-9fed95e4b07a`. Service tier UNKNOWN because interface does not expose it; no Fast/config changes.

Independent private 0700 Git-external root: `/Users/shenjianpeng/.codex/runs/freqtrade-lab/ltc-exact-grid-dual-sma-28-84-v1/cohort-v1.0cg9aqkv`.

### Hypothesis, selection, authority
Fixed single-source engineering/data-availability check on LTC; not selected from old LTC prices or returns. No usable window is established. Reuse the economically unevaluated 28/84 daily dual-SMA hypothesis: directional state could retain trend exposure with fewer reversals. No claim that a paper proves LTC or these parameters. #62 remains stopped OPEN/BLOCKED_DATA; no old protocol changes, collection restart or success closure.

User already authorizes this Issue, public collection, Profile/Candidate generation/review/approval, bounded Search and one Development for a legal finalist. Holdout and Stress require separate one-shot authorization; remain SEALED_UNREAD. No credentials, sensitive DB, funds/live trading, Release, Freqtrade Ai changes, business-code/schema changes, new services, custom engine/runner, PR or artificial delivery commit.

### Frozen identity and windows
- LTC/USDT:USDT; LTC-USDT-SWAP; OKX linear perpetual, futures isolated, 1d, long-only, 1x.
- data_start=2023-10-04T00:00:00Z.
- Search=[2024-02-01T00:00:00Z,2025-02-01T00:00:00Z), 366 days.
- Development=[2025-02-01T00:00:00Z,2026-02-01T00:00:00Z), 365 days.
- Holdout/Stress metadata=[2026-02-01T00:00:00Z,2026-07-31T00:00:00Z), 180 days, SEALED_UNREAD.
- pre_roll_days=120; startup_candle_count=90. Program assertions passed: Search minus 120d equals data_start; Holdout start plus 180d equals end; full funding window contains 2193 scheduled 8h events.
- min_development_trades=5 applies independently to Search and Development; min_holdout_trades=4, holdout_days=180, smoke_days=30 metadata only. No independent smoke. These 12-month stages retain #62's 5-trade/1.25% thresholds without reduction; insufficient sample terminates honestly.
- fee=.0005; real funding records must enter Freqtrade; slippage=UNKNOWN; balance=1000; stake=100; max_open_trades=1; stress_fee_multiplier=2 metadata only.

### Frozen gates and exact strategies
Both stages independently require strictly positive net return, profit_factor>=1.10, maximum drawdown<=15%, trades>=5. PROFILE_DRIVEN_ECONOMIC_GATE_V1: minimum_net_profit_after_base_fees_pct=1.25, minimum_average_holding_period_minutes=10080, maximum_roi_exit_count=0. UNKNOWN fails. No post-result changes or combining stages to mask failure. Existing finalist ranking applies.

R1 class `LtcExactGridDualSmaR1`: INTERFACE_VERSION=3, timeframe='1d', startup_candle_count=90, process_only_new_candles=True, minimal_roi={}, can_short=False, stoploss=-.20. `fast=close.rolling(28).mean()`; `slow=close.rolling(84).mean()`; fast>slow sets enter_long; fast<slow sets exit_long; equality/NaN produce no signal. State rule, not cross-only. No price/volume/ATR/time filters, forced holding, ROI or delayed exits. Closed-candle signal, Freqtrade next-timepoint execution.

R2 class `LtcExactGridDualSmaR2` differs only in class name and stoploss=-.10; parent bound to R1, changed_factor=stoploss. Before approval verify exact AST/fields, unique classes, hashes and project single-factor verifier.

Exactly at most two actual Search attempts: technically valid R1 requires R2 even if economically negative. Early stop only for technical/data/security error. No third attempt, reruns, retrospective tuning, asset substitution, shifted windows or tolerance increase. Legal finalist permits exactly one independent Development. No finalist means no ResearchRun or fabricated pending state. Development rejected stays REJECTED; pass stops HOLDOUT_AUTHORIZATION_REQUIRED and notifies supervisor.

### Consumption metadata and data-first execution
Only canonical contract/receipt metadata under `/Users/shenjianpeng/.codex/runs/freqtrade-lab` and related public Issue/PR metadata are in scope. #62 consumption index reused as index: 36 referenced file hashes reverified; 77 current canonical metadata files checked; no identified LTC record at any timeframe. GitHub LTC Issue search returned no matches. All LTC timeframes count for consumption/seal conflicts; an identified conflict stops without shifting windows. External runs remain NOT_AUDITED_UNKNOWN. No old prices, PnL, sensitive DB or sealed values used. Detailed scope/hash evidence: `consumption-metadata.json` in root.

1. Use existing official producer instrument/catalog/transport and bounded 429 policy. Fetch only the first necessary monthly funding archive initially for fixed [2024-02-01,2026-02-01). Check selected RAW timestamps, before normalization: exact 8h grid, no nonzero offset, gaps, duplicate timestamps, identity/nonfinite/other material errors. First substantive failure => BLOCKED_DATA; do not repeat it. Do not modify producer 0..2000ms constants or rules and do not claim floor output proves raw exactness.
2. First archive pass immediately continues remaining funding-only precheck; each month stops at first substantive failure. Expected per-month sequence is UTC+8 local-month half-open interval intersected with frozen UTC window. Last boundary event may belong to the next local month. Full-window expected count is program-verified 2193. No unrelated historical/asset audits. Out-of-window rates remain uninterpreted under main timestamp-first behavior, including final UTC+8 month archive.
3. Full raw zero-offset, unique, continuous, correct identity/value precheck unlocks official source acquisition and independent Search/Development slices, reusing new raw archives from this same root through normal producer mechanism. No old cohort values, manual source splicing, independent Holdout/Stress price/mark acquisition. Validate source binding, hashes, UTC sequences/counts, 120-day warmup, bounds, retention and consumer before Candidate.
4. Then initialize new six-table DB/Profile via existing lab.database if no HTTP Profile route; generation/approval/Search/Development via existing Console/API/formal entries. Compact process/results in generation_runs/metadata; large artifacts external and hash-bound. Search-only research_runs/backtest_executions/releases have no execution rows. One real page/API reconciliation; generic Development READY is not finalist proof; backend gate controls.
5. Reuse clean Freqtrade 2026.7 `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade`, same-level venv/bin/python, exact SHA `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`; verify runtime and prevent PYTHONPATH shadowing. Only necessary static/data checks and real engine executions; no full suite, independent smoke, custom runner or engine fork.

Raw exact grid removes normalization offset; it does not establish second-level assessment, execution or slippage fidelity. Record this as the existing Freqtrade modeling convention; no expanded qualification claim.

### Reporting and terminal audit
Notify supervisor on startup identity, Issue/window freeze, first archive pass, complete data pass, first engine result, Search terminal, Development terminal or material blocker. New capability gaps stop with minimal evidence; no implementation expansion.
End with Issue/code/source SHA, root, Profile/Generation/Candidate/Campaign/ResearchRun IDs, gate and actual failed items, six-table/API/page/terminal/ZIP consistency. No result => NULL/UNKNOWN. Preserve raw failure and original evidence. Incomplete acceptance keeps this Issue OPEN. No code change means no PR or artificial commit.
