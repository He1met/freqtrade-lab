## PREREGISTERED — DATA_SELECTED_30D_TSMOM_DRAWDOWN_RISK_OFF_V1

Frozen before any new market-data acquisition. Clean execution worktree `/Users/shenjianpeng/.codex/worktrees/6dc2/freqtrade-lab`; live remote main and HEAD `dc82c61fe8a27a654977344755c088412518d858`, includes merged PR #60 timestamp-first archive selection. Date assertion passed: 2024-04-01 minus 60 days equals 2024-02-01 UTC.

### Scope and source-only selection algorithm
1. Fixed priority ADA/USDT:USDT → SOL/USDT:USDT → XRP/USDT:USDT; maximum three, no fourth asset or ranking optimization. All share the dates, strategy, gates and budget below.
2. Before acquisition, audit only canonical metadata/receipts and non-sensitive research records in `/Users/shenjianpeng/.codex/runs/freqtrade-lab` and referenced Issues #55/#57/#58/#59/#60 for same-pair/timeframe consumption and seals. Do not read old price/PnL or sealed values to select an asset; unknown overlap is not unconsumed. #57 SOL [2024-01-01,2024-02-01) remains sealed, including pre-roll; never replay old cohorts. #58 is terminal BLOCKED_DATA, not repaired.
3. In order, inspect instrument/listing, official funding catalog, raw timestamps, missing/duplicate/continuity/finite-rate checks using the existing producer public transport/catalog/parser/validator. Normalization remains FLOOR_TO_8H_GRID_V1 with 0..2000ms tolerance. No custom backtest runner or product-code expansion. Source-only precheck uses isolated synthetic configuration when needed; no signals, PnL, rate-level/direction or price-performance selection.
4. On metadata overlap, missing data or unsupported normalization, retain an exact reason and move to the next fixed asset; stop at first decisive failing month if appropriate. Choose first complete and provably unconsumed asset; immediately stop checking later assets. Bind pair/instrument/Profile/source hashes and selection summary to existing Profile description/controls and this Issue, without schema additions.
5. Complete OHLC/mark acquisition may still fail; before Candidate generation or any economic result only, the same fixed priority may continue with retained failure evidence. After any economic result, no asset switch or rescue. If all three fail, terminate BLOCKED_DATA and report common capability limits; no new windows, relaxed tolerance, spliced sources or omitted funding. Precheck is not a Search attempt.
6. Raw archives and large precheck evidence stay in a fresh Git-external 0700 directory; source bytes and SHA-256 retained. Formal source acquisition must use merged official unauthenticated project entrypoint. UTC+8 final archives crossing Holdout use timestamp-first selected-only validation: no parsing/reporting/interpreting protected rates.

### Frozen execution contract
- OKX linear perpetual, futures/isolated, 1d, long-only, can_short=False; no leverage experiment.
- data_start 2024-02-01T00:00:00Z; pre_roll_candles=60.
- Search [2024-04-01T00:00:00Z,2025-04-01T00:00:00Z).
- Independent Development [2025-04-01T00:00:00Z,2026-04-01T00:00:00Z).
- Holdout metadata [2026-04-01T00:00:00Z,2026-05-01T00:00:00Z), holdout_days=30; Stress same window. Both SEALED_UNREAD and require separate one-shot user authorization. This task never executes either.
- fee=.0005; historical funding must enter engine; slippage=UNKNOWN; balance=1000, stake=100, max_open_trades=1; stress_fee_multiplier=2 metadata only.
- Fresh independent schema-v1 six-table database, source/search/development roots, no reused old market/Candidate/runtime artifact. Exact clean Freqtrade 2026.7 Git source and venv binding, avoiding site-packages shadowing; tools may be reused. Producer and consumer verify instrument, UTC, continuity, rows, 60-day warmup, retention, hashes and boundaries before any Candidate.
- No separate engine smoke or full project suite: actual R1 provides engine compatibility evidence.

### Frozen strategy and lineage
Display family DATA_SELECTED_30D_TSMOM_DRAWDOWN_RISK_OFF_V1. After selection use legal consistent lowercase slug such as ada-30d-tsmom-drawdown-risk-off-v1 from first generation.
Common INTERFACE_VERSION=3, startup_candle_count=40, process_only_new_candles=True, minimal_roi={}, can_short=False.
R1 unique class DataSelectedRiskMomentumR1; stoploss=-0.20:
close_30=close.shift(30); prior_high_30=high.rolling(30).max().shift(1).
enter_long when close>close_30 AND close>prior_high_30*0.85.
exit_long when close<close_30 OR close<prior_high_30*0.85.
No short signals. R2 unique class DataSelectedRiskMomentumR2, identical except stoploss=-0.10 and class name; changed_factor=stoploss, parent=R1. Before approval verify distinct classes, exact parent, single-factor AST and exact verifier=True. Do not repeat #55 duplicate-class invalid attempt.

This is an untested single-asset risk-management momentum hypothesis. Liu/Tsyvinski NBER w24877 motivates crypto time-series momentum. Ao Yang 2025 DOI10.1016/j.frl.2025.107879 uses 2-week formation/1-week holding cross-coin WML plus volatility management; these rules are an extrapolation, not replication, and citations do not establish profitability.

### Frozen gates, budget and stopping
- Profile: minimum_trades=4, net strictly positive, profit factor>=1.10, max drawdown<=15%.
- PROFILE_DRIVEN_ECONOMIC_GATE_V1: minimum_net_profit_after_base_fees_pct=1.0, minimum_average_holding_period_minutes=10080, maximum_roi_exit_count=0; UNKNOWN fails closed.
- Search and independent Development each pass separately; never average across windows. Existing ranking net descending, DD ascending, ID ascending; no manual winner substitution.
- Maximum two rounds, exactly one R1 and one R2 true Search attempt; after technically valid R1 run unique R2 regardless of economic sign. No third attempt or post-result parameter/window/gate change. Only technical/data/security failure permits early stop; invalid consumed attempts remain recorded, never replayed.
- Two legal attempts without finalist → SEARCH_TERMINATED_NO_FINALIST. Only lawful finalist gets one independent Development. Development failure → DEVELOPMENT_REJECTED; pass → HOLDOUT_AUTHORIZATION_REQUIRED, notify supervisor and stop sealed.

### Delivery and authority
User explicitly authorizes data acquisition, Profile/generation/Candidate review and approval, Search, Development and necessary terminal Issue records. Use existing pages/APIs/official Freqtrade entrypoints and existing six tables; no new schema/fields/runner/services. No credentials, sensitive DB, funds, live trading or Freqtrade Ai changes. If new code is required, retain exact reproducible blocker and defer scope decision to supervisor.
Notify source task at selection, first engine result, real blocker, Search terminal and Development terminal. Deliver Issue/code SHA, selection table, chosen pair, roots/DB/IDs, two attempt metrics, Development or reason absent, six-table counts, actual page/API and failure evidence, inside/outside-DB boundary, hashes and sealed status. No fabricated metrics, ResearchRun or terminal projection; NULL stays unknown. Technical completion and in-sample results do not establish profitability or trading readiness.
