# Issue #61 terminal: SEARCH_TERMINATED_NO_FINALIST

Completed exactly two real, technically VALID Freqtrade Search attempts on **ADA/USDT:USDT**. Both passed trade-count, positive net, PF, drawdown and ROI-exit gates, but failed the preregistered **average holding >= 10080 minutes** gate. There is no finalist. Development was not executed; ResearchRun/Execution IDs and Development metrics remain NULL/not produced. Holdout and Stress remain **SEALED_UNREAD**. Positive Search returns are in-sample evidence, not profitable/robust/trading-ready qualification.

## Frozen source selection

| Priority | Asset | Outcome |
|---|---|---|
| 1 | ADA/USDT:USDT / ADA-USDT-SWAP | First complete source; selected |
| 2 | SOL/USDT:USDT | Not checked after ADA passed |
| 3 | XRP/USDT:USDT | Not checked after ADA passed |

Only canonical contract/receipt metadata and referenced Issues were used for consumption/seal checks, not old market values for selection. No ADA consumed source/campaign was found within the authorized canonical research inventory. BTC/ETH sources bind other instruments. Old SOL #57 Holdout [2024-01-01,2024-02-01) stays sealed; the new pre-roll begins exactly at 2024-02-01. Failed preparation roots without source/campaign/runtime remain labeled as such with unknown pair where metadata lacks it, not fabricated as executed research.

ADA instrument/listing and official funding-only precheck passed all 2190 required 8h timestamps across 25 local-month archives under unchanged FLOOR_TO_8H_GRID_V1, 0..2000ms. No rate-level/direction/price/PnL selection. The final local 2026-04 archive selected 1 research row; **89 out-of-window rate rows were uninterpreted**, including protected Holdout. Raw source bytes and hashes stay private outside Git.

Official complete producer: 790 1d candles, 18960 mark 1h candles, 2190 funding rows, no missing/duplicate/unclosed candles. Source spans [2024-02-01,2026-04-01). Search [2024-04-01,2025-04-01), Development [2025-04-01,2026-04-01); each independently prepared consumer slice has 425 daily candles, 10200 mark hours and 1095 funding rows, including 60-day candle/mark pre-roll. Holdout metadata [2026-04-01,2026-05-01), 30 days, remains unread. Producer/consumer SHA, UTC, boundaries, source identity, retention and continuity checks passed before Candidates.

## Actual two-attempt results

| Metric | R1 stoploss -0.20 | R2 stoploss -0.10 | Frozen gate |
|---|---:|---:|---:|
| Technical status | VALID | VALID | valid |
| Trades | 18 | 20 | >=4 |
| Net after base fees (%) | 7.442382878 | 7.349504349 | >=1.0 and >0 |
| Profit factor | 1.9010216566 | 1.8798833857 | >=1.10 |
| Max drawdown (%) | 5.0029745680 | 5.0477359535 | <=15 |
| Average holding (minutes) | 6960 | 5976 | >=10080 — both FAIL |
| ROI exits | 0 | 0 | <=0 |

Both engine ZIPs contain funding_fees on every trade; sums are -5.877558723168101 and -5.796835014740528 respectively. All trades are long, leverage 1. Base fee=.0005, starting balance=1000, stake=100, max_open_trades=1; slippage remains UNKNOWN. R2 distinct class, exact R1 parent, exact project single-factor verifier=True and exact source equality except class/stoploss substitutions were checked **before approval**. No invalid/replayed/third attempt, parameter change, gate relaxation, asset switch or artificial finalist.

Existing engine/UI generic capacity remains active=3/hard=6; Issue #61 imposed the stricter two-attempt budget, fully consumed. The terminal closes both round actions; generic unused capacity is not permission for another attempt.

## Identity and entrypoint evidence

- Lab clean execution HEAD and freshly checked live remote main: `dc82c61fe8a27a654977344755c088412518d858`, includes merged #60. No repo changes, commits, pushes or PR required. Existing code SHA was already remote.
- Exact clean Freqtrade 2026.7 Git source `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`, Python3.13.13, ccxt4.5.68, pandas3.0.3, pyarrow25.0.0. Source-bound PYTHONPATH avoided site-packages shadowing. No separate smoke or full test suite; R1/R2 real executions and targeted integrity/AST/API checks are the evidence.
- Root `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-61-data-selected-risk-momentum/cohort-v1.d5s4ilpi`, mode0700. DB `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-61-data-selected-risk-momentum/cohort-v1.d5s4ilpi/lab.sqlite`. Source `source-acquisition`; Search `search-campaign`; independently prepared Development `development-pilot`; runtime `console-runtime` under this root.
- Profile `ada-30d-tsmom-drawdown-risk-off-v1-profile`. Family `ada-30d-tsmom-drawdown-risk-off-v1` from first generation. No HTTP Profile-create route or description column exists; registration used existing `lab.database` connection API, selection stored in existing external controls/Issue without schema expansion.
- R1 generation `c54560d6-d47f-40f9-b1e2-c5126941c08e`; Candidate `de8a6fae-f7d9-49d0-8492-cb87cf1bed5b`; class `DataSelectedRiskMomentumR1`; code SHA `f05cd3d1257d6560493d5df9adb2b2d559d6ac9cdbbde8316176b5873e7c3c92`.
- R2 generation `ac6e9e7e-bfaa-4d32-b10c-f90e34631825`; Candidate `97b91c7b-afc9-4dba-9181-84462bfffb0c`; class `DataSelectedRiskMomentumR2`; code SHA `98c3590deb099ed660ae91392ad50a1bf13b69eea446c8fbaaf7128d0cc97087`.
- Search campaign and MANUAL terminal projection generation ID `a73e70a3-6264-4b8d-973a-1ae667583ff6`.
- Actual console http://127.0.0.1:62110/console; generation/review/Search used existing POST APIs. GET `/api/search/context` and campaign API project both attempts and SEARCH_TERMINATED_NO_FINALIST; DB response/evidence, terminal file and API exactly match. Browser rendering verified, Round1/2 disabled, Holdout disabled. FreqUI is UNAVAILABLE.
- Existing presentation limitation: `/api/research/context` and Development button still display generic APPROVED Candidate READY even with no Search finalist. After verifying source enforcement precedes any mutation, an actual nonfinalist POST returned **409 search_finalist_required**, with zero ResearchRun/Execution or Development child. This negative boundary check is not a Development attempt. No code repair in this research scope.
- Strategy Library API in explicit Search mode returned intentional **404 SEALED_UNREAD**. It was not represented as available.

## Six-table and evidence boundary

`research_profiles=1`, `generation_runs=3` (2 CODEX Candidate generations + 1 MANUAL Search terminal projection), `candidates=2`, `research_runs=0`, `backtest_executions=0`, `releases=0`. Schema remains exactly six tables. SQLite holds Profile/Candidate source, review/lineage and compact Search terminal/attempt/evidence pointers. Large archives, Feather, engine trade ledgers/ZIPs, source receipts, controls, logs and raw artifacts are external with hashes. No credentials/sensitive old DB/funds/live/Freqtrade Ai access.

Key SHA-256:

| Evidence | SHA-256 |
|---|---|
| Source retrieval receipt | 835a81668c33275e596066534ea93820c16bafac1fda90df2816bd6ad01577c5 |
| Source provenance | e88781113fca1dbc9a5863b90987a94c4532f8b994b33e867cbe21c5f2eee611 |
| Search provenance | 580af256659b587de4b9d7faeca9aeea528162190298c181e48e89e4478b8bd8 |
| Development provenance | ebc6c6e0767f9aad4612b2491788904c37f41e4c99c88837932b175465f3a0ff |
| Search terminal | efa43c2141093c4d8ac6273ce542e681a5364849b40d70f3394814fe8b39c366 |
| Trials | 41460b3f485b7d7b6b38f26dd7c45344d3224f7eb64c22b5cad31a3263845bc9 |
| R1 engine ZIP | a86e040c1639bd7f3de8d2b5b16ab47a4107d9a176b15d092c74d270927a40c3 |
| R2 engine ZIP | b6d9048a3058bcdbb41b14e3478d7f8e63f83ebf9b5635f1c22c230e931a6509 |
| Evidence manifest | 3c72dee32b33a7249808a8f1bef769ca0d427dce1782c3aa0f8bae034e778681 |

The research ends at its frozen no-finalist gate. No Development/Holdout/Stress/Release/trading is justified by these results. This cohort must not be replayed or rescued.
