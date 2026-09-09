## Issue #62 — BLOCKED_DATA

The frozen XRP_28_84_DUAL_SMA_TREND_V1 cohort stopped at its first funding-only precheck source error. This is not a Search loss or SEARCH_TERMINATED_NO_FINALIST; economic outcome remains UNKNOWN.

- Clean worktree and live main: `dc82c61fe8a27a654977344755c088412518d858` (PR #60); #61 verified CLOSED before this Issue.
- Exact 0700 root: `/Users/shenjianpeng/.codex/runs/freqtrade-lab/xrp-28-84-dual-sma-trend-v1/cohort-v1.pos_2t8c`.
- Clean Freqtrade 2026.7: `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`; Python 3.13.13, ccxt 4.5.68, pandas 3.0.3, pyarrow 25.0.0 verified by official producer runtime validator with source PYTHONPATH binding.
- Public XRP-USDT-SWAP identity/listing validation passed. First funding archive is May 2023. CSV line 11 timestamp `1683129603000` = `2023-05-03T16:00:03Z` has drift **3000ms**, exceeding frozen **2000ms**. Exact official parser error: `RuntimeError: funding archive month 2023-05 timestamp drifted`.
- Raw official ZIP: `precheck-xrp/http-002.zip`; SHA-256 `7e9f4337bf346bfdb3315ef342a2dd6e3ed760152449a82a452f052d42455783`. Raw HTTP hashes rechecked. No rate values reported. No later-month audit, full acquisition, price data, retry, splice, filling or tolerance change.
- R1 / R2 actual Search attempts: **0 / 0**. Profile, generation, Candidate, campaign and ResearchRun IDs: **NULL / none**. Database not created; six-table counts **not applicable**, not queried or manufactured as zero. No engine ZIP or metrics. API/page **not started** because precheck failed before initialization.
- Development not executed. Holdout/Stress `[2025-11-01,2026-04-30)` remain **SEALED_UNREAD**; no protected window was fetched/read/executed. Both 120-day warmup and 180-day Holdout date assertions passed.
- Schema `holdout_days > 0` and Development Profile snapshot duration branch express 180 days at source level. Runtime Profile/Development capability is not established because data precheck stopped first.
- `consumption-metadata.json`: 18 canonical window records, none identified XRP. Related early XRP 5m Issue/PR metadata describes 2026 mid/late-year Pilot/fixture windows, outside this cohort's `[2023-01-01,2026-04-30)` span. Audit scope is the specified canonical root plus related Issue/PR metadata; external unknown runs remain unaudited. No old price/PnL or sensitive DB read for selection.

Contract requires stopping on this substantive source error. No business code/schema changes, tests, smoke, candidate generation, backtest, release or trading. Issue remains open because requested execution acceptance is incomplete; supervisor notified. No silent replay or changed dates/assets/tolerance. Any different research contract requires a separate supervised decision.
