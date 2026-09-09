# Issue #58 terminal data audit: BLOCKED_DATA

The frozen Issue #57 funding window cannot be repaired by timestamp normalization. No production code was changed and no PR is warranted. Issue #57 remains terminal and must not be replayed.

Audit Issue: https://github.com/He1met/freqtrade-lab/issues/58

Current checkout and live remote main (checked at start and finish): `47f608b41354fab755616d86591bd774fa1674a0`; clean detached HEAD; no staged/unstaged/untracked repository changes. No commit, push, branch change, PR, or merge occurred.

Exact Git-external root: `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-58-funding-data-audit/audit-v1.0xdhtp37`; mode `0700`, device/inode `16777234/61648358`.

Evidence manifest: `evidence-manifest.json`, SHA-256 `2479efc2e1c713fa7a17a5807ed017f3dde3791826f23d5836ab7cc4605f227c`. It binds the audit scripts, untouched ZIPs, raw catalog requests/responses, per-month JSON integrity results, timestamp-only progress, and isolated replay evidence. Report excluded to avoid circular hashing. Production helper SHA-256 `017b348b5ad6ea700ec23719f4285e4f3092bd999c44955c0ac8515609e2dee7`.

## Decisive evidence

1. March's exact rejection is the **>2000ms branch**, not local-month mismatch. CSV line 2 has instrument `SOL-USDT-SWAP`, timestamp `1646064003000` = `2022-02-28T16:00:03Z`; UTC+08 gives March 1. Offset=3000ms. March has 93 rows and offsets `2000:4, 3000:66, 4000:14, 5000:5, 6000:3, 7000:1`. The 1443-byte ZIP SHA is `d59393d13949143506e31a94f33781d7dea5b803572150ad8cdbf7d62de926c8`; a separate second GET returned byte-identical content. Unchanged producer code reproduced `funding archive month 2022-03 timestamp drifted` offline.
2. Independent of the drift rule, **57 required observations are absent**. After diagnostic flooring only, the research window has 2133 of 2190 expected timestamps, zero collisions/duplicates, and these missing segments:
   - 47: `2022-01-01T00:00:00Z` through `2022-01-16T08:00:00Z` inclusive.
   - 10: `2022-02-22T08:00:00Z` through `2022-02-25T08:00:00Z` inclusive.
   January local month has 45/93 rows (48 missing includes one pre-Search grid point); February has 74/84. Timestamp transformations cannot manufacture missing funding observations.
3. December has large, non-millisecond-scale delays: CSV line 55 `1671353595000` = `2022-12-18T08:53:15Z` (offset 3,195,000ms), and line 56 `1671389647000` = `2022-12-18T18:54:07Z` (offset 10,447,000ms). Diagnostic flooring maps these to 08:00 and 16:00, but exact grid continuity does not prove that advancing them by 53m15s or 2h54m07s preserves settlement/accounting semantics.
4. All 2023 month archives exceed the current 2000ms rule. Therefore this audit does not establish a usable later 2023 window under the existing producer.

## Integrity and causal interpretation

The original timestamps are 13-digit ASCII strings, interpreted as Unix milliseconds; this produces the correct year/month and UTC+08 membership. All 24 full research-month archives contain exactly one correctly named CSV with the expected header and exact instrument, finite rates, strictly increasing timestamps, zero raw duplicates, and zero local-month mismatches. Every timestamp has whole-second granularity. Raw exact-grid continuity fails where offsets or absent records exist; diagnostic floor continuity is complete from March 2022 onward but not January/February. Full distributions, raw adjacent-delta counts, first/last rows and all anomalous timestamp lines are recorded in each `YYYY-MM.json`. Rates are not printed in audit outputs.

Instrument identity is verified in every inspected row; historical listing/lifecycle completeness remains UNKNOWN. The February interior gap proves the required source sequence is incomplete regardless of the earlier listing boundary. No API error, parse-unit error, or time-zone explanation accounts for the 57 absent rows. Byte stability was checked twice for March only; permanent archive immutability and repeat stability for other months are UNKNOWN.

The [official archive page](https://www.okx.com/historical-data) currently advertises funding history from March 2022 onward, consistent with caution about earlier partial files. The [official funding mechanism](https://www.okx.com/en-us/help/perps-funding-fee-mechanism), updated 2026-08-27, distinguishes the default scheduled grid from actual fee assessment and notes that positions opened during delayed assessment can still be charged. This current document does not establish the exact semantics of the 2022 CSV field or justify retroactive rounding. The API documentation lookup did not establish an archive-specific `funding_time` definition. Archive period-label versus actual settlement/availability semantics remain UNKNOWN. No claim is made that all observed delays reflect an exchange incident or corruption.

No generic causal-safe normalization rule has been proved. Increasing the cap to the largest observed offset would be threshold fitting and would still leave 57 records missing. A faithful actual-timestamp path would require separately scoped producer/consumer/engine alignment and boundary-accounting evidence; it cannot solve this window's missing source observations and is not implemented here.

## Protected boundary

Current producer funding begins at Search start `2022-01-01`, not the price pre-roll date `2021-11-02`. The required last UTC funding point belongs to the local January 2024 archive. Under explicit supervisor authorization, the boundary selector checked instrument/timestamp first, immediately skipped timestamp >= `2024-01-01T00:00:00Z`, and only then accessed/converted the selected rate. The one selected row is CSV line 2: `1704038404000` = `2023-12-31T16:00:04Z`, finite, offset 4000ms. The 92 protected rates were not converted, validated, statistically analyzed or output. Their finiteness and full-month integrity remain `UNKNOWN / SEALED_UNREAD`. Raw ZIP and CSV bytes were hashed without publishing decompressed protected values. No candle, mark, signal, performance or Holdout/Stress result was requested or inspected.

## Monthly outcome

Missing below refers to the entire local month except the explicitly selected January 2024 boundary. PASS offset alone is not a data-readiness claim.

| Local month | Rows | Offset min..max ms | Missing diagnostic grid | Current producer |
|---|---:|---:|---:|---|
| 2022-01 | 45 | 0..0 | 48 | PASS offset only; INCOMPLETE |
| 2022-02 | 74 | 0..0 | 10 | PASS offset only; INCOMPLETE |
| 2022-03 | 93 | 2000..7000 | 0 | REJECT >2000ms |
| 2022-04 | 90 | 3000..5000 | 0 | REJECT >2000ms |
| 2022-05 | 93 | 3000..8000 | 0 | REJECT >2000ms |
| 2022-06 | 90 | 2000..6000 | 0 | REJECT >2000ms |
| 2022-07 | 93 | 3000..8000 | 0 | REJECT >2000ms |
| 2022-08 | 93 | 3000..9000 | 0 | REJECT >2000ms |
| 2022-09 | 90 | 3000..7000 | 0 | REJECT >2000ms |
| 2022-10 | 93 | 3000..8000 | 0 | REJECT >2000ms |
| 2022-11 | 90 | 4000..16000 | 0 | REJECT >2000ms |
| 2022-12 | 93 | 5000..10447000 | 0 | REJECT >2000ms |
| 2023-01 | 93 | 9000..16000 | 0 | REJECT >2000ms |
| 2023-02 | 84 | 5000..23000 | 0 | REJECT >2000ms |
| 2023-03 | 93 | 5000..19000 | 0 | REJECT >2000ms |
| 2023-04 | 90 | 5000..20000 | 0 | REJECT >2000ms |
| 2023-05 | 93 | 5000..21000 | 0 | REJECT >2000ms |
| 2023-06 | 90 | 5000..15000 | 0 | REJECT >2000ms |
| 2023-07 | 93 | 5000..7000 | 0 | REJECT >2000ms |
| 2023-08 | 93 | 5000..9000 | 0 | REJECT >2000ms |
| 2023-09 | 90 | 4000..7000 | 0 | REJECT >2000ms |
| 2023-10 | 93 | 3000..24000 | 0 | REJECT >2000ms |
| 2023-11 | 90 | 3000..21000 | 0 | REJECT >2000ms |
| 2023-12 | 93 | 4000..18000 | 0 | REJECT >2000ms |
| 2024-01 boundary only | 1 selected / 92 rates sealed | 4000 | 0 selected | REJECT >2000ms; whole month UNKNOWN |

## Official sources and raw hashes

Catalog: `POST https://www.okx.com/priapi/v5/broker/public/trade-data/download-link`, official unauthenticated public historical-data catalog; request/response bytes and SHA are retained. Despite the `/priapi/` path, this is the existing producer's no-credential public download catalog, not an account/private trading API.

Each file is `SOL-USDT-SWAP-fundingrates-YYYY-MM.zip`, containing the identically stemmed `.csv`; its official URL is `https://static.okx.com/cdn/okex/traderecords/swaprates/monthly/YYYYMM/SOL-USDT-SWAP-fundingrates-YYYY-MM.zip?v=999`. Exact URL, content headers, timestamps, bytes, ZIP/CSV hash and count are in every per-month JSON. No third-party source was used.

| Month | ZIP bytes | ZIP SHA-256 | CSV SHA-256 |
|---|---:|---|---|
| 2022-01 | 713 | `9a46a07862cdeb4b3e7e8e7a21f2a3b6b9776a34dadf967ba805a40ab587ea72` | `c4b6f7bcc22904e327c7a366abdd0efcf27211a2d6ddd3b410b7a0da9217e29d` |
| 2022-02 | 997 | `a66bb4c86399bbcfaf5ba8e570ddc92837b243e15fa5711951bbc90b550644b5` | `b8c6c0b924d05810978a7a57bb669088792857d23f410cd197ede9b052d3da1a` |
| 2022-03 | 1443 | `d59393d13949143506e31a94f33781d7dea5b803572150ad8cdbf7d62de926c8` | `069f636b5e4c5c72ecfbcbc26bf8367c138b9a167d39d5c4548e9c7b7194d437` |
| 2022-04 | 1396 | `a1ea8f1bf8e915ff93896275258f086454fb92f228f2d39d5ea3b7eeeb6dba24` | `d9445ab5c6c56be0772135bf276a1383f783c7ac5a1bc58509f66c4a60707779` |
| 2022-05 | 1410 | `4da7e44122871e8ad3ad5038d6233f101598d978279fa309080cd91c310c9a1a` | `ca44ea508d88a36130f3c21141fdad012a63357394d6e1ae357d265b7eb40296` |
| 2022-06 | 1397 | `29910979e8226e1a43340f04b1568f5af0e07f438d89e5905abe8359063cc4ee` | `12c76d5f5700d7a552d2ff141e466ef083fe94989e6a70bec9a92df4b6f4568f` |
| 2022-07 | 1436 | `b7b5672a33eaf540d38384584b461dbe94b6260570d6fde29e6df956278cb7ac` | `61d045726b5fcbe1468261e6da6dc77c4dd7f76634ce4386dc7bd44e2fb24afe` |
| 2022-08 | 1443 | `1dce6e631adc6d41102bc13e189daff0b17ac47b58560b1896d0aefcefed7212` | `096db1723727d0d505aac18c30bc4607107de249f4d82eb93bac27b330b5fd47` |
| 2022-09 | 1405 | `bbf867307d9ce1f4106276fbb2eefd2488f7d87857ae40fe2f25d26c6dbab288` | `03a2aa947104c471131e3e22970cde6a8776255e79407dc0f847b540cc4fcc0f` |
| 2022-10 | 1445 | `1d53e6ff9feb72c2c55f50db6a2371608694425f31d8698cdf348b513b30cbc6` | `1d715f46a28cf73dbecf4ec76903db470773d199a198c3fe4dc64bfb6e9905f1` |
| 2022-11 | 1456 | `c164ee6326b52c3df6341f73e5e5079868995f3468955917e3755ae3d7e094fd` | `411001cc7b34b44dda70a66c9ff06e442ae16ef7b75c534c57d8ed05c7a6d9d1` |
| 2022-12 | 1460 | `6ba9ad518b78f79a9e14f4bda28fd8bb092d65398ae333d176d15d78155e5289` | `b5367fe35735fbeea810a3d1f81f65518f2ddcd1e502a10e27711a69a382690e` |
| 2023-01 | 1484 | `ab9b48d82a55dca19999092dba3d0f4d0a172ef4a1e5bf8107ddccb73b1621f2` | `f943241861b5e4633216727d4796b9a241fd53f913cb73dc819a86901aab0f5f` |
| 2023-02 | 1361 | `fceb326a6b7a3b90cbe25ff08eb503265014b58915a21d23540ada4b45369ec1` | `4929d579d1868708b4ecc0b1113e669d836c9446a249076d9a6b1efb4b1d7445` |
| 2023-03 | 1477 | `4a8445fd41d56c303245a8d3af9567a10f648e2e12c1aedb2bd15a7301ab7341` | `2c649e0e5c7617d0933865cb73464ef0c7810037b6de7a1a36c462875b5abcb6` |
| 2023-04 | 1409 | `68b9bc0875e1a6c7ca63c81b72823476b7d585342ccef40b33f0d1660b1efeae` | `cbf6f2d9acaf775610b40f84f8ae987148cf1cfbe62929df29762329028493db` |
| 2023-05 | 1442 | `3cf54d441054faf1bcde8372fb8a8089ea3e6bf70a262560828ed33d3ae01e48` | `932a610c2a3abafafa4a59f4d6336068fb4d1aa0fa2f37eeef021f85d259afd9` |
| 2023-06 | 1394 | `0186eca3175a7fe6a6719580548448e3f61e435de6fe87677d20b95d35d84c08` | `0c28a24245a36ed7e719868864af6a757212c32512b3db820ed4ed4dbb4e6958` |
| 2023-07 | 1429 | `f4a61afc1f38d8c872d4dcc392f098dcc132740d79be08856eb21571ea8fd59e` | `57c9730453aa0ed12815f7a2fc79606c8f2d00f9b3107350fdf37c516604d38f` |
| 2023-08 | 1433 | `84343672e399e4eca6679e19e5b41bedc88de9aa3b38dba3fcadc865fa6d1d27` | `c58379ea24a18826a47e9e37b3651a0c5e1825cbe61dae04a8c58812e81e11cc` |
| 2023-09 | 1395 | `195be90a2fe8e7012dc0057b727b32587631bdddf1e901d8fa247363ca11085a` | `f1f61a0349d4943388ed5c696316024b51a2a77ae2060c8e2026b1872d7d0e2f` |
| 2023-10 | 1448 | `76d6652fa4c27174a843da5d68339b9d9e5e7a25d43ae131959c9b857daba02a` | `8f5e8773393e1a07c1b8c7093084ab3c0f03f89391c1df5ed61f1d2f63db273a` |
| 2023-11 | 1423 | `6e57548ba0bdbe350bf39ff60156770070f464dc9e318cd053204febd473572e` | `4d41ea5509fedc163fc133be7893dbc5698554f8b5de0479c4d8aae05755d7bd` |
| 2023-12 | 1430 | `7c36d0e0d2405249bc93ab80ec12e6283915c2604e07335f675e9d82a07db326` | `60da9e88bf9c4d35cf91d4011c10d7c8239e9b8d21ed174ee23fdf1f81a8f6d2` |
| 2024-01 boundary archive | 1429 | `e96e1dbe68ca1b7f400ea6923a33d5799bd757dcd2b846ace5b2e1721d4c4c81` | `b24d35b8be00f74da41aa0f669737ef1826f9dcee8f3dc2f1b27c8ae3ea63a51` |

## Proportionate verification

- T0 read-only scope: AGENTS, audit skill and two references, #57 and terminal, #52 / PR #54, unchanged producer and tests, HEAD / clean state / live main.
- T1 existing targeted tests: `PYTHONDONTWRITEBYTECODE=1 uv run --with pytest python -m pytest -q -p no:cacheprovider tests/test_fetch_okx_public_data.py -k 'archive_funding_crosses_okx_local_month_and_records_hashes or archive_funding_rejects_timestamp_outside_post_grid_drift_budget'`: **4 passed, 42 deselected**. Temporary synthetic fixtures only.
- Audit isolation checks completed before the boundary GET: five poisoned protected-rate variants skipped, exactly one permitted conversion, two invalid identity/timestamp cases rejected before rate conversion.
- Exact offline March replay: original function bodies extracted through AST from the hashed producer; zero network, no database, no runtime/acquisition entrypoint. PASS expected rejection on exact line/branch.
- T2 data evidence: 25 required official month files (24 full research months, one restricted boundary) plus one repeat March download; global timestamp-only integrity check. `git diff --check` passed.
- No production repair, so no new product tests, full suite, atomic-cleanup rerun or actual acquisition publication. Prior #57 cleanup/database counts are historical terminal evidence, not re-read here. T3 strategy/engine/Search/Development tests were not run. Tests are not economic evidence.

## Decision and next bounded route

Close #58 as `BLOCKED_DATA / NO_PROVABLE_SAFE_REPAIR_FOR_FROZEN_WINDOW`. The data audit has completed with a negative result; this is not delivery of a runnable dataset and not a research verdict. No production code diff, PR or retry of #57.

A possible separately preregistered route is a new SOL window with *all data including pre-roll* after the protected January 2024: for example data_start `2024-02-01`, Search `[2024-04-01,2025-04-01)`, Development `[2025-04-01,2026-04-01)`, and separately sealed Holdout `[2026-04-01,2026-05-01)`. The 60-day date arithmetic is exact. This is only a prospective candidate: canonical consumption/overlap status, complete funding source, listing coverage, causal semantics and current producer compatibility are UNKNOWN and must pass a new supervisor-led pre-registration/data gate before research. No values from that proposed route were fetched. The existing January 2024 Holdout is not reused even for pre-roll.

No cohort/Profile/database/Candidate/campaign/Search/Development/strategy signals/PnL/Holdout-Stress/Judge/Release/Demo/live trading, credentials, funds, schema changes, service, runner, or consumer changes occurred. Runtime roots and sensitive databases from #57 were not opened. Only this Issue's private audit files were created; no normalized acquisition was published. #57 historical attempts=0 and campaign=NULL remain historical evidence; current runtime counts are UNKNOWN in this isolated audit.
