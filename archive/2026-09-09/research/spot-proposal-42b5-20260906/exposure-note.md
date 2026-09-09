# Stage 1 exposure incident — 2026-09-06

Status: PAUSED_FOR_SUPERVISOR_ADJUDICATION. No new market acquisition or backtest occurred. No database opened, ledger changed, or repository source edited.

Violation: one Python command printed full contents of the three explicitly named index files instead of projecting identity/window/status fields first. This was an execution error, not permission to use historical results. Tool command `0af3c1` reported 33,636 original tokens and truncated output; the enclosing tool response was also truncated. This note is based only on output already obtained; no expansion/re-read of old economic results was performed to audit the incident.

Visible exposure categories (no metric values reproduced):

- PnL/net return after base fees: YES. An imported Search terminal for Issue #32 and imported Development terminal for Issue #30 contained numeric economic metrics.
- Trade count: YES, for those same imported records. Individual trade rows/timestamps: not visible in the retained output excerpt.
- Profit factor and drawdown: YES, in imported terminal summaries (drawdown visibly present for #32).
- Funding-rate or taker-fee numeric series: not visible in the retained excerpt; absence across truncated output UNKNOWN.
- Signals/individual OHLCV market values: not visible in retained excerpt; absence across truncated output UNKNOWN.
- Development values: YES, Issue #30 imported summary. Its exact dates/asset were not supplied in that visible record, only `HISTORICAL_DEVELOPMENT`; identity/window UNKNOWN. Do not label that historical Development unseen.
- Holdout/Stress result values: not visible in retained excerpt; absence across truncated output UNKNOWN. Protected-window metadata was visible, which is distinct from market/economic values.

Windows/identities actually identifiable from exposed economic records: Issue #32 Search `20260601-20260701`; pair absent in the visible record, UNKNOWN (do not infer it from other tasks). Issue #30 `HISTORICAL_DEVELOPMENT`, exact interval/asset UNKNOWN. Numerous later XRP/AVAX/DOGE/LINK/SOL metadata identities/windows appeared, but these do not establish economic exposure by themselves. Catalog filenames and archive size metadata also appeared. The truncation boundary prevents a complete exposure inventory from the retained text. No blanket claim that D/H remained unread is supportable for all historical tasks.

Subsequent reads: a process-internal projection of consumption-metadata identity/window/status keys (including flat data.instrument_id); live Issue list titles/states and Issue #61/#63/#64 identity/date/window-only extraction. No result metrics intentionally output by those projections. Those checks confirm ADA #61 and LTC #63/BCH #64 reservations, but do not cure the earlier incomplete exposure inventory.

Mitigation: stop broad reads; no asset/parameter chosen from exposed results; no proposal finalized; keep previous sealed windows and all uncertain-exposure windows ineligible pending supervisor decision. Only an explicitly adjudicated independent asset/window can proceed. Future metadata reads start with key names, then exact allowlisted leaf-field projection, never whole objects. Await supervisor ruling rather than claiming global unseen history from no index hit.
