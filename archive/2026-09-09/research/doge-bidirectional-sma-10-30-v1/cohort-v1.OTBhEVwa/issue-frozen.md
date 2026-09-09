## PREREGISTERED — DOGE_BIDIRECTIONAL_SMA_10_30_V1

Frozen before any new DOGE market acquisition. Exact external contract below. No outcome-dependent changes. Raw exact grid does not establish second-level settlement/fill fidelity. Actual strategy AST/hash and unique class plus project single-factor verifier are required before approval. No filters, forced holding, leverage callback, ROI or manual backtest. Technical/data failure stops with evidence; no asset/window substitution, third Search, or runner implementation. Search+Dev require current producer and consumer provenance/isolation verification. Holdout/Stress boundaries are metadata only: never acquire or interpret their prices/funding. Use existing Console/API and original six tables, preserve NULL. #64 remains closed and #62 remains untouched.

```json
{
  "name": "DOGE_BIDIRECTIONAL_SMA_10_30_V1",
  "executor": "01a06e40-e16b-72d2-a517-8acca61acab1",
  "supervisor": "01a05dcc-17fd-7972-9177-9fed95e4b07a",
  "cwd": "/Users/shenjianpeng/.codex/worktrees/4f75/freqtrade-lab",
  "root": "/Users/shenjianpeng/.codex/runs/freqtrade-lab/doge-bidirectional-sma-10-30-v1/cohort-v1.OTBhEVwa",
  "main": "dc82c61fe8a27a654977344755c088412518d858",
  "model": "gpt-6-astra",
  "reasoning": "high",
  "service_tier": "UNKNOWN",
  "pair": "DOGE/USDT:USDT",
  "instrument_id": "DOGE-USDT-SWAP",
  "exchange": "okx",
  "trading_mode": "futures",
  "margin_mode": "isolated",
  "timeframe": "1d",
  "directions": [
    "long",
    "short"
  ],
  "leverage": 1,
  "balance": 1000,
  "stake": 100,
  "max_open_trades": 1,
  "fee": 0.0005,
  "slippage": "UNKNOWN",
  "funding": "actual_native_engine",
  "data_start_utc": "2023-10-04T00:00:00Z",
  "search": [
    "2024-02-01T00:00:00Z",
    "2025-02-01T00:00:00Z"
  ],
  "development": [
    "2025-02-01T00:00:00Z",
    "2026-02-01T00:00:00Z"
  ],
  "holdout": [
    "2026-02-01T00:00:00Z",
    "2026-07-31T00:00:00Z"
  ],
  "holdout_status": "SEALED_UNREAD",
  "stress_status": "SEALED_UNREAD",
  "pre_roll_days": 120,
  "startup_candle_count": 90,
  "gate_each_search_and_development": {
    "min_trades": 5,
    "net_profit_pct_strictly_above": 0,
    "min_profit_factor": 1.1,
    "max_drawdown_pct": 15,
    "minimum_net_profit_after_base_fees_pct": 1.25,
    "minimum_average_holding_period_minutes": 10080,
    "maximum_roi_exit_count": 0,
    "unknown": "FAIL"
  },
  "holdout_min_trades": 4,
  "stress_fee_multiplier": 2,
  "r1": {
    "class": "DogeBidirectionalSmaR1",
    "fast": "close.rolling(10).mean()",
    "slow": "close.rolling(30).mean()",
    "stoploss": -0.2,
    "can_short": true,
    "minimal_roi": {},
    "signal": "fast>slow enter_long and exit_short; fast<slow enter_short and exit_long; equal/NaN no signals; state signals; native next candle execution",
    "extras": "none"
  },
  "r2": {
    "class": "DogeBidirectionalSmaR2",
    "parent": "R1",
    "changed_factor": "stoploss",
    "stoploss": -0.1,
    "only_differences": [
      "class_name",
      "stoploss"
    ]
  },
  "budget": {
    "max_actual_search": 2,
    "r2_required_if_r1_technically_valid": true,
    "max_development": 1,
    "ranking": "existing frozen ranking",
    "holdout_runs": 0,
    "stress_runs": 0
  },
  "expected_rows": {
    "source": {
      "futures": 851,
      "mark": 20424,
      "funding": 2193
    },
    "search": {
      "futures": 486,
      "mark": 11664,
      "funding": 1098
    },
    "development": {
      "futures": 485,
      "mark": 11640,
      "funding": 1095
    }
  },
  "data_gate": {
    "months": 25,
    "first_month_events": 86,
    "last_month_events": 1,
    "raw_offset_ms": 0,
    "grid_hours": 8,
    "timestamp_first": true,
    "first_failure": "BLOCKED_DATA_NO_RETRY_NO_SUBSTITUTION",
    "producer": "unchanged existing native producer; one authorized same-source re-download after full funding PASS; compare all ZIP/CSV SHA"
  },
  "route_terminal": "Final bounded extension of simple dual SMA route. Full economic no finalist or Dev failure retires route; data block is not strategy failure.",
  "selection_risk": "DOGE fixed before prices/returns, not ranking. Cross-asset overlapping calendar windows correlated, not independent statistical repetition; cumulative trials and multiple selection remain.",
  "prior": "LTC #63 2/4 trades insufficient; BCH #64 Search passed, unique R1 Dev 8 trades net -0.444077628% PF .92208059 failed; funding +1.3588392277 USDT receipt, not drag. DOGE does not establish BCH repair or superiority.",
  "consumption": "metadata-only all-timeframe canonical index plus updates; no DOGE conflict identified; external uncovered UNKNOWN",
  "engine": {
    "path": "/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade",
    "sha": "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5",
    "version": "2026.7"
  },
  "hypothesis_sources": [
    "https://pages.stern.nyu.edu/~lpederse/papers/TimeSeriesMomentum.pdf",
    "https://academic.oup.com/rfs/article-abstract/34/6/2689/5912024",
    "https://www.freqtrade.io/en/stable/leverage/"
  ],
  "source_limits": "Moskowitz et al: traditional futures own-return long/short with volatility scaling; not DOGE, SMA10/30, fixed-stake validation or replication. Liu/Tsyvinski broad crypto momentum motivation only; official abstract direct request unavailable this turn.",
  "authorization": "New Issue, public data, independent six-table Profile/CODEX generation/Candidate review+approval, MANUAL Search terminal projection; legal finalist creates one ResearchRun and Dev. Dev pass stops HOLDOUT_AUTHORIZATION_REQUIRED. No seals values, no Release/live/credentials/sensitive DB; no business changes or new service/runner/cache/schema.",
  "delivery": "One terminal report/Issue evidence; supervisor acceptance, leave Issue OPEN; no artificial commit; actual trades/costs/direction PnL, SHA, IDs, DB/API/page reconciliation."
}
```
