## Full frozen funding-only raw exact-grid precheck PASS

This is data-precheck evidence, not a strategy result or full source readiness. Search attempts=0; Profile/Generation/Candidate/Campaign/ResearchRun IDs=NULL; no database exists yet. Holdout/Stress remain SEALED_UNREAD.

- 25 official UTC+8 monthly archives (2024-02 through 2026-02), fixed selected window [2024-02-01,2026-02-01).
- 2193/2193 expected raw funding timestamps: zero offset from 8h grid, unique and continuous, correct LTC-USDT-SWAP identity, finite selected values. Original timestamps checked before unchanged producer parser; no normalization used to establish raw exactness.
- First month: 86/86 events; final month: 1/1 event, with 83 out-of-window rate values left uninterpreted. Per-month expected series uses local-month intersection with frozen UTC window.
- Runtime validated: Python 3.13.13, Freqtrade 2026.7 clean SHA 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5, ccxt 4.5.68, pandas 3.0.3, pyarrow 25.0.0.
- Exact private root: `/Users/shenjianpeng/.codex/runs/freqtrade-lab/ltc-exact-grid-dual-sma-28-84-v1/cohort-v1.0cg9aqkv`. Raw ZIPs and request/parser receipts retained; `funding-precheck-terminal.json` is authoritative. No old cohort prices/PnL reused.

Remaining gate: official futures/mark acquisition, independent Search/Development slices and consumer validation. Main producer currently has no raw-reuse parameter; supervisor has received the proposed minimal same-root transport binding for review. No producer constants, code/schema or windows changed. Issue remains OPEN.
