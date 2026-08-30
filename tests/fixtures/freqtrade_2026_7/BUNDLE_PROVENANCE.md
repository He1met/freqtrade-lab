# Three-scenario fixture bundle

This is a technical import/bundle fixture, not evidence of profitability or
trading suitability. All three artifacts use official Freqtrade `2026.7` at
commit `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5` and the same
`StrategyTestV3Futures` source SHA-256
`db2d416b5d40daf2dcd8ef8c07a937053c846ca89a9fca1f01facab60dfadc2d`.

| Scenario | Timerange | Configured fee | ZIP (SHA-256) | Meta SHA-256 | Provenance SHA-256 |
| --- | --- | ---: | --- | --- | --- |
| Development | `20260801-20260804` | `0.0005` | `backtest-result-2026-08-30_12-55-02.zip` (`f8a064d3910435aecbe5a612211376c390d67912b856b4a19a403af31229efe9`) | `e4afe038fc5a358530fe6aff8f11dc84874d60e057d4e02da839fee6f138ee2c` | `132b65ebdf236940a2da645ec1ef26c1b23aedc5287416ad021b725da0648d3b` |
| Holdout | `20260804-20260807` | `0.0005` | `backtest-result-2026-08-30_06-43-00.zip` (`2c4723050a792e8b4351f23b78b1792220fe04fb52ecd830bbaff4da0ff87ec6`) | `80f3dde8d400f357b86aa91a8978537f033fb75438bdd0f35a8a5875ca74205c` | `df61ed5eadb4768d2992577464a8517cab92a90cb17df998174787b3a2f51bfa` |
| Holdout Stress | `20260804-20260807` | `0.001` | `backtest-result-2026-08-30_06-43-22.zip` (`3cb0f8e8a943e7fdff24c10a2e8afca2e165d7d375d5e216b606316e40ec6a68`) | `a08c296eacb7f4d19774eb25109695907df2e699e0a1a8b8e6767c90e4028255` | `661cf9ca15cefe85c97a3be4609310175d698a5552b4afb8c8c4a6ea91347d17` |

Development is the unchanged Issue #2 fixture. Holdout and Holdout Stress share
fresh public OKX market evidence bound by retrieval receipt SHA-256
`84e380b847a46255841d85864ca97c388d373b429067c80e1e82604459c94e4d`.
The fee values are fixture configuration assumptions, not observed account fees.
The shared `UPSTREAM_LICENSE.txt` SHA-256 is
`589ed823e9a84c56feb95ac58e7cf384626b9cbf4fda2a907bc36e103de1bad2`.
