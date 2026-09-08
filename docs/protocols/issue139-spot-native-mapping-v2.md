# Issue139 spot native mapping V2

This replaces the unimplemented native mapping in execution binding V1 for review. V1/V2 acquisition failures remain failures. The 39 source bytes and V3 inventory identity remain fixed. This is engineering admission evidence only: no market execution or reservation is authorized by this package; qualification and market PnL remain uncomputed.

## Execution and accounting

`run_spot139_native.py` dispatches causal hourly intents into the real pinned Freqtrade `Backtesting._enter_trade`, `_exit_trade`, `_process_exit_order` and `Wallets` spot paths. This is a custom hourly dispatcher around native orders, not a claim that ordinary `Backtesting.start()` or its aggregate statistics implements our base-fee model. It uses real Binance/CCXT objects with cached bound market definitions and network disabled. Installed Freqtrade source is untouched. Strategy callbacks specify frozen stake; native validation remains active. An exact quantity or price mismatch rejects the result, rather than substituting the controller's fill.

Signals see only completed full calendar days (85 days for B; 273 for C). Missing/short days are never compacted or filled. An original archived hourly open is required for every fill; an archived short candle still has its actual open but does not complete a daily signal bar. Fixed prior stop and expiry continue through missing signal history. Slippage is an explicitly disclosed executable-price overlay on that open, rounded up to the current bound tick for buys and down for sells; it is not represented as archived OHLC. All fees, filters, historical precision and dynamic reference-price constraints remain simulation assumptions, not proof of historical exchange acceptance.

The modeled ledger pays buy fees once in received base and sell fees once in quote, conservatively rounded to commission precision. Native spot instead keeps gross inventory and accounts for quote entry fees in realized profit. Native `order.cost` metadata is not the cash actually debited from its dry wallet. The adapter preserves both ledgers:

- Each native gross fill quantity and price must equal the submitted modeled gross order exactly.
- Native gross inventory minus modeled net inventory must equal cumulative modeled base entry fees exactly, per asset. No tolerance is used for this conservation check.
- Modeled cash minus native cash equals native entry quote fees realized on sold units minus modeled sell-fee rounding, plus separately reported native arithmetic/rounding residual. Native profit rounding is also reported separately. Values are never overwritten to make the difference disappear.
- The actual native wallet is independently checked against its own initial cash + native realized profit - native open stake calculation, using exact equality under native float arithmetic. Decimal ideal differences and native arithmetic residuals remain visible; they are not a claim of identical financial results.
- If the model is exactly flat on a lot boundary while native retains the fee reserve, the next cycle adds an actual native entry order to the same native trade. Native weighted entry price is retained for later native fee allocation. A separate synthetic replay covers this case.

Native gross marked inventory contains fee reserves which the modeled account no longer owns. Its cash/PnL therefore must not be combined with modeled net inventory or presented as the strategy's conservative return. The result keeps `native_matching_statistics_identical=false` and `independent_qualification=false`.

## Timing, dust and terminal behavior

C's new midnight volatility reduction is queued for hour+1. If that exact open is absent, the reduction expires; it is not caught up later. Persistent stop/negative-signal/expiry exits remain queued until an actual open. A negative signal re-arms the episode; its subsequent sell does not erase that event. A stop/expiry without a nonpositive event still requires nonpositive then positive before reentry.

A modeled remainder below a valid sell lot/notional remains inventory and globally blocks new risk. This contract is intentionally unchanged: one ordinary fee-bearing exit may stop all new entries permanently. A resulting short sample or cash-dominated terminal is not an advantage. Existing risk exits may continue.

Native `handle_left_open` is narrowly overridden to retain open native positions without creating orders. Model terminal cash, inventory, mark age, realized/unrealized amounts and estimated exit cost remain separate. No future open or force-exit is manufactured. Real maximum drawdown remains `UNKNOWN`; observed opening-mark drawdown cannot replace it.

## Evidence and bounded commands

`docs/issue139-native-synthetic-mapping-v2.json` records actual pinned Freqtrade 2026.7 integration with source commit `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`, real orders and wallet values. Base and stress each test two assets, slipped prices, partial exit, fee dust, global new-risk block, missing-open rejection and unchanged order count at terminal. An additional native replay verifies exact-lot modeled flat followed by a new cycle while retaining native fee reserves.

All synthetic attempts are disclosed: 10 native engine instances in 6 Python process invocations; 2 early instances failed exact gross sizing before the stake callback was wired, and 8 passed. The final process contains 3 successful instances. Synthetic instances are separate from the 28 historical market calls. New market calls=0, reservations=0, additional GET=0.

Run synthetic integration with the fixed runtime:

```
PYTHONDONTWRITEBYTECODE=1 /Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python scripts/probe_spot139_native.py
```

The first-batch manifest is `docs/issue139-spot-first-batch-v2.json`. The entrypoint requires its published SHA, cost `base` or `stress`, and defaults to check-only. After supervisor review, `--execute --grant <external JSON> --grant-sha256 <fixed SHA>` additionally requires an external grant with `market_execution_authorized=true`, this exact `manifest_sha256`, `costs=["base","stress"]` and a nonempty `authorization_reference`. This package does not create that grant.

The runner fixes the native checkout, interpreter, 39 sources and code hashes. Base must succeed before stress. Before spawning the native worker it durably appends a reservation under the single fixed Git-external root `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue139-spot-native-v1`; duplicate cost, unresolved previous reservation or more than two reservations rejects. Constructor failure, timeout or other failure consumes the reserved slot; timeout=180 seconds, technical retries=0, no reclaim/reset. The parent holds a single-writer lock and passes its descriptor to the worker. A public worker flag without the parent reservation is rejected. A killed parent leaves an unresolved reservation and requires audit, never an automatic rerun.

Both historic market-call/global ledgers remain exact bound snapshots. The new fixed-root ledger is a distinct Issue139 first-batch accounting suffix, not a reset of global96 or old sealed10. The manifest carries 28 historical consumed + old sealed10 + Issue139 draft maximum10 + remaining48. Only B's two slots are implemented here; later A/C/half-B modes remain gated and have no executable job. A supervisor must reconcile this new suffix before authorizing other global market work.
