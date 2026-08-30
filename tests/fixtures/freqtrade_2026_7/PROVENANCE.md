# Freqtrade 2026.7 OKX futures fixture provenance

This directory contains one frozen parser-compatibility fixture. It is evidence
for the supported artifact shape and database import contract only. It is not
evidence that the strategy is profitable, deployable, or suitable for trading.

The machine-readable binding is
`backtest-result-2026-08-30_12-55-02.provenance.json`. The values below are a
human-readable audit trail of the same Gate.

## Pinned software

- Upstream: Freqtrade, tag `2026.7`
- Git commit: `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`
- Actual `freqtrade --version`: Freqtrade 2026.7, Python 3.13.13,
  CCXT 4.5.68 on macOS 26.5.2 arm64
- Data/export dependencies: pandas 3.0.3, pyarrow 25.0.0
- Upstream license: GPL-3.0-only; the upstream license text is retained as
  `UPSTREAM_LICENSE.txt`.

The checkout and virtual environment were created in a new temporary Gate
directory. Dependency installation used a local package cache in offline mode;
nothing was installed into the user's global Python.

## Public OKX acquisition

Acquisition ran from `2026-08-30T04:50:32.905588Z` to
`2026-08-30T04:50:37.946036Z` with an empty environment and temporary HOME.
It used no authentication and made only public HTTPS GET requests to
`www.okx.com` for:

- instrument `XRP-USDT-SWAP`;
- its isolated position tiers;
- 5m futures candles;
- 1h mark candles;
- funding-rate history.

The fixed landed-data window was
`2026-07-31T22:00:00Z <= timestamp < 2026-08-04T00:00:00Z`.
The extra two hours before the configured backtest start supplied the official
strategy's startup candles. All regular candles were already closed.

| Evidence | Rows | Start UTC | End UTC | SHA-256 |
| --- | ---: | --- | --- | --- |
| 5m futures Feather | 888 | 2026-07-31 22:00 | 2026-08-03 23:55 | `b5505131ff772fae1f70bd27768edce9070f668baf2e4cfa9e07e4d9c2435ddc` |
| 1h mark Feather | 74 | 2026-07-31 22:00 | 2026-08-03 23:00 | `7bbb7dbe92cf7be0300b7d0ad0e819fefa7766198af789d462c5b8589c2d3fa7` |
| funding Feather | 9 | 2026-08-01 00:00 | 2026-08-03 16:00 | `edc079c68bf79081cb382a82935b2c5ce7e70f286ac8424e63cb62ef6b395eac` |

The acquisition checks found zero duplicate 5m/mark rows, zero missing regular
candle intervals, zero unclosed candles, and no funding timestamp outside the
fixed window. The raw public response hashes and exact URLs are retained in the
same-stem machine-readable provenance. The complete retrieval receipt SHA-256
was `9bc537633ba444f9d47f14143c8aab2dbc1dabba4065a1a518ee01a31b02f6e5`.
Raw responses and Feather data are not tracked in this repository.

## Offline generation

The configured parser-fixture contract was:

- exchange `okx`;
- `trading_mode=futures`, `margin_mode=isolated`;
- pair `XRP/USDT:USDT`;
- timeframe `5m`, no detail timeframe;
- timerange `20260801-20260804`;
- `dry_run_wallet=1000.0`, `stake_amount=100.0`,
  `max_open_trades=1`;
- explicit `fee=0.0005`;
- official `StrategyTestV3Futures` source, SHA-256
  `db2d416b5d40daf2dcd8ef8c07a937053c846ca89a9fca1f01facab60dfadc2d`.

The fee is a configured parser-fixture assumption used to test cost/scenario
identity. It is not an observed or public OKX account fee rate.

Before starting Freqtrade, the real OKX exchange adapter was rehydrated only
from this Gate's public instrument and isolated-tier snapshots (SHA-256
`0eff7c426f0a56bec3fa18e03357bea23e8b8837202b0930e8cb1edfcb4e3f29`
and
`5630472ad69a4fb5714144415dfc142039850b67e449453c4c22e1dfa815f9db`).
No generic `patch_exchange`, market fabrication, result stub, or stats wrapper
was used.

Generation then ran under an explicit `sandbox-exec` profile containing
`(deny network*)`. The ephemeral command shape was:

```bash
sandbox-exec -f deny-network.sb env -i \
  HOME=<gate-root>/home TMPDIR=<gate-root>/tmp \
  PATH=<gate-root>/venv/bin:/usr/bin:/bin \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<gate-root>/source \
  <gate-root>/venv/bin/python <gate-root>/run_offline_backtest.py
```

The harness called the official, unmocked
`Backtesting.start`, `Backtesting.backtest_one_strategy`,
`Backtesting.backtest`, statistics generator, and
`store_backtest_results`. The one-shot acquisition/generation scripts and
environment are not retained in the repository.

The first offline invocation stopped before the core because the Freqtrade
`_markets` cache had not been hydrated and the sandbox rejected its attempted
reload. It produced no artifact. The cache wiring was corrected using the same
already-hashed public snapshots, pair, and time window; the successful
invocation did not require network access.

The successful report covers `2026-08-01 00:00:00` through
`2026-08-03 23:55:00`, never preceding the available funding evidence. It has
11 trades with wins/draws/losses `8/0/3`; every trade uses the exact pair and
has finite `fee_open=fee_close=0.0005`.

## Raw exporter output and deterministic sanitization

- Raw ZIP:
  `58e37c79376fcaf26023930a4ca3ffadd664c7144a16618d7289a40a05e10452`
- Raw same-stem meta:
  `e4afe038fc5a358530fe6aff8f11dc84874d60e057d4e02da839fee6f138ee2c`
- Unchanged report member:
  `5fd2bc38f4d583640a1795dba023fb4e83d82a55a6bd664009a51533c8b66674`
- Raw config member:
  `c5d9212a263893c64f01ac04b99a4509383ba76641ca8f6edb4864924b322ba7`
- Unchanged strategy member:
  `db2d416b5d40daf2dcd8ef8c07a937053c846ca89a9fca1f01facab60dfadc2d`

Only private temporary paths were transformed in config:

| Field | Sanitized value |
| --- | --- |
| `config_files` | `["gate_config.json"]` |
| `datadir` | `"data/okx"` |
| `exportdirectory` | `"backtest_results"` |
| `strategy_path` | `"strategies"` |
| `user_data_dir` | `"user_data"` |

No credential keys were present. All exchange/mode/pair/timeframe/timerange/fee,
wallet/stake/max-open-trades fields were preserved. The sanitized config member
SHA-256 is
`74454e4aa319358dba1e15d506d5fe3436c00935090654cff01abbb5276a58f8`.

The raw market-change and wallet Feather members were removed because Issue #2
does not parse them. The final ZIP was rebuilt with exactly report, sanitized
config, and strategy source in that order, stored without compression, with
1980-01-01 timestamps, regular-file mode 0644, no extras, and no ZIP comment.
The report, metadata, and strategy bytes were unchanged.

## Final tracked evidence

- Final ZIP:
  `f8a064d3910435aecbe5a612211376c390d67912b856b4a19a403af31229efe9`
- Same-stem meta:
  `e4afe038fc5a358530fe6aff8f11dc84874d60e057d4e02da839fee6f138ee2c`
- Same-stem provenance:
  `132b65ebdf236940a2da645ec1ef26c1b23aedc5287416ad021b725da0648d3b`
- Upstream license text:
  `589ed823e9a84c56feb95ac58e7cf384626b9cbf4fda2a907bc36e103de1bad2`

Final checks passed for ZIP CRC, duplicate members, traversal/absolute member
paths, encrypted or non-regular members, compression ratio, unexpected binary
members, JSON readability, member/provenance hashes, credentials, usernames,
private absolute paths, and retained Gate directory names.
