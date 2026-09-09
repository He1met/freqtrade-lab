# LINK_NATIVE_ORDERFLOW_G1_V1 — G1 ONLY, preregistered before archive download

Supervisor authorized only one small data/native compatibility Gate in task 01a06e51-9548-70e3-8933-c5a8b86a879e. This Issue does not authorize G2 integration or any G3 real strategy backtest. #65 is closed; #62 remains untouched. No candidate/profile/database/schema mutation or real PnL/signal scoring.

The January diagnostic and all synthetic results are technical evidence only. The earlier February/March/April research draft is withdrawn before downloading data. The replacement March/April/May calendar below is reserved metadata only and is not authorized for data acquisition or research execution.

## Exact G1 authorization and stop conditions
```json
{
  "name": "LINK_NATIVE_ORDERFLOW_G1_V1",
  "status": "PREREGISTERED_G1_ONLY",
  "executor": "01a06e51-9548-70e3-8933-c5a8b86a879e",
  "supervisor": "01a05dcc-17fd-7972-9177-9fed95e4b07a",
  "root": "/Users/shenjianpeng/.codex/runs/freqtrade-lab/link-native-orderflow-g1-v1/g1-20260904T215103Z",
  "cwd": "/Users/shenjianpeng/.codex/worktrees/dfd5/freqtrade-lab",
  "main": "dc82c61fe8a27a654977344755c088412518d858",
  "started_at_utc": "2026-09-04T21:51:03Z",
  "deadline_utc": "2026-09-05T01:51:03Z",
  "model": "gpt-6-astra",
  "reasoning": "high",
  "service_tier": "UNKNOWN",
  "authorization": "G1 only; no G2 Lab integration or G3 real strategy backtest. No Lab business code, schema, DB, Profile, Generation, Candidate, Search, Dev, H/Stress, Release, credentials, account, live trading, settings, or Freqtrade Ai.",
  "source": {
    "instrument": "LINK-USDT-SWAP",
    "pair": "LINK/USDT:USDT",
    "filename": "LINK-USDT-SWAP-trades-2024-01.zip",
    "url": "https://static.okx.com/cdn/okex/traderecords/trades/monthly/202401/LINK-USDT-SWAP-trades-2024-01.zip?v=999",
    "catalog_directory": "https://www.okx.com/priapi/v5/broker/public/trade-data/download-link",
    "catalog_module": "1",
    "catalog_month": "202401",
    "catalog_size_mb": 40.03,
    "catalog_evidence": "/Users/shenjianpeng/.codex/runs/freqtrade-lab/next-mechanism-discovery-v1-01a06e51/consumption-metadata.json",
    "catalog_evidence_sha256": "d69e27d426111083486fc3b771134380a9981f3f3a7b648fc2db837e5f4521f9",
    "catalog_first_response_sha256": "UNKNOWN_NOT_RETAINED",
    "allowed_downloads": 1,
    "redirects": false,
    "compressed_limit_bytes": 67108864,
    "uncompressed_csv_stream_limit_bytes": 536870912,
    "download_timeout_seconds": 900,
    "selected_utc": [
      "2024-01-30T00:00:00Z",
      "2024-01-31T00:00:00Z"
    ],
    "excluded_rows": "Read timestamp first; do not interpret excluded price, size, side or trade metrics. Record original full ZIP exposure and actual timestamp coverage separately.",
    "timestamp_rules": "Only exact Unix milliseconds or explicitly UTC/offset-qualified timestamps, or a format whose UTC semantics are confirmed by official archive documentation. Unproven naive timestamps fail; no guessed timezone or alignment.",
    "semantic_checks": [
      "instrument exact",
      "trade ID identity and duplicates",
      "timestamp unit UTC and date membership",
      "archive side is taker, not inferred from OHLCV",
      "archive size unit and native contracts/amount/contractSize semantics",
      "native parser/converter and handler roundtrip"
    ],
    "real_data_forbidden": [
      "price/return summary",
      "signals",
      "strategy scoring",
      "PnL/backtest",
      "OHLCV/mark/funding downloads"
    ]
  },
  "withdrawn_draft": {
    "search": [
      "2024-02-01",
      "2024-03-01"
    ],
    "development": [
      "2024-03-01",
      "2024-04-01"
    ],
    "holdout": [
      "2024-04-01",
      "2024-05-01"
    ],
    "status": "WITHDRAWN_BEFORE_ANY_NEW_DATA_DOWNLOAD"
  },
  "future_metadata_only": {
    "search": [
      "2024-03-01T00:00:00Z",
      "2024-04-01T00:00:00Z"
    ],
    "development": [
      "2024-04-01T00:00:00Z",
      "2024-05-01T00:00:00Z"
    ],
    "holdout_and_stress": [
      "2024-05-01T00:00:00Z",
      "2024-06-01T00:00:00Z"
    ],
    "pre_roll_start": "2024-02-29T00:00:00Z",
    "pre_roll_days": 1,
    "authorized": false,
    "reason": "Pre-value isolation from entire January diagnostic archive; not outcome-dependent window selection",
    "reference_signal_and_economic_gate": "Unchanged from selection.md SHA26a189433769b0ef822c121ff66cb84d34961fbaf211f8c6eeb3dbbd198d861f; no tuning based on G1 prices."
  },
  "native": {
    "root": "/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade",
    "commit": "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5",
    "python": "/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python",
    "version": "2026.7",
    "execution": "Existing native Okx(validate=False,load_leverage_tiers=False) and in-memory synthetic market/tier rehydration as in project offline adapter; native converter/handler/Backtesting only. No custom fill simulator or engine patch."
  },
  "resources": {
    "active_work_limit_seconds": 14400,
    "each_synthetic_timeout_seconds": 300,
    "peak_rss_limit_bytes": 2147483648,
    "measurement": "Ephemeral parent watchdog using psutil RSS (not VMS), aggregate owned child tree polling; os.wait4 native ru_maxrss in bytes on macOS retained. Own child new process group only; TERM then KILL on breach. Report sampled RSS and OS high-water separately. No claim of kernel RSS reservation.",
    "precheck": [
      "timeout terminates exact owned child",
      "small memory-limit test terminates exact owned child",
      "normal child completes and OS RSS available"
    ],
    "on_unenforceable": "BLOCKED_CAPABILITY",
    "on_breach": "STOP_NO_BUDGET_CHANGE"
  },
  "stop_rules": {
    "substantive_failure": "Stop on material format/direction/time/isolation/native mismatch; keep evidence, no alternate asset/day/source, no relaxation.",
    "ordinary_orchestration_error": "May repair bootstrap/path plumbing within original 4h; freeze expectations unchanged, retain attempt/error and code hashes.",
    "unknown": "Critical unresolved source direction/time/unit prevents overall PASS.",
    "final": "One G1 receipt plus short Issue comment; Issue stays OPEN for supervisor. PASS means data/native compatibility only; G2/G3 require new authorization."
  }
}
```

## Frozen SYNTHETIC_TEST_ONLY cases
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

## Successful pre-download SHA manifest
```json
{
  "schema": "G1_PREFLIGHT_MANIFEST_V1",
  "files": {
    "g1-contract.json": {
      "bytes": 5603,
      "sha256": "78092075610f742cb90bc5e68b300d316fa322a3f24718a767299b9844c1dfe0"
    },
    "synthetic-cases.json": {
      "bytes": 4341,
      "sha256": "d9f5fbe4412cd787a014fe3e08c2502a0bbc1e2956540a39a4d5f79c0107133c"
    },
    "LinkTakerAbsorptionControlR1.py": {
      "bytes": 1071,
      "sha256": "2f53392a04fea4e1131742cadcd5c24b8c4fbe62de79b16a18da16c79ed90640"
    },
    "LinkTakerAbsorptionR2.py": {
      "bytes": 1191,
      "sha256": "89bf87f7a20e8362ad7e538cdb8d5f63d68ab145b3d4454763995eef4a9ae917"
    },
    "resource_guard.py": {
      "bytes": 3847,
      "sha256": "d368df1c263d5aaeca3e2b375c73ee25a5de187f5ff5d88145a180aa2b102871"
    },
    "resource-normal.resources.json": {
      "bytes": 783,
      "sha256": "0bdfaca869aef83636e2c3ffe94fe7b0e4f66774fb3eef9948e0eb9cbe1f53d7"
    },
    "resource-timeout.resources.json": {
      "bytes": 764,
      "sha256": "f8c29e32921b36fad01ff4cdb0db59bd6b34fd3e07934a3534148bc2e666617b"
    },
    "resource-memory.resources.json": {
      "bytes": 827,
      "sha256": "4af7131199f2635695ae9ef87b98c5f47a6f8e3180f317f662113e5892a5b9a3"
    }
  },
  "resource_prechecks": "PASS",
  "native_git": "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5",
  "no_archive_download_yet": true
}
```

The resource prechecks completed before download: a normal child was measured; a deliberate timeout and a low-memory-limit child were terminated by the owned-process watchdog. RSS is measured, not virtual memory; polling plus OS high-water are reported honestly, not claimed as a kernel allocation guarantee.

Each critical step must return success independently. Local SHA checks and full remote Issue-body equality must pass before the one authorized ZIP request. Archive/header/UTC/side/unit/size or native substantive failure stops; no replacement sample or relaxed bounds. Ordinary startup plumbing can be corrected within the fixed budget while preserving original frozen test expectations and an error record. Keep this Issue OPEN for supervisor acceptance; never call G1 a strategy pass.
