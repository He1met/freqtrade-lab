# Issue #9 producer input provenance

`PORTABLE_RETAINED_FIXTURE=BLOCKED_LICENSE`

This directory intentionally does **not** redistribute OKX OHLCV, mark-price,
funding-rate, market-snapshot, leverage-tier, or raw API-response content.  A
license review found no basis for adding that Market Data to this public Git
repository.  The tracked files are a sanitized Freqtrade config, a fixed
ResearchProfile/Candidate spec, GPL-covered upstream test strategy source, a
manual public-data acquisition/validation helper, exact metadata receipts, and
a receipt for the local-only inputs used during the Issue #9 verification.

The strategy is from Freqtrade tag `2026.7`, commit
`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`, and is covered by the parent
fixture license [`../UPSTREAM_LICENSE.txt`](../UPSTREAM_LICENSE.txt)
(`GPL-3.0-only`).  Its retained bytes were not modified.

## Public source boundary

Both acquisitions used `authentication=none`, host `www.okx.com`, instrument
`XRP-USDT-SWAP` (`XRP/USDT:USDT`, linear USDT-settled perpetual swap), and only
the following HTTPS GET requests.  The tracked receipts contain URL, fetch
time, response byte count/SHA-256, coverage statistics, and landed-file hashes;
they do not contain response bodies.

Development acquisition: started
`2026-08-30T04:50:32.905588+00:00`, finished
`2026-08-30T04:50:37.946036+00:00`, data window
`[2026-07-31T22:00:00Z, 2026-08-04T00:00:00Z)`.

- `https://www.okx.com/api/v5/public/instruments?instType=SWAP&instId=XRP-USDT-SWAP`
- `https://www.okx.com/api/v5/public/position-tiers?instType=SWAP&tdMode=isolated&uly=XRP-USDT`
- `https://www.okx.com/api/v5/market/history-candles?instId=XRP-USDT-SWAP&bar=5m&limit=300&before=1785535199999&after=1785625200000`
- `https://www.okx.com/api/v5/market/history-candles?instId=XRP-USDT-SWAP&bar=5m&limit=300&before=1785625199999&after=1785715200000`
- `https://www.okx.com/api/v5/market/history-candles?instId=XRP-USDT-SWAP&bar=5m&limit=288&before=1785715199999&after=1785801600000`
- `https://www.okx.com/api/v5/market/history-mark-price-candles?instId=XRP-USDT-SWAP&bar=1H&limit=74&before=1785535199999&after=1785801600000`
- `https://www.okx.com/api/v5/public/funding-rate-history?instId=XRP-USDT-SWAP&before=1785535199999&limit=100&after=1785801600000`

Holdout acquisition: started `2026-08-30T06:42:33.103528+00:00`, finished
`2026-08-30T06:42:34.331593+00:00`, data window
`[2026-08-03T22:00:00Z, 2026-08-07T00:00:00Z)`.

- `https://www.okx.com/api/v5/public/instruments?instType=SWAP&instId=XRP-USDT-SWAP`
- `https://www.okx.com/api/v5/public/position-tiers?instType=SWAP&tdMode=isolated&uly=XRP-USDT`
- `https://www.okx.com/api/v5/market/history-candles?instId=XRP-USDT-SWAP&bar=5m&limit=300&before=1785794399999&after=1785884400000`
- `https://www.okx.com/api/v5/market/history-candles?instId=XRP-USDT-SWAP&bar=5m&limit=300&before=1785884399999&after=1785974400000`
- `https://www.okx.com/api/v5/market/history-candles?instId=XRP-USDT-SWAP&bar=5m&limit=288&before=1785974399999&after=1786060800000`
- `https://www.okx.com/api/v5/market/history-mark-price-candles?instId=XRP-USDT-SWAP&bar=1H&limit=74&before=1785794399999&after=1786060800000`
- `https://www.okx.com/api/v5/public/funding-rate-history?instId=XRP-USDT-SWAP&before=1785794399999&limit=100&after=1786060800000`

## Local-only merge audit

The two already-acquired Gate datasets were read with Freqtrade `2026.7`,
Pandas `3.0.3`, and PyArrow `25.0.0`.  For each series, the audit required the
same six columns and dtypes, sorted by `date`, proved that every overlapping
row was value-identical (including null equality), concatenated the two
frames, performed a stable date sort, removed duplicate timestamps while
keeping the first identical row, reset the index, and wrote Freqtrade-compatible
Feather with LZ4 compression level 9.  A reread had to match exactly.  Final
timestamps were unique and strictly regular: 5 minutes for futures, 1 hour for
mark, and 8 hours for funding.

| Local-only file | Rows | UTC range (inclusive) | Source overlap | Bytes | SHA-256 |
| --- | ---: | --- | ---: | ---: | --- |
| `data/okx/futures/XRP_USDT_USDT-5m-futures.feather` | 1,752 | `2026-07-31T22:00:00+00:00` to `2026-08-06T23:55:00+00:00` | 24 | 45,866 | `7b4590559e57056585a11e3ca7730b79cec4113a064f97cd6f4edc06c65545ee` |
| `data/okx/futures/XRP_USDT_USDT-1h-mark.feather` | 146 | `2026-07-31T22:00:00+00:00` to `2026-08-06T23:00:00+00:00` | 2 | 8,330 | `350fba0cf91a0acfc1038aa9c18af8026abb9703a4b438b4082f66d0760adc50` |
| `data/okx/futures/XRP_USDT_USDT-1h-funding_rate.feather` | 18 | `2026-08-01T00:00:00+00:00` to `2026-08-06T16:00:00+00:00` | 0 | 3,834 | `f746edcaae5d727b3196b47c0f0ef3aee392c45ec53d351508b1111c83f6f3a5` |
| `market_snapshot.json` | n/a | acquired `2026-08-30` | identical across both Gates | 1,690 | `0eff7c426f0a56bec3fa18e03357bea23e8b8837202b0930e8cb1edfcb4e3f29` |
| `isolated_tiers_snapshot.json` | n/a | acquired `2026-08-30` | identical across both Gates | 35,877 | `5630472ad69a4fb5714144415dfc142039850b67e449453c4c22e1dfa815f9db` |

These five local-only inputs total **95,597 bytes**.  They are represented by
hash/size receipts in `retained-data-provenance.json` but are absent from Git.
The producer must receive their actual local paths explicitly and fail closed
unless every hash matches.

## Tracked-file audit

| Tracked file | Bytes | SHA-256 |
| --- | ---: | --- |
| `config.json` | 988 | `8baf9cfc681793e097ab6ae4a6f9158a95ab23e062018b50838a99cb9054ac70` |
| `research-spec.json` | 821 | `5ba01e42486c0b723753e044e000e9f894fa138df872a61ea644fa9ec470ccc8` |
| `strategies/StrategyTestV3Futures.py` | 6,730 | `db2d416b5d40daf2dcd8ef8c07a937053c846ca89a9fca1f01facab60dfadc2d` |
| `fetch_okx_public_data.py` | 23,829 | `5f9bed4f63a31c333e4ab0c6f0d8d72410865443d2980e52572db084707c9dd2` |
| `sources/development-retrieval-receipt.json` | 4,230 | `9bc537633ba444f9d47f14143c8aab2dbc1dabba4065a1a518ee01a31b02f6e5` |
| `sources/holdout-retrieval-receipt.json` | 4,391 | `84e380b847a46255841d85864ca97c388d373b429067c80e1e82604459c94e4d` |

The six files in the provenance `files` map total **40,989 bytes**.
`retained-data-provenance.json` is 4,248 bytes with SHA-256
`d1f409eacf939cce313adf83486d18072863cca9a94b84a7faad97f5024f170a`;
the tracked payload plus that receipt totals **45,237 bytes**, excluding this
narrative file.

`fetch_okx_public_data.py` is manual and networked by design.  It requires an
explicit new output directory outside this repository, accepts no credentials,
blocks every non-allowlisted request before network I/O, hashes but does not
retain raw response bodies, validates the exact Python/dependency versions plus
clean Freqtrade tag/commit and series continuity, and deletes its own new output
directory on failure.  On success it also copies the sanitized config/spec/GPL
strategy/license and writes a matching local `retained-data-provenance.json`, so
that output directory is directly usable by the producer after review.  A
future acquisition may differ from the reviewed hashes and must be reviewed as
new evidence.

The exact original Development process argv was not retained and is therefore
`UNKNOWN`; the Holdout execution receipt contained private temporary paths and
is intentionally not redistributed.  The safe, user-initiated reacquisition
interface retained here is:

```sh
PYTHONDONTWRITEBYTECODE=1 <freqtrade-2026.7-python> \
  tests/fixtures/freqtrade_2026_7/producer/fetch_okx_public_data.py \
  --output-root <new-directory-outside-repository>
```

This command is not part of offline regression and must never run implicitly
from a test.  It prints both the retrieval-receipt and local-provenance paths and
SHA-256 values.  The generated directory remains local-only and must not be
added to Git.

This fixture metadata proves only that a bounded technical producer/import
regression can be checked against explicit local inputs.  It does **not** prove
profitability, a Judge result, Release qualification, safety for trading, or
tradability.  `verdict` and `scenario_passed` remain unassessed (`NULL`).
