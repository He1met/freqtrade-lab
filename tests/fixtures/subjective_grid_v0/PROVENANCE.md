# Subjective Grid Gate v0 synthetic fixture provenance

This directory contains one deliberately synthetic, frozen contract fixture for
the Subjective Grid Gate v0. It is `SAMPLE_ONLY` evidence for JSON/CSV parsing,
intrabar-path handling, accounting, baseline comparison, and atomic CLI output.
It is not observed market data, a profitable-strategy result, or evidence that
the mechanism is deployable or suitable for trading.

## Source and construction

The fixture was hand-authored for repository regression testing on 2026-09-01.
It contains no exchange response, account information, credential, private API
data, or real-funds activity. The fictional pair is `SYNTH/USDT`.

The single one-hour candle was chosen to traverse both sides of an arithmetic
grid so the deterministic `O-H-L-C` and `O-L-H-C` simulations exercise the
intrabar-path sensitivity contract:

| Timestamp UTC | Open | High | Low | Close | Volume |
| --- | ---: | ---: | ---: | ---: | ---: |
| `2026-01-02T00:00:00Z` | 100 | 110 | 90 | 100 | 1000 |

The decision ticket was declared at `2026-01-01T00:00:00Z`, before the frozen
evaluation window `[2026-01-02T00:00:00Z, 2026-01-02T01:00:00Z)`. This proves
only that the test contract is causally shaped; it is not an external timestamp
attestation that the file existed on that historical date.

## Frozen files

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `ohlcv.csv` | 78 | `c3050ccdd73dee1b7d671a6fa8eb53bf673964931822c5a3151b774ac48bd32f` |
| `decision-ticket.json` | 842 | `e0898036d766ac6b3b596cb8d800d739c2b52dfe8958ddbf7798752f36972d22` |

`decision-ticket.json` binds the exact `ohlcv.csv` SHA-256. The evaluator is
expected to record both the ticket and data hashes in its result. Any byte
change is new fixture evidence and requires updating this provenance document.

## Evidence boundary

The configured fee and slippage rates are test assumptions, not observed
exchange costs. `completed_grid_profit_quote`, `unmatched_inventory_pnl_quote`,
`fees_quote`, `slippage_quote`, `turnover_quote`, `maximum_drawdown`, and
baseline comparisons produced from this fixture are mechanical regression
values only. The fixture must remain `SAMPLE_ONLY`; it must never be presented
as real economic validation or trading authorization.
