N 已完成两轮正式 Search，终态 **SEARCH_TERMINATED_NO_FINALIST**。真实 native 2/2，均技术 VALID，无重跑。D/H/Stress/Judge/Release/交易均未执行。Issue #77 保持 OPEN，等待监督复核。

| 证据 | R1 | R2 |
|---|---:|---:|
| 成交 / 多 / 空 | 642 / 319 / 323 | 362 / 196 / 166 |
| 活跃周块 | 26 | 26 |
| 原生净收益 | -2.572701932% | -3.318135475% |
| PF | 0.949188858683898 | 0.8904509535129287 |
| 回撤 | 7.6794737899007135% | 7.532286324705857% |
| 纯价格毛额 G (USDT) | 38.0740 | 2.9345 |
| 实际 signed funding (USDT) | -0.15097434275991681953 | -0.22120313594278701082 |
| 基础手续费 (USDT) | 63.65004500 | 35.89465165 |
| N2bps (USDT) | -51.18703734275991681953 | -47.53921544594278701082 |
| N5bps (USDT) | -89.37706434275991681953 | -69.07600643594278701082 |

覆盖门通过，但两策略原生 PF/回撤/净正及额外成本净正均失败。R2 ΔG=-35.1395 USDT，G/E 和 N2bps/E 均未提高。ΔN2bps=+3.64782189681712980871 USDT 仅是较少交易后的相对少亏；删除最大ΔN2bps周（2024-12-12起）后，ΔG=-45.6181、ΔN2bps=-9.43301263008022390843。原生无finalist，不进行额外否决后的手工递补。

全部1004笔均验证两笔实际fill的quantity/price/time和notional/fee、1x、整点后30分钟next-open、ROI恰180分钟、持仓0..180分钟；各一笔0分钟交易均为stop_loss。funding按S实际费率和mark独立复算，最大差1.615e-17 USDT；N与原生8位profit_abs最大差4.98866545e-9 USDT。会计容差仅用于导出舍入对账，所有经济不等式使用完整Decimal值，没有以舍入放行。

原生 minified order不含单订单funding_fee；此处每笔交易只有一次入场和一次出场，保留两单实qty/notional、trade signed funding并独立复算全部现金流。未补零或去funding。Search既有gross_profit_before_fees含funding，不能把它当纯价格G。

链路：两次source=CODEX、model参数gpt-6-astra的真实Generation，各原样匹配M冻结SHA，现有API审批后执行。实际effort/Fast及模型运行回传UNKNOWN。数据库六表计数 Profile1 / Generation3 / Candidate2 / ResearchRun0 / BacktestExecution0 / Release0；Generation3中的一行是现有应用自动写入的MANUAL Search-terminal投影，不是手工生成候选。该行parse_report_json绑定两attempt、native artifacts、trials、terminal SHA，finalist_binding=null。

数据：单次官方producer57.124849秒；S 52722/4394/549，D52146/4346/543（5m/mark/funding）。D只有机械物化/QC、Agent不读价格/费率/收益。H价格/mark未取；July月包opaque字节已取，两条窗外rate未解释，精确skipped时间UNKNOWN，监督已书面裁决不阻塞本次S但不构成完整H审计。旧ledger81行原封不动，仅追加N登记、源接触和终态。业务代码/schema零改动，工作树clean。

Console [http://127.0.0.1:8777/console](http://127.0.0.1:8777/console) 保持idle供监督审查（PID10080）；Generation/native进程已结束。FreqUI UNAVAILABLE。GET /api/research-runs为现有405方法边界，零ResearchRun由六表查询和/api/research/context验证。

主要证据：execution-manifest.json、terminal-summary.json、sha256-index.json、accounting-summary.json、accounting-r1-trades.json、accounting-r2-trades.json、database-final-proof.json、search-final-api.json、supervisor-notes.md。源码/原生artifact/实物/terminal/trials的精确SHA见索引。2/5bps为情景成本，不是实测滑点；这次是精确协议下经济负结果，不宣称机制普遍无效或已证明统计功效。
