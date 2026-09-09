两轮正式 Search 已完成，原生终态 `SEARCH_TERMINATED_NO_FINALIST`；真实 native 2/2，均 VALID，无重跑、无finalist。D/H/Stress/Judge/Release/交易未执行。

| 指标 | R1 | R2 |
|---|---:|---:|
| 成交（多/空） | 642（319/323） | 362（196/166） |
| 活跃周块 | 26 | 26 |
| 原生净收益 | -2.572701932% | -3.318135475% |
| PF | 0.949188858683898 | 0.8904509535129287 |
| 回撤 | 7.6794737899007135% | 7.532286324705857% |
| 纯价格G / USDT | 38.0740 | 2.9345 |
| N2bps / USDT | -51.18703734275991681953 | -47.53921544594278701082 |
| N5bps / USDT | -89.37706434275991681953 | -69.07600643594278701082 |

覆盖门通过，经济门失败。R2 ΔG=-35.1395；G/E、N2bps/E均更差；删去最大ΔN2bps周（2024-12-12起）后ΔG=-45.6181、ΔN2bps=-9.43301263008022390843。两者删除自身最佳N2bps周后N2bps仍负，R2剩余G也负。没有手工递补。

1004笔逐笔验证next-open完整冲击/确认、实际两填单quantity/price/time/notional/fee、1x和0..180分钟；零分钟均stop_loss。按S真实funding.open×同小时mark.open×signedqty独立复核资金费，最大浮点差1.615e-17；N与原生8位profit_abs最大差4.989e-9 USDT。经济门使用完整Decimal，无舍入放行。

现有六表计数：Profile1 / Generation3（2真实CODEX + 1应用自动Search投影）/ Candidate2 / ResearchRun0 / BacktestExecution0 / Release0。两源码精确匹配M；真实Generation模型参数gpt-6-astra，运行时effort/Fast回传UNKNOWN。Console http://127.0.0.1:8777/console 保持idle供监督复核，FreqUI UNAVAILABLE。

ledger旧81行未改，追加82登记、83源接触、84终态。S实际52722/4394/549，D52146/4346/543；D仅机械QC，H price/mark未取。July包2条rate未解释，精确跳过时间UNKNOWN，按监督裁决保留缺口。业务代码/schema零改动；工作树clean。

精确证据：
- manifest SHA `f019e3cc7db7ca1d03bfb989ee09d402b361e80098abf61ae52e23fccc5e73bb`
- native terminal SHA `befe5c5fcce3582f42686d3fd918f8e9106c680782d659314f033911d20fee8e`
- R1 ZIP SHA `e22283293c4726cbead4e8e42fa43662e42df2fb7d0285f34e7c152f1c22e5a0`
- R2 ZIP SHA `83cae92eaa8cd515e5eaddd918cfdded00674c70358ea9eb508c00d763c3899c`
- accounting-summary SHA `660e2c2fda7540aa172a6d954854a2820f654622cbc9c80c58b54e1ce25fe989`

本地交付根：/Users/shenjianpeng/.codex/runs/freqtrade-lab/link-closed-shock-continuation-n-v1-2528-20260905T034227Z；summary.md、terminal-summary.json、sha256-index.json、accounting-summary.json、逐笔文件及database-final-proof.json齐备。Issue留OPEN等待root独立核最终件。
