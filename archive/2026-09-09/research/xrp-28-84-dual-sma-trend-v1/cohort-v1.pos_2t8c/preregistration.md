## PREREGISTERED — XRP_28_84_DUAL_SMA_TREND_V1

Frozen before any new XRP market acquisition. Worktree `/Users/shenjianpeng/.codex/worktrees/dca5/freqtrade-lab`, clean HEAD and live remote main `dc82c61fe8a27a654977344755c088412518d858` (PR #60 timestamp-first funding parser); #61 verified CLOSED. This is a new hypothesis and independent cohort; previous ADA results, gates, prices, Candidates and artifacts will not be reused or modified.

### Hypothesis and authority
28/84 daily SMA state may reduce direction reversals relative to a single 30-day endpoint comparison and retain net returns with actual holding duration. This is falsifiable, not a profitability claim. Liu/Tsyvinski NBER w24877 motivates time-series momentum only; it does not prove the exact XRP rule. No forced seven-day hold, delayed exits or post-result rescue. R2 changes only risk stoploss.
User authorizes preregistration, public data acquisition, Profile and Candidate generation/review/approval, two Search attempts, and one independent Development only for a legal finalist. No Holdout/Stress read or execution; separate one-shot user authorization is required. No credentials, sensitive DB, funds, trading, Freqtrade Ai, business-code or schema changes.

### Frozen market and windows
- XRP/USDT:USDT; XRP-USDT-SWAP; OKX linear perpetual futures/isolated; timeframe 1d; long-only; can_short=False; 1x.
- data_start=2023-01-01T00:00:00Z; Search=[2023-05-01T00:00:00Z,2024-08-01T00:00:00Z).
- Development=[2024-08-01T00:00:00Z,2025-11-01T00:00:00Z).
- Holdout metadata=[2025-11-01T00:00:00Z,2026-04-30T00:00:00Z), 180 days; Stress same window. Both SEALED_UNREAD.
- 120 daily warmup candles. Program assertions passed: Search start minus 120 days = 2023-01-01; Holdout start plus 180 days = 2026-04-30.
- Search and Development are 15 months for slower signals. Relative to earlier 12-month 4-trade/1% gate, minimums scale to 5 trades/1.25%; no relaxed standard. Holdout 180 days gives low-frequency signals observation capacity.
- fee=.0005; historical funding must enter Freqtrade; slippage=UNKNOWN; starting_balance=1000; stake=100; max_open_trades=1; stress_fee_multiplier=2 metadata only.

### Frozen Profile and economic gates
Use existing Profile fields: min_development_trades=5 (Search and Development), min_holdout_trades=4, holdout_days=180, smoke_days=30 (no separate smoke), maximum drawdown<=15%, profit factor>=1.10, net strictly positive.
Same frozen PROFILE_DRIVEN_ECONOMIC_GATE_V1 applies separately to Search and Development: minimum_net_profit_after_base_fees_pct=1.25; minimum_average_holding_period_minutes=10080; maximum_roi_exit_count=0. UNKNOWN fails closed. Never average stages to hide failures. Ranking remains net descending, DD ascending, ID ascending. Verify real entrypoint faithfully represents holdout_days=180; otherwise stop capability-blocked without new fields, changed windows or fabricated downstream capability.

### Exact frozen strategies
R1 class XrpDualSmaTrendR1: INTERFACE_VERSION=3; timeframe='1d'; startup_candle_count=90; process_only_new_candles=True; minimal_roi={}; can_short=False; stoploss=-0.20.
Indicators: fast_sma=close.rolling(28).mean(); slow_sma=close.rolling(84).mean(). enter_long=1 iff fast_sma>slow_sma; exit_long=1 iff fast_sma<slow_sma. Equal or NaN gives no signal. State rule, not cross-only event. No short, volume/price/ATR/time filters, ROI, forced minimum hold or delayed exit. Signal uses candle close; Freqtrade executes next timepoint.
R2 class XrpDualSmaTrendR2: identical source except class name and stoploss=-0.10; changed_factor=stoploss, parent R1. Before approval check distinct names, exact frozen R1 AST/fields, project single-factor validator=True, hashes and parent binding. Do not repeat #55 same-class invalid attempt.

### Data provenance and consumer
Before acquisition audit only contract/receipt metadata in `/Users/shenjianpeng/.codex/runs/freqtrade-lab` and related Issues: pair, timeframe, dates, phase and status. Do not use old price/PnL to select windows. Cross-timeframe consumption/seals count, especially older XRP 5m exposure inside proposed Holdout. Any conflict or unresolved in-scope overlap UNKNOWN => BLOCKED_DATA before acquisition, with exact dates; no shifting dates/assets. External unknown runs are not falsely claimed audited.
Fresh private Git-external root: /Users/shenjianpeng/.codex/runs/freqtrade-lab/xrp-28-84-dual-sma-trend-v1/cohort-v1.pos_2t8c. Retain raw sources/hash evidence outside Git.
1. Existing official producer public instrument/catalog/parser/validator funding-only precheck over [2023-05-01,2025-11-01). PR #60 timestamp-first selects before interpreting rate, including final UTC+8 archive; protected out-of-range rates remain uninterpreted. Preserve 0..2000ms drift tolerance, 8h continuity, instrument identity, finite values and raw SHA-256. Stop on first substantive source failure; no repeated full-month audit, fill/splice/omit funding/tolerance change.
2. Only after precheck passes: fresh schema-v1 six-table DB, Profile, full official acquisition and independent Search/Development slices. Producer and consumer validate source binding, identity, UTC continuity, counts, 120-day warmup, bounds, retention and hashes before Candidate. No old market data/Candidate/artifact reused.
3. Reuse clean Freqtrade 2026.7 source `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade` and venv only after checking commit `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`, source cleanliness and runtime version. PYTHONPATH must prevent site-packages shadowing. Actual results only from existing project/Freqtrade engine, no custom backtest runner.
4. If Profile has no HTTP creation route, use existing lab.database connection API. All subsequent generation/approval/Search/Development through existing pages/API/formal entrypoints. Six tables store compact results/process; large source/artifacts external and hash-bound. No schema additions.

### Budget, stop and reporting
Exactly two actual Search attempts: technically valid R1 always followed by unique R2 regardless of economic sign. Only data/security/technical failure permits early stop. No third attempt, rerun, rescue, new gate or post-result parameter change.
No legal finalist => SEARCH_TERMINATED_NO_FINALIST, no Development. Legal finalist => exactly one independent Development: fail DEVELOPMENT_REJECTED; pass HOLDOUT_AUTHORIZATION_REQUIRED, notify supervisor and stop sealed.
No independent smoke, no full test suite, only necessary data/AST/actual engine/persistence checks. #61 generic Development READY button is not finalist evidence; backend 409 gate remains authoritative, no UI expansion.
Notify source task on consumption conflict, precheck pass, first engine result, Search terminal, Development terminal or new capability blocker. End with Issue/code/source SHA, exact root, Profile/Candidate/campaign/ResearchRun IDs, two results/failing criteria, six-table/API/page/terminal/ZIP-hash consistency, unexecuted stages and sealed status. If code change is necessary, stop with reproducer and minimal assessment for supervisor; no engineering expansion.
