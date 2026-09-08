# Issue139 B controlled residual V3 — synthetic development only

Authority: https://github.com/He1met/freqtrade-lab/issues/139#issuecomment-5579673703 . This is a new exploration rule designed after observing the V2 positive-return but one-episode/dust-stop result. The same 2021–2023 history can only be future development diagnostics, never independent confirmation. No V3 historical call, source GET or later mode is authorized. V2 code, results and consumed slots are preserved.

## Origin and one replacement rule

The user's hard requirement is maximum DD20% and the stated net-after-cost objective. The 10%/15% latches, B0.5% stop-risk cell and 40%/80% notional caps are previously adopted constraints. `issue139-spot-experiment-v1.md` line9 required retaining dust and not inventing full cash. `issue139-spot-gap-continuation-v2.md` line29 expanded inability to exit into blocking new risk; execution binding V1 line7 and `SpotReference._sell` made any positive post-exit remainder a permanent global block. That last expansion was our conservative design, not a user hard requirement.

V3 keeps one actual modeled inventory and one cost basis per asset, with a separate active-episode flag and residual classification. A requested exit may end the active episode with explicitly nonzero inventory if both conditions hold at an actual current open:

1. The full available modeled quantity, capped by maxQty and floored to lot, cannot form a minQty/lot or minNotional order at the conservatively tick/slippage-adjusted sell price.
2. Its entire marked value (worst-case loss to zero) is <= the asset's existing B risk cell times current equity: 0.5%, or 0.25% after the10% warning latch. This bound comes from the existing risk cell and exchange order rule, not the observed0.2USDT remainder. Every residual also remains in the40%/80% notional and shared-cash accounting. Two per-asset residuals therefore cannot silently consume more than the two existing B cells.

A significant unsellable active position, an unresolved sellable active exit, stale inventory, hard-cap violation or execution/accounting error still blocks new risk. The bound is re-evaluated each hour; a residual becoming too risky blocks even if it was small earlier. The15% latch always prohibits new buys. Nothing resets peak, latches, actual quantity or cost basis.

Residuals are tested at every actual open before signals. If sellable, sell the largest legal modeled lot/maxQty chunk immediately, irrespective of profit/loss or trend. If still unsellable and within risk budget, retain it. Missing opens cannot fill. A genuine new same-asset episode requires the original nonpositive→positive transition (initial entry may use the first positive); no buy exists solely to clear residuals. Its risk budget first subtracts the old residual's entire marked value; its notional budget subtracts old inventory, and joint sizing includes all held assets. New bought net base and new cost are added to the old balances, never assigned over them. A later sell floors the total modeled base; native gross fee reserves never enter modeled available quantity.

Cost basis is pooled. For a partial sale, release proportional basis floored to quote commission precision; leave the rounding remainder in retained basis. A truly full modeled sale releases all remaining basis. This is an attribution convention, preserves exact total cost, and does not change cash, inventory or NAV. Active episode end is not claimed to mean an exchange-flat account. No terminal synthetic liquidation is introduced.

Only B is implemented in V3. Existing `signal()` still requires85 complete days for B and273 for C, and synthetic tests reject missing dependencies; there is no V3 C execution path. Signal unavailability does not cancel prior stops/expiry.10% halving,15% halt and40%/80% caps remain effective. Current filters/fees remain disclosed simulation assumptions, not historical acceptance evidence.

## Native precision rejection rule frozen before V3 native probes

Reuse the existing pinned native order path without modifying Freqtrade. Independently replay gross amount and cost as exact rational values. For each buy add q*p to stake; each sale releases q times the unrounded rational average. Native ideal quote-fee profit is q*(exit-average)-q*(exit+average)*fee. This avoids V2's use of the tick-rounded display `open_rate` as the ideal weighted-cost reference. Modeled cash/base/basis is independently reconciled as well.

Gross inventory minus modeled inventory must equal cumulative modeled base fees exactly. Cash and realized-profit residuals must each pass an absolute precision envelope:

`S*0.5e-8 + gamma(64*N*N)*(1000 + 4*T) + N*Q*1e-18`

N is orders, S is sells, T is cumulative absolute gross turnover including native fee, Q is cumulative gross units, u=2^-53 and gamma(k)=k*u/(1-k*u). Reject if k*u>=1/2. The64 operations per historical-order iteration is a deliberately conservative arithmetic count for conversions, spot fee products, additions and wallet sums; native recalc revisits at most N*N prior order items. The turnover expression bounds absolute monetary terms despite profit subtraction. The8-decimal profit rounding term follows pinned `trade_model.calculate_profit`; the18-decimal average division truncation follows CCXT `Precise.div`. Positive spot quantities and partial amounts cannot exceed actual inventory, so truncated-average monetary error propagates through retained stake rather than an unbounded leverage exposure. Inventory/price mismatches still reject exactly, outside this numerical envelope.

This is an engineering rejection rule for this pinned arithmetic path, not certification of exchange settlement or a formal proof of all Freqtrade code paths. Unsupported/nonfinite arithmetic or a residual beyond the envelope is `ACCOUNTING_UNRESOLVED` and terminates; never widen it based on outcomes. The rule was written before V3 native integration and is hashed in the probe receipts. A deliberately corrupted cash value must be rejected. Source commit remains52bc96f4480b1a0da6a9b455bd00b17fbb6786a5, ccxt4.5.68; native source and precise.py hashes are recorded.

A V3-only entry wrapper proposes the next representable float above q*p, preventing stake/rate floating-point underflow from rounding a requested lot downward. Native gross quantity and price must still equal the original request exactly; the proposal is not a fill or extra modeled spending. Existing V2 bridge/source are untouched. The first V3 base synthetic passed but stress failed exact gross checking (0.832 versus0.833); that failure is retained, not retrospectively passed.

V3 synthetic native probes are separate from market96. The small probe runner caps this development slice at4 actual synthetic engine instances including failures, and saves a receipt before/after each constructor. No model market runner or activation grant is added here.

## Future diagnostic budget proposal, not authorization

Recommend at most2 later B development diagnostics (base then stress,180s each,0retry, failure consumes and stops) drawn from the Issue139 remaining8: current30 consumed + old10 sealed + proposed2 + other6 pending +48 unallocated =96. If both later consume,32+10+6+48=96. Old V2 calls/results remain unchanged and not replayed as the same trial. A new supervisor grant, frozen V3 integration review and new manifest against current global state would be required. A/C/half-B remain unimplemented/unexecuted in V3. PR140 stays draft and Issue139 open.
