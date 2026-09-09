# Issue #30 contract-level boundary — 2026-09-06

Recommendation: allow a value-blind TRX proposal with S 2024 and D 2025 under the explicitly qualified contract-level interpretation below. Do not claim the old terminal source is recovered. Reserve H [2026-01-01,2026-05-31) rather than [2026-01-01,2026-06-01), so the prior pre-roll tail is conservatively excluded too. This is a planning recommendation for supervisor adjudication, not acquisition or execution authorization.

## Verified relationship and code

GitHub PR #31 is merged at 28691dfa414aaed0e5d4f6e0a9db7d9a29bc96b2, merged_at 2026-08-31T21:00:57Z. Its body explicitly states `Refs #30`; GraphQL closingIssuesReferences is empty, so this is an explicit reference relationship, not an auto-close link. No historical economic metrics were read for this check.

At that exact SHA:

- lab/research_console.py:714 freezes the server Development capability at startup; :2682 passes that stored capability to prepare; :2751 constructs the worker from it. No user-supplied evaluation window is passed on this production route.
- lab/development_run.py:304 rejects any plan development_timerange other than 20260601-20260731. :329 and :340 require source/isolation contract agreement; :341 fixes exclusive stop to 2026-07-31.
- :455 re-freezes and compares identities/hashes before prepare (:787). :592 copies the capability window into snapshot. :734/:746 copy it to materialized provenance. :763 binds snapshot to manifest; :839 writes snapshot to the ResearchRun. Worker argv :895-916 has no timerange override.
- :919-938 verify materialized input hashes and snapshot hash mapping. :1001-1012 require manifest snapshot equality with the database snapshot and Candidate/run bindings. :1073 and :1082 pass that same snapshot timerange to runtime config and _run_scenario; :1127 uses the same expected interval for artifact handling.
- lab/bounded_strategy.py:241 fixes startup_candle_count=20 at 5m; normal strategy pre-roll is 100 minutes. Conservatively exclude the entire UTC 2026-05-31 day through 2026-07-31 exclusive when pair is unknown. #32's independently hash-bound XRP pre-roll starts 2026-05-31T22:00Z and is covered by this exclusion too.

Normal API route: no observed supported way to change the window after preparation while retaining the required bindings. This is not a universal tamper-proof claim: execute_development_run trusts a mutually consistent DB/manifest rather than reasserting the literal date; _require_ready compares hashes/identities but does not include capability.development_timerange itself in the comparison tuple. A caller forging an in-memory capability or coherently replacing local DB/manifest is outside the checked Console route. No evidence of either was found or sought.

## Limits and exposure reconciliation

No old Issue #30 execution ID, terminal-to-receipt hash chain, actual deployed application SHA or asset was recovered. Therefore the date constraint is strong evidence for the documented PR #31 Console execution contract, conditional on the imported #30 result belonging to that path. It is not conclusive proof of the actual old result window. Supervisor must explicitly accept this bounded inference for planning; it should remain in the final protocol provenance limitations.

Previous full-index output was truncated. Known displayed economic exposure was #30 and #32; absence of additional hidden output values cannot be proved. Later exact identity projections and complete Issue-body identity cross-checks found no TRX/XLM/ATOM match. Known other reservations/exposures identify XRP, ADA, BCH, LTC, DOGE, AVAX, LINK, SOL, DOT, NEAR, ETC, BTC/ETH in prior context, not a TRX binding. No blanket cross-asset calendar embargo is inferred. This supports TRX as the first fixed-order metadata candidate under a limited checked-history claim; it does not establish global unseen history or erase the truncation limitation.

Proposed disposition: PROCEED_TO_PROPOSAL_CONDITIONAL_ON_SUPERVISOR_BOUNDARY_ACCEPTANCE. S [2024-01-01,2025-01-01), D [2025-01-01,2026-01-01), H [2026-01-01,2026-05-31); exact proposal pre-roll and sample feasibility remain to be fixed before market access. TRX source/listing completeness has not been verified with market acquisition. No fourth asset, data, backtest, database, ledger or repository mutation.
