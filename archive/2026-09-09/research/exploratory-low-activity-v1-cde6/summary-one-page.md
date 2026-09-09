# B：低成交活动条件反转——收尾摘要

**结论：SEARCH_TERMINATED_NO_FINALIST。** 两次原生 Search 均技术有效、经济门失败；本轮过滤机制结束。仅为 EXPLORATORY / NOT_INDEPENDENTLY_VALIDATED，无独立验证或合格策略。

固定条件：LINK/USDT:USDT，5m，UTC `[2024-02-01,2024-07-31)`，73根预滚；wallet 2000、名义 stake 400 USDT，1x，单仓，止损2%，ROI关闭，手续费5bps/side。实际源码与事前 SHA 完全一致。

| 金额单位 USDT | R1 基线 | R2 低活动过滤 |
|---|---:|---:|
| 成交笔数 | 988 | 275 |
| 价格毛额：不含手续费、资金费 | +221.7561 | −76.8608 |
| 原生资金费净额：正为收入 | −1.1463 | −1.5502 |
| 费用前收益：价格毛额＋资金费 | +220.6098 | −78.4110 |
| 手续费 | 394.4911 | 109.8658 |
| 原生净收益 | −173.8812 | −188.2768 |
| 原生净收益 / 初始资金 | −8.6941% | −9.4138% |
| 原生 PF / peak DD | 0.9283 / 10.3953% | 0.7031 / 9.6261% |
| 说明性2bps/side再扣减后净额 | −331.6776 | −232.2231 |

**增量口径：** R2−R1 的原生净额为 **−14.3955**；说明性扣减后差额为 **+99.4546**。后者仅因两者成交成本暴露不同，不能替代原生净增量；两者扣减后仍负，R2未通过冻结增量门。实际滑点 UNKNOWN，说明扣减未计入原生 PF/DD。

手续费由原生逐笔量价及费率重建（archive未导出fee_open_cost/fee_close_cost金额字段）；资金费来自原生 funding_fees。逐笔价格毛额−手续费＋资金费与净額对账误差小于5×10⁻⁹。全部入场/信号退出与前一闭合bar→next-open对齐，无越窗；R1的19笔零分钟均为同bar止损，两轮ROI/force_exit均0。

**交付已验收：** [Console](http://127.0.0.1:8792/console)页面已核两次尝试、无finalist、预算2/2及探索/封存标签。SQLite六表依次Profile/Generation/Candidate/ResearchRun/Execution/Release为 **1/4/3/0/0/0**；其中保留1个语义漂移REJECTED Candidate及1次授权技术重试，未增加经济尝试。原生进程已空，槽位释放；A+B总4次共用探索池，非独立统计证据或组合PnL。

完整证据：[native-results-audit.json](/Users/shenjianpeng/.codex/runs/freqtrade-lab/exploratory-low-activity-v1-cde6/native-results-audit.json)，SHA `7cabebd157ef726017c9886dbc401b4b82c210573183976bb9217b64c6a3d15b`。campaign `3d8a9b13-e2a5-48e5-a39e-4ffb4fa43b06`。监督已复核终态、ledger、原生审计及数据库；本任务结束，不再追加研究。
