# BCH planning evidence and limits

This is public metadata and documentation only. Local code context is clean detached `7ae2b6b6c45cfb57c40a13dccd697ce1c57d08a4`; remote HEAD was not refreshed in this planning turn. No new Issue is active. Issue93 closeout is accepted and was not reopened or re-audited. No protected research outputs or market-value files were opened. Documentation examples are documentation, not fetched historical market observations. Prior Liu–Tsyvinski paper text was already available from the initial selection.

## HTTP inventory

Each actual HTTP intent was appended before sending to `perpetual-planning-http.jsonl`; redirect following and automatic retries were disabled. 13 requests total, <=16. Raw metadata/doc responses are preserved locally under the names below; no linked ZIP/CSV/feed was requested.

| # | Local response name (`perpetual-` prefix) | HTTP / semantic result |
|---|---|---|
|1|instrument.txt|200, BCH-USDT-SWAP identity|
|2|api-docs.txt|200, official API documentation|
|3|fees.txt|200, default spot fee table; NOT BCH perpetual fee proof|
|4|catalog-2022-07.json|200/code50077: next-month exclusive end exceeded catalog's six-month input limit; no archive links|
|5|catalog-2022-07-inclusive.json|200/code0, manually corrected end to last local-calendar day, matching existing producer; all six July–December 2022 filenames returned|
|6|catalog-2023-01-inclusive.json|429/code50011; STOP official catalog requests, no retry|
|7|tardis-metadata.txt|200, provider's `okex` metadata is spot, not selected contract coverage|
|8|tardis-docs.txt|200, spot documentation points to `okex-swap`; one provider only|
|9|fee-help.txt|404, no fee evidence|
|10|funding-help.txt|301, redirect NOT followed, no settlement evidence|
|11|tardis-swap-metadata.txt|200, exact selected contract coverage and incident metadata|
|12|tardis-swap-docs.txt|200, selected venue product channels/access documentation|
|13|tardis-types.txt|200, funding fields refer to next event; no settled-rate column proved|

## Exact source findings

- [Official instruments](https://www.okx.com/api/v5/public/instruments?instType=SWAP&instId=BCH-USDT-SWAP): state live, linear, settleCcy USDT, listTime `1573557408000`, contTdSwTime `1611916860000`; current ctVal 0.1 BCH/contract, ctMult1, lotSz/minSz0.1 contract, tickSz0.1 USDT. These are current metadata, not historical parameter invariants. Instrument grouping is 4. No market price, OI, current funding or volume was requested.
- [Official API docs](https://www.okx.com/docs-v5/en/): ordinary and mark history endpoints describe recent years, not an exact BCH start. Funding history REST is limited to up to three months, insufficient for proposed four-year evidence. Intervals may change among 8/6/4/2/1 hours; documentation explicitly says to determine the interval from event times. Positive settled funding is paid by longs, negative by shorts. No instrument-specific historical event schedule was retrieved.
- Official catalog uses POST `/priapi/v5/broker/public/trade-data/download-link`, module3/SWAP/BCH-USDT. Correct request covers UTC+08 month first day through last day (calendar selection, not economic half-open window). Six filenames match `BCH-USDT-SWAP-fundingrates-2022-{07..12}.zip`; advertised `sizeMB:"0"` is display metadata, not proof files are empty or complete. Detail instId is blank, filenames identify selected contract; current producer strict shape must be checked before acquiring, never loosened merely because a link exists. Other 43 months were not verified. UTC half-open final selected events must be excluded before parsing out-of-window rates from monthly tails.
- [Tardis swap docs](https://docs.tardis.dev/historical-data-details/okex-swap) and [metadata](https://api.tardis.dev/v1/exchanges/okex-swap): exact BCH-USDT-SWAP availableSince 2019-12-27, dataset availableTo 2026-09-06. Trades, derivative_ticker and raw mark-price/funding-rate channels are listed. This is a provider coverage assertion, not continuity validation. Documentation only offers first day monthly samples without an API key; full access/cost is UNKNOWN, no key or payment was accessed.
- [Tardis data types](https://docs.tardis.dev/downloadable-csv-files/data-types): derivative_ticker funding_timestamp is upcoming settlement; funding_rate can change until settlement, and final value immediately before event is described as applied. Therefore records cannot be treated as final settled rates simply by their existence; completeness at each event and exchange corroboration matter. Predicted following-event rates are a different field. Do not backfill gaps with zero, last arbitrary quote or another venue.
- Tardis incident metadata in proposed horizon includes exchange recorder gaps 2022-08-17 09:42–10:13Z, 2023-02-24 09:50–11:20Z, 2024-05-09 07:37–08:16Z (crosses typical 08Z funding), 2025-02-03 01:54–02:09Z, and multiple H gaps including 2026-05-21 00:00–05:16:19Z. “resolved” denotes resumed recording, not repaired historical records. The long 2023–2026 statistics-channel incident explicitly excludes other channels, so it is not treated as a funding outage. Alternate source is credible but not a complete drop-in for this strict contract.

## Occupancy and accounting constraints

Ledger was read only with metadata projections; unchanged98397-byte SHA `2f2e1ee577ca324f82e25f1222058b159cff0949a6b502a43eee9ba58c584205`. No BCH literal hit. BTC/ETH historical 2020–2025 families and protected windows are recorded, so changing their venue/product is not used to reset exposure. First two historical imported records identify Issues32/30 but omit asset identity in those records; no claim of universal no-exposure is made. No outstanding sealed asset windows are released. New proposed BCH dates are not reserved until owner confirms coverage/occupancy and explicitly freezes.

Native pinned exchange.calculate_funding_fees includes both open and close event timestamps and computes amount*open_mark*open_fund, signed by side. Monday00Z entry and Sunday00Z exit can coincide with settlement. Existing FLOOR_TO_8H_GRID_V1 and inclusive endpoint semantics cannot be accepted as exact exchange execution timing without a synthetic boundary/accounting contract. Plan must freeze conservative ambiguity treatment or fail before native run; must not patch native source or add a second price-path runner. If alternative timing cannot be bounded without material economic ambiguity, classify model-fidelity BLOCKED, not profit/no-profit.

Paired roles require bounded existing JSON contract changes: current SINGLE_BASELINE_V1 requires attempts=rounds=1; ordinary round1 can open a child round and ranks candidate profitability. Neither represents a fixed comparison whose only eligible finalist is A. No proposal should merely change the baseline integer to2 or launch two unrelated campaigns on already-consumed S. Both candidates must be preauthorized as one paired experiment before any shared S exposure.

The one-page S gates are researcher proposals, not inherited project acceptance nor user approvals. Primary D/H plan tests A's net performance only; it does not independently replicate the incremental-short contrast. Daily calendar accounting includes zero-exposure days and costs, retains dependence; 28-day blocks and confidence interval diagnostics are not IID trade counts. Equity/short slippage and financing must be traced; adverse stop-gap debit applies only to the unreflected part. Same-path cost sensitivity is not a second native result. If min-lot or historical volume capacity fails, report feasibility failure instead of silently skipping and rescreening a coin.

Proposed coarse capacity check: each entry's500USDT notional must be <=0.1% of preceding closed daily base-volume times that day's Low, with raw OKX contract volume converted through the point-in-time multiplier. This is a feasibility check, not a signal filter or proof of opening-book depth. Opening depth remains UNKNOWN. Either A or B lacking collateral/lot/capacity is reported as such; it is not allowed to silently shrink stake. B's economic loss alone does not cancel the preregistered A run; a technical/source/accounting defect stops both without retry, and any attempt already made remains consumed. Cash and daily MTM use the same independent1000USDT initial capital and fixed500 sizing in both arms; no pooling of PnL or borrowed cash between them.

Estimated engineering2–4 active days is conditional on a validated single-source settlement contract and approved scope; network/calendar waiting is separate. This supersedes the earlier conditional1–2 day rough estimate. No development is authorized by this estimate.
