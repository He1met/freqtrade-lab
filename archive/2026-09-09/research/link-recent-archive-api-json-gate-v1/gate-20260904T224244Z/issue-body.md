# LINK_RECENT_ARCHIVE_API_JSON_GATE_V1

Separate, explicitly supervisor-authorized technical/data Gate only. Start 2026-09-04T22:42:44Z; active and wall deadline 2026-09-05T00:42:44Z (7200 seconds). Sample may only start before 2026-09-05T08:00:00Z; no rolling replacement. Supervisor task 01a05dcc-17fd-7972-9177-9fed95e4b07a. Requested model gpt-6-astra/high, standard/default; actual service tier UNKNOWN, no configuration change.

Private root: /Users/shenjianpeng/.codex/runs/freqtrade-lab/link-recent-archive-api-json-gate-v1/gate-20260904T224244Z
Lab: /Users/shenjianpeng/.codex/worktrees/9ce1/freqtrade-lab; clean detached HEAD and live remote main dc82c61fe8a27a654977344755c088412518d858. Original checkout untracked docs/product-requirements-v1.md preserved.
Native: /Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade; clean 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5 / 2026.7; sibling venv/bin/python and correct native PYTHONPATH.

Prerequisites: private output parents exist; normal, timeout and RSS owned-child guard prechecks pass; freeze SHA manifest and full remote Issue body equality before any catalog/API/ZIP request. Each critical command succeeds independently. No hash-failure chained downloads. 20ms aggregate owned-child subtree RSS polling + wait4 OS high-water, not VMS or kernel hard allocation cap. Max 2GiB; own new process group only TERM/KILL. Single case max 300s; deadline caps every child. Unavailable protection => BLOCKED_CAPABILITY before collection. No daemon.

Requests in strict order, exactly one actual GET each maximum, HTTPS only, no redirects, retries, authentication or fallback:
1. https://www.okx.com/api/v5/public/market-data-history?module=1&instType=SWAP&instFamilyList=LINK-USDT&dateAggrType=daily&begin=1780848000000&end=1780848000000
Catalog <=65536 bytes / 30 seconds. Require success and unique LINK-USDT-SWAP / 2026-06-08 daily archive; filename LINK-USDT-SWAP-trades-2026-06-08.zip, HTTPS static.okx.com host, normal expected CSV ZIP, declared size <=16777216 bytes. Catalog missing/ambiguous/oversized/non-success => STOP. No priapi/month/other day/asset/source. Freeze exact returned URL, filename and raw response SHA in local addendum and full Issue body, read back identical before API.
2. https://www.okx.com/api/v5/market/history-trades?instId=LINK-USDT-SWAP&type=2&after=1780905600000&limit=100
API <=262144 bytes / 30 seconds, exactly 100 unique original trade IDs; exact instrument; all timestamps raw [1780848000000,1780934400000) = [2026-06-07T16:00Z,2026-06-08T16:00Z), strictly <1780905600000; check time before any other market value. Both buy and sell; finite positive Decimal price/size. No before/pagination/changed after. Save private response bytes+SHA, no values in conversation. Failure => stop, no ZIP.
3. Only catalog-frozen URL ZIP GET <=16777216 compressed bytes / 300s. Exactly one full scan <=134217728 cumulative decompressed bytes / 300s, including header and first row through same counted stream. One regular expected CSV member, CRC EOF check. All rows timestamp/ID only except 100 API matching IDs; target row instrument, exact original ID, timestamp, side, Decimal price/size equal API, each ID exactly once. No replacement aggregate IDs. Record full actual UTC min/max and exposure; any range outside frozen raw day => stop without changing range. Persist selected raw and normalized 100 rows+SHA before native plumbing; never rescan.

Real format: isolated new-root files containing exactly matched 100 rows only. Native JSON trades handler store/load exact comparison, dataformat_trades=json exclusively, no Feather/jsongz fallback. Conditional contracts-quantity format only; historical contractSize/base amount UNKNOWN. No real OHLCV/flow/signal/PnL.

Synthetic: SYNTHETIC_TEST_ONLY fixture SHA d9f5fbe4412cd787a014fe3e08c2502a0bbc1e2956540a39a4d5f79c0107133c; R1 SHA 2f53392a04fea4e1131742cadcd5c24b8c4fbe62de79b16a18da16c79ed90640; R2 SHA 89bf87f7a20e8362ad7e538cdb8d5f63d68ab145b3d4454763995eef4a9ae917. Exact fixture copied unchanged with full expectations below. Native JSON configuration only; no strategy/economic formula/fee/stop/ROI changes. FLOW then R1_NORMAL, R2_NORMAL, R2_REJECT_BUY_DOMINATED, R1_STOP, SYNTHETIC_FORCE_EXIT, each substantive execution at most once. Full DataProvider->strategy 42 rows including last candle +1/+2ms trades and all row flow completeness. Native Backtesting and native executed trades required: t+1 open entry / t+2 open exit, 5min; buy dominated R2 zero entries; stop and force expected. No manual fills, alternative runner, native code patch, tail candles, timestamp shifts, weakened assertions or bypass. Synthetic in-memory market/funding metadata from old pure synthetic script permitted, networking forbidden. PnL strictly synthetic only.

Stop at first substantive source/field/time/identity/matching/resource/native completeness/fill mismatch and all later cases NOT_RUN. Ordinary startup/path wiring error only BEFORE target semantic stage may be repaired once within original budget; retain original error and old/new script SHA, never repeat a request, ZIP scan or substantive failed case. No automatic repairs to substantive failure.

No Lab/native code changes, Profile/DB/Generation/Candidate/Search/Dev/H/Stress/Release, real strategy backtest, new market months, OHLCV/mark/funding downloads, native fork, matching replacement, tables/fields/indexes/migrations/services/platform, B/C development, Freqtrade Ai, credentials/accounts/funds/live trading/global settings. Only new root written and exact owned children terminated. #62/#66 stay old OPEN/BLOCKED; #65 stays CLOSED; no old receipt/input/budget/terminal changes and no old January ZIP/selected market reads. No Git commit/push/PR for Git-external evidence.

Possible sample bridge PASS and synthetic compatibility PASS remain separate and local, never full-window READY or economic evidence. Historical contractSize, cross-file schema, full-window JSON resources, funding and causal availability remain UNKNOWN. Future 2024 reserved and 2026 example research calendars metadata only, not authorized. Prior 114 index/77 ledger check identified no LINK date conflict but other assets same calendar exposure; not globally independent market period.

Delivery: one small Git-external receipt plus necessary SHA index, short new Issue comment, leave OPEN for supervisor acceptance. Notify supervisor frozen Issue/root/deadline before requests and terminal promptly. Never enter G2 or real research automatically.

Original evidence verified: decision.md SHA 51ec826676924783b5678e13564d8d1e02f5a51aedeade512deb9d467804aa40; review-metadata.json cb38103798efeb713067c40df063645b564b3f61b6fc2fe0e6c9d042a53d57fc; #66 receipt 864b5d27351e6c7fffe8cc94a64d7a96616eb0b590fd423c06dea43fd9983f9a; final index 32db17b44cb3aeb937751bd3af8ab1fdfd3c26acc2b1bb0c3d9166b3b25e2282.

## Frozen original synthetic expectations
```json
{
  "label": "SYNTHETIC_TEST_ONLY",
  "no_real_values": true,
  "unit": "base amount in native synthetic trade schema",
  "flow": {
    "candles_start": "2000-01-01T00:00:00Z",
    "timeframe": "5m",
    "candle_count": 3,
    "ohlcv": [
      100,
      101,
      99,
      100,
      10
    ],
    "trades": [
      {
        "offset_ms": 0,
        "side": "sell",
        "amount": 7,
        "price": 100,
        "id": "s0"
      },
      {
        "offset_ms": 1,
        "side": "buy",
        "amount": 3,
        "price": 100,
        "id": "b0"
      },
      {
        "offset_ms": 299999,
        "side": "buy",
        "amount": 2,
        "price": 100,
        "id": "b_edge"
      },
      {
        "offset_ms": 300000,
        "side": "sell",
        "amount": 4,
        "price": 100,
        "id": "s1"
      },
      {
        "offset_ms": 300001,
        "side": "buy",
        "amount": 1,
        "price": 100,
        "id": "b1"
      },
      {
        "offset_ms": 600000,
        "side": "sell",
        "amount": 1,
        "price": 100,
        "id": "s2"
      },
      {
        "offset_ms": 600001,
        "side": "buy",
        "amount": 9,
        "price": 100,
        "id": "b2"
      }
    ],
    "expected": [
      {
        "bid": 7,
        "ask": 5,
        "delta": -2
      },
      {
        "bid": 4,
        "ask": 1,
        "delta": -3
      },
      {
        "bid": 1,
        "ask": 9,
        "delta": 8
      }
    ],
    "tail_max_candles": 2,
    "tail_expected": "first candle missing, second and third correct; completeness detector must flag first missing"
  },
  "execution": {
    "label": "SYNTHETIC_TEST_ONLY_NATIVE_BACKTEST",
    "pair": "LINK/USDT:USDT",
    "start": "2000-01-01T00:00:00Z",
    "count": 42,
    "timeframe": "5m",
    "startup": 30,
    "default_ohlcv": {
      "open": 100,
      "high": 101,
      "low": 99,
      "close": 100,
      "volume": 10
    },
    "pulse": {
      "index": 32,
      "close": 101
    },
    "postpulse": {
      "from_index": 33,
      "open": 101,
      "high": 102,
      "low": 100,
      "close": 101,
      "volume": 10
    },
    "native_config": {
      "fee": 0.0005,
      "stake": 100,
      "wallet": 1000,
      "max_open_trades": 1,
      "leverage": 1,
      "stoploss": -0.03,
      "roi": {},
      "trading_mode": "futures",
      "margin_mode": "isolated",
      "use_public_trades": true
    },
    "native_orderflow": {
      "cache_size": 1000,
      "max_candles": 10000,
      "scale": 0.01,
      "stacked_imbalance_range": 3,
      "imbalance_volume": 1,
      "imbalance_ratio": 3
    },
    "cases": [
      {
        "name": "R1_NORMAL",
        "reference": "R1",
        "sell": 8,
        "buy": 2,
        "expect": {
          "count": 1,
          "open_index": 33,
          "close_index": 34,
          "duration_minutes": 5,
          "exit_reason": "exit_signal"
        }
      },
      {
        "name": "R2_NORMAL",
        "reference": "R2",
        "sell": 8,
        "buy": 2,
        "expect": {
          "count": 1,
          "open_index": 33,
          "close_index": 34,
          "duration_minutes": 5,
          "exit_reason": "exit_signal"
        }
      },
      {
        "name": "R2_REJECT_BUY_DOMINATED",
        "reference": "R2",
        "sell": 2,
        "buy": 8,
        "expect": {
          "count": 0
        }
      },
      {
        "name": "R1_STOP",
        "reference": "R1",
        "sell": 8,
        "buy": 2,
        "override": {
          "index": 33,
          "low": 95
        },
        "expect": {
          "count": 1,
          "open_index": 33,
          "close_index": 33,
          "exit_reason": "stop_loss"
        }
      },
      {
        "name": "SYNTHETIC_FORCE_EXIT",
        "reference": "R1 entry with dedicated no-exit test class, not a research variant",
        "sell": 8,
        "buy": 2,
        "expect": {
          "count": 1,
          "open_index": 33,
          "close_index": 41,
          "exit_reason": "force_exit"
        }
      }
    ],
    "assertions": [
      "No adjacent raw R1 or R2 entry signals",
      "No same-row entry+exit collisions for R1/R2",
      "Use native executed trades, not manually computed fills",
      "Any generated PnL is synthetic and excluded from research claims"
    ]
  }
}
```

## Catalog URL freeze before market API (2026-09-04 UTC)
Unique successful official catalog response: LINK-USDT family / SWAP / daily / dateTs 1780848000000.
Instrument identified by exact filename: LINK-USDT-SWAP-trades-2026-06-08.zip.
URL: https://static.okx.com/cdn/okex/traderecords/trades/daily/20260608/LINK-USDT-SWAP-trades-2026-06-08.zip?v=999
Declared sizeMB 1.69 (even conservative MiB interpretation 1772093.44 bytes <16MiB).
Raw catalog response 488 bytes, SHA-256 f558bd128ebf1b26521223894cf68717f52de0c5f98055e128d7f171572ce506.
Actual catalog GET count 1; API/ZIP counts 0 at this freeze. No redirects/retries. The actual archive UTC content remains UNKNOWN until the one authorized scan.


## Verified prerequest SHA manifest
```json
{
  "files": {
    "SyntheticForceExitOnly.py": {
      "sha256": "83e6f6fabf770f028d51704a0aa5512181dffb5d589b7fe726ec55ad3a55dfd0",
      "bytes": 335
    },
    "resource-normal.resources.json": {
      "sha256": "7a67c6f5a6a91580ef1a3f61ca899f03823686f8c78990f251e3c95fde0b8845",
      "bytes": 780
    },
    "resource_precheck.py": {
      "sha256": "946feea7f5060c9f29afddbad5323ad0007694879b501976667c1e37fe7ae68c",
      "bytes": 848
    },
    "run_synthetic.py": {
      "sha256": "f0226fe8f6f223f2969d468cc75289a57d946c50d168e1f7def4630d7df17753",
      "bytes": 10725
    },
    "resource-memory.stdout": {
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "bytes": 0
    },
    "resource-prechecks.json": {
      "sha256": "0dc15b43c3b432028db4cbbff48cb17da2a6be290ee3c44ebefa25b44effd10d",
      "bytes": 2557
    },
    "resource-timeout.stderr": {
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "bytes": 0
    },
    "LinkTakerAbsorptionControlR1.py": {
      "sha256": "2f53392a04fea4e1131742cadcd5c24b8c4fbe62de79b16a18da16c79ed90640",
      "bytes": 1071
    },
    "resource-timeout.stdout": {
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "bytes": 0
    },
    "LinkTakerAbsorptionR2.py": {
      "sha256": "89bf87f7a20e8362ad7e538cdb8d5f63d68ab145b3d4454763995eef4a9ae917",
      "bytes": 1191
    },
    "resource-memory.stderr": {
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "bytes": 0
    },
    "resource_guard.py": {
      "sha256": "1e0a61d8c837dd1a882f97d460c6542c795b8099377966be00341a5994fb1998",
      "bytes": 4093
    },
    "contract.md": {
      "sha256": "e37f9e1d476876631e62e64063446ac4d2f822bece5f68b49485e48e969414c3",
      "bytes": 6913
    },
    "resource-memory.resources.json": {
      "sha256": "d089fa063dedf055ddbc9ed1b9d3b0a55ace8f9530aad412bd3e7295372d8ce6",
      "bytes": 824
    },
    "resource-normal.stderr": {
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "bytes": 0
    },
    "resource-normal.stdout": {
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "bytes": 0
    },
    "synthetic-cases.json": {
      "sha256": "d9f5fbe4412cd787a014fe3e08c2502a0bbc1e2956540a39a4d5f79c0107133c",
      "bytes": 4341
    },
    "acquire_once.py": {
      "sha256": "1b19c412cedd113bac5b18f39da793314619a772dbc66e14952f5d551b9fc59c",
      "bytes": 3128
    },
    "resource-timeout.resources.json": {
      "sha256": "ba0e5a4fe596775717a57fb52135862736cea8bd427f9a07287905f3c67bbd36",
      "bytes": 764
    }
  },
  "verified_frozen_originals": {
    "synthetic-cases.json": "d9f5fbe4412cd787a014fe3e08c2502a0bbc1e2956540a39a4d5f79c0107133c",
    "LinkTakerAbsorptionControlR1.py": "2f53392a04fea4e1131742cadcd5c24b8c4fbe62de79b16a18da16c79ed90640",
    "LinkTakerAbsorptionR2.py": "89bf87f7a20e8362ad7e538cdb8d5f63d68ab145b3d4454763995eef4a9ae917"
  },
  "market_requests_so_far": 0
}
```
