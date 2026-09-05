# LAGGED_FUNDING_SIGNAL_V1

Issue #71 provides one fixed historical funding strategy template for exploratory
Search. It is an engineering capability, not economic or qualification evidence.

## Existing entrypoints

Start the existing Research Console with its explicit Search root and frozen
exploration contract. Use the existing `POST /api/generations` with
`strategy_family="lagged_funding_signal_v1"`, the frozen Profile id and idea.
The Profile must select only LINK/USDT:USDT, 5m and one open trade. The server adds
the fixed source to the generation prompt and persists `signal_contract` inside
the existing request/provenance JSON. Ordinary request/response, Profile, code SHA,
review and parent binding still apply. No table or SQL column was added.

R1 has no parent. R2 names the approved fixed R1 as `parent_candidate_id` and uses
`entry_lagged_funding_positive_v1` as the existing Search changed factor. R2 adds
only `lagged_funding > 0.0001`; after removing that exact conjunct, the entire
remaining AST must equal R1. Shared guards cannot be removed or changed.
`lab.lagged_funding.funding_source()` exports each complete standalone source.
Only the class name varies; imports, methods, clocks, guards and parameters match
the fixed AST. Generic DataProvider calls and arbitrary UTC expressions remain
outside the ordinary strategy allowlist. The exported source imports only pandas
and native Freqtrade, so it does not depend on this repository on PYTHONPATH.

## Source and timing

Use the existing `scripts/fetch_okx_profile_data.py` producer with a newly frozen
source contract, then `prepare_search_data`. Existing source-sharing intentionally
rejects changed windows, pre-roll and exposure contracts. It cannot repurpose A/B
source receipts for this experiment. A fresh directory still uses the already-seen
historical exploration pool; it is not statistically independent data.

The planned `[2024-03-01, 2024-07-31)` window has 289 OHLCV pre-roll candles from
2024-02-28 23:55 UTC, mark from 23:00 UTC, and funding only from Search start.
The expected rows are 44065 / 3673 / 456. These are contract calculations; actual
market availability and values have not been examined by this implementation.

The producer checks the complete, ordered 00/08/16 UTC event grid before storing.
The consumer independently checks original Feather continuity, finite values and
the native 2026.7 representation: rate in `open`, other OHLCV columns zero. The
existing source hashes, Profile, exact source window and consumer receipts remain
bound. Missing, duplicate, off-grid or already hourly-filled source data fail.
Native hourly fill can manufacture a zero on a missing settlement slot, so the
strategy's recovery of the event grid is valid only after those original-source
checks. Real zero funding remains a valid event.

At a closed 00:00 UTC 5m bar, R1 requires a 24h close return <= -2%, 289 valid
price/volume candles, contiguous UTC time and valid funding. Native next-open
entry is 00:05. Funding means the D-48/-40/-32h settled events, selected via
native 1h→5m merge and a 288-candle shift. Both variants use identical guards.
The two-day funding burn-in is inside Search and is separate from price pre-roll;
the first possible decision for March 1 data is March 3 at 00:05. At least 32h
settlement lag is a conservative historical assumption. Archive publication
timing remains `UNKNOWN`.

Exit is the closed 08:00 bar, executed at 08:05. Stoploss is -3%, ROI is disabled,
and the source has no pyramiding, long signal, intraday re-entry or custom exit.
The actual funding cashflow is still calculated by native Freqtrade during the
position. Signal funding and cashflow funding are different observations.

## Verification and limits

- T0/T1: fixed-template mutations, shared guards, exact one-factor comparison,
  request/metadata downgrade attempts, original-source failure before publication,
  and existing NY/daily/exploration/generation/Search/Development regressions.
- T2 HTTP: a clearly synthetic fake Codex executable through the real local
  generation, preview/approval and parent API; only temporary SQLite. No real
  model response or model provenance is claimed.
- T2 native: `tests/native_lagged_funding_gate.py OUTPUT_ROOT NATIVE_CHECKOUT`,
  run by the pinned 2026.7 Python with `PYTHONDONTWRITEBYTECODE=1`. It creates
  only synthetic input, snapshots the unchanged native package, and invokes the
  existing SHA-bound `scripts/run_freqtrade_backtest.py` subprocess, including
  `Backtesting.start` and original native ZIP export. Runtime evidence stays
  outside Git. Normal 480-minute holds, 55-minute stop, signed positive/negative
  funding, shared availability, future invariance, consecutive days and the final
  complete day are checked. Initial probe setup failures are retained.

The family currently requires exploratory Generation. Its Candidate cannot enter
Development even if a future unseen window is available. If an economic finalist
later exists, the next step is a separately authorized, frozen independent
validation protocol and a narrowly scoped handoff that preserves source SHA,
trial history and exposure metadata. That handoff is not implemented here; do not
remove exploration labels, manufacture a ResearchRun or reuse consumed windows.
No real-market acquisition, economic backtest, formal Candidate/ResearchRun,
Holdout, release or trading was run for this delivery. Engineering PASS says
nothing about strategy profitability or qualification.
