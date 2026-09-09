# LINK_NATIVE_JSON_SCALE_FEASIBILITY_V1

Independent supervisor-authorized synthetic technical scale feasibility only; no research or business-code changes. Supervisor 01a05dcc-17fd-7972-9177-9fed95e4b07a. #67 CLOSED 2026-09-04T22:57:48Z, accepted comment https://github.com/He1met/freqtrade-lab/issues/67#issuecomment-5547388624. Do not restore #66 or rerun #67; #62/#66 preserved, #65/#67 CLOSED.

Start 2026-09-04T23:00:55Z; common active/wall deadline 2026-09-05T00:30:55Z (90 minutes). Wall time conservatively bounds active time; no calendar waiting. Requested gpt-6-astra/high/Standard-default; actual service tier UNKNOWN; no Fast/priority selection or global settings changes.
Root /Users/shenjianpeng/.codex/runs/freqtrade-lab/link-native-json-scale-feasibility-v1/scale-20260904T230055Z is newly created Git-external 0700. Clean detached worktree /Users/shenjianpeng/.codex/worktrees/ae4e/freqtrade-lab. Local HEAD and live remote main independently verified dc82c61fe8a27a654977344755c088412518d858. Original checkout/untracked docs untouched.
Native clean Freqtrade 2026.7 commit 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5 at /Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade; sibling venv/bin/python and explicit native PYTHONPATH. No native handler/DataProvider/strategy/matching modifications.

## Accepted input boundary
Only #67 metadata/source/synthetic evidence. Its receipt.md SHA c466e7eccf4fa4d55b8e8ed93e5e243b889df1a81105696116f2daca9141ea36 and final-evidence.json SHA 1bf70b9a9d2aefb063757c34789b7e88a588696f718fed1d8f36a8a1cc96ef0e verified at exact gate-20260904T224244Z root. bridge-result.json only row/time/SHA metadata if needed. No reading api.raw, zip.raw, selected/api-normalized or real-format market values, any new history, sealed or future candidate data. No market/trading APIs. Original R1/R2/fixture copied unchanged with SHAs in manifest. #67 proves only 100 same-ID bridge, conditional contracts-quantity JSON roundtrip, native FLOW/5 small execution cases. It does not prove historical contractSize/base units, cross-file semantics, complete research, funding/availability or profitability.

## Frozen unique experiment
SYNTHETIC_TEST_ONLY, pair identifier LINK/USDT:USDT, entirely invented price/base-unit quantity. 32 days [2001-01-01T00:00:00Z,2001-02-02T00:00:00Z), 9216 continuous complete 5m candles. Last candle opens 2001-02-01T23:55:00Z. Exactly 9337408 trades = 291794*32. 291794 is one diagnostic-day count, not a guarantee of future average density and not selected research dates.
For candle i=0..9215, n(i)=1013+1[i<1600]; unique global sequential string ID 0..9337407. For j=0..n(i)-1 timestamp=978307200000+300000*i+1+floor(j*299998/(n(i)-1)), strictly inside +1..+299999ms including the last candle. Even j sell, odd j buy. Price=100.0, amount=1.0 synthetic base unit, cost=100.0, type=null. Every candle has both sides. Native 7-field schema [timestamp,id,type,side,price,amount,cost]. OHLCV open/high/low/close=100/101/99/100, volume=n(i). No original fixture, mechanism or expected-case alterations.
Expected for ALL 9216 rows: bid=ceil(n/2), ask=floor(n/2), delta=ask-bid, total_trades=n, R2 sell_share=bid/n. Thus first1600 bid=507 ask=507 delta=0; remaining7616 bid=507 ask=506 delta=-1. Full UTC sequence exact, no missing flow, all original IDs/timestamps/side/price/amount/cost verified from native per-candle output, including last candle internal trades.
Only dataformat_trades=json. Stream legal native JSON once (no fixture list OOM), first compare exact native schema and a separate two-candle synthetic store/load roundtrip; this is new generator validation, not a repeat of #67. At most ONE large generation and ONE substantive large load/process. In ONE owned process original R2 advise_all_indicators -> native DataProvider.trades -> native JSON handler -> native orderflow -> original populate_indicators -> full assertions. Native calls observed without replacing code. No separate large preload, sampling, slicing, shortened window, ID aggregation, alternative runner, manual matching or real Backtesting/PnL. No need to repeat small native execution cases.
Frozen orderflow config unchanged from #67: cache_size=1000, max_candles=10000, scale=.01, stacked_imbalance_range=3, imbalance_volume=1, imbalance_ratio=3. These are native algorithm parameters, not a new cache service. exchange.use_public_trades=true; futures/backtest modes; no exchange connection.

## Frozen independent resource contract
16GiB physical RAM verified, initial memory_pressure -Q free=48%, runs available approximately200GiB. Before EACH launch freshly require RAM16GiB, free>=40%, sufficient disk and root size. If unavailable/unprotectable, do not launch heavy work; BLOCKED_CURRENT_RESOURCES. No system memory changes or unrelated process termination.
Owned-child tree sampled RSS ceiling=4GiB (4294967296 bytes, this new independent task's quarter-RAM contract, not a change to old2GiB Gate). Each generation/processing step max600s, capped by common90min deadline. Root all generated data/logs <=2GiB; generator independently caps main file at1.5GiB leaving headroom. No background service/queue/cache. Reuse audited new-process-group20ms RSS watchdog plus wait4 OS high-water; observe JSON load and full processing same process. Not a kernel hard allocation quota, polling may overshoot and any observed OS/sampled overshoot is failure. Signal only validated owned group identity. Normal/timeout/low-RSS termination prechecks passed, output parents pre-created. Save generation and processing elapsed/RSS separately and all errors.
First substantive time/resource/integrity failure STOP, no changed format/parameters/scale retry. Only ONE ordinary launch/path wiring correction before target semantics is allowed; preserve failed evidence and old/new SHA. No semantic repair, assertion weakening, new execution cases or increased budget. Representative scale failure only establishes failure under THIS fixed scale/resource contract, never inevitable real monthly failure or blanket native-engine incapability. PASS establishes only synthetic scale, never full-window READY.

## Conditional read-only followup (ONLY if scale PASS)
At most20 additional minutes INCLUDED in90min, no new engineering. Identify exact existing Lab source/profile/executor/AST/factor/artifact/Console entrypoints, minimal bid/ask whitelist and binding native use_public_trades/JSON/orderflow settings to existing profile/config JSON; DB remains exactly6 business tables, zero new fields/indexes. State smallest missing user-page segment, with engineering/testing/actual-run effort separate.
JSON ignores TimeRange: minimum producer+consumer contract MUST verify per-stage physical isolated trade files before invocation, no sealed load followed by filtering. Need origin/version/hash/instrument/pair/unit/timeframe/cadence/row count/UTC complete internal trades/causal cutoff and immutable config/source binding; no sealed/future values opened.
Distinguish correct native base amount from R2 ratio invariance under common positive scaling: invariance alone cannot prove historical contractSize or excuse wrong labels. Determine rigorous path using already-available evidence or UNKNOWN without new historical market values. Funding only realized fees, not signal, still needs causal timestamp/rate/mark/position accounting evidence. May consult official OKX/Freqtrade/CCXT documentation/native source only, no market API/history acquisition, bounded lookup. No carry/volatility redevelopment, assets/dates/threshold changes.
Return exactly one directional verdict GO_FOR_SMALL_G2 or NO_GO_WITH_CONCRETE_REASON. No automatic G2 implementation or Search regardless of verdict.

## Delivery and exclusions
One short Git-external feasibility receipt and necessary SHA index; one result comment on this unique Issue, keep OPEN for supervisor acceptance. Notify supervisor Issue/root/deadline before large execution and immediately at completion or substantive BLOCKED, no wait loop. No Lab/native/Freqtrade Ai code writes, runtime business DB/Profile/Generation/Candidate/Search/Dev/H/Stress/Release reads or writes, real strategy research, credentials/accounts/funds/live trading, tables/fields/ORM/services. All generated market values synthetic. No code diff, so no commit/push/PR.

## Frozen source SHA-256 manifest
```json
{
  "local_sources": {
    "launch_step.py": "6b91915c0464d2591466e1932d493abd19724bc44c238d4508d220cfb9c507d8",
    "resource_precheck.py": "946feea7f5060c9f29afddbad5323ad0007694879b501976667c1e37fe7ae68c",
    "LinkTakerAbsorptionControlR1.py": "2f53392a04fea4e1131742cadcd5c24b8c4fbe62de79b16a18da16c79ed90640",
    "LinkTakerAbsorptionR2.py": "89bf87f7a20e8362ad7e538cdb8d5f63d68ab145b3d4454763995eef4a9ae917",
    "resource_guard.py": "6537016e33c161413220931f694e7424467508a5b5dcc8738c0b3303ed2919eb",
    "scale_case.py": "9405fe6464babab955d1dd14f2008e226638eabaa1e7de56e835eecf92b4ab7e",
    "resource_guard_original.py": "1e0a61d8c837dd1a882f97d460c6542c795b8099377966be00341a5994fb1998",
    "synthetic-cases.json": "d9f5fbe4412cd787a014fe3e08c2502a0bbc1e2956540a39a4d5f79c0107133c"
  },
  "native_sources": {
    "freqtrade/data/history/datahandlers/jsondatahandler.py": "373d9116a530640a641868bf6a9b7e59c2ed04d66357db2d0ac47c8624ce0917",
    "freqtrade/data/history/datahandlers/idatahandler.py": "760d4af8dbbf341e2bc4a4c6b1aa87ceed32040bc919c51141d5f38bf0cd4c90",
    "freqtrade/data/converter/trade_converter.py": "56973212f1502a2eac8cbc508092731deb2bfb4501d7ceefe736e21bc25c0746",
    "freqtrade/data/converter/orderflow.py": "ab897e7cd5bcd5745c1f255619cf0a2ce565812bd3dc08784f34a49ef85b3a57",
    "freqtrade/data/dataprovider.py": "b13c8b966fc28790b1e0881ee7da9ad59d1df065a723d26cf619531d0a860761",
    "freqtrade/strategy/interface.py": "05fbbf06ece8feca6ce276c088508dd2018140aa1f780f5b3bdeb79d242cd19f",
    "freqtrade/constants.py": "018856e3682dfd8f2333c29613008f51d5c2edf57797ec7f32463a9d42d22627",
    "freqtrade/misc.py": "71e307111720704f2736ac24fcfae32870131cfcbc99499cfdf7f7779eaca21b"
  }
}
```
