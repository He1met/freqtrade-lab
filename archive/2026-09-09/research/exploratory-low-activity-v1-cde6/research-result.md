# 低成交活动条件反转 B：历史探索结果

**SEARCH_TERMINATED_NO_FINALIST。** R1、R2 各一次原生 Freqtrade Search，均技术有效，但均未通过经济门；低活动过滤没有取得事前规定的净增量。标签始终是 **EXPLORATORY / NOT_INDEPENDENTLY_VALIDATED**，不进入 Development、Holdout、Stress、Judge、Release 或交易。

固定样本：OKX LINK/USDT:USDT，5m，UTC `[2024-02-01, 2024-07-31)`；73 根 pre-roll 从 Jan31 17:55 起。初始资金 2000 USDT、名义固定 stake 400、1x、单仓、stoploss −2%、ROI={}。实际成交量按交易所精度取整。两份实际 Candidate 源码 SHA 与事前冻结源完全一致。

| 指标 | R1 无活动过滤 | R2 唯一低活动过滤 |
|---|---:|---:|
| 真实成交 | 988 | 275 |
| 原生净额，USDT | −173.88122640 | −188.27676989 |
| 净收益 / 初始资金 | −8.6941% | −9.4138% |
| 原生 PF | 0.9283 | 0.7031 |
| 原生 peak DD | 10.3953% | 9.6261% |
| 价格毛额，未扣手续费/资金费，USDT | +221.75610000 | −76.86080000 |
| 手续费，USDT | 394.49105745 | 109.86576040 |
| 原生计入资金费，正为收入，USDT | −1.14626905 | −1.55020954 |
| 平均 / 中位持仓，分钟 | 147.05 / 125 | 184.05 / 180 |
| 信号退出 / 止损退出 | 718 / 270 | 209 / 66 |
| 多 / 空 | 540 / 448 | 148 / 127 |
| 额外 2bps/side 说明性扣减，USDT | 157.79642298 | 43.94630416 |
| 说明性扣减后净额，USDT | −331.67764938 | −232.22307405 |

R1 的正价格毛额不足以覆盖费用。R2 费用较少，但价格毛额本身已负，原生净额较 R1 **再少 14.39554349 USDT**。扣除说明性冲击后 R2 相对 R1 好 99.45457533 USDT，但两者都负，且 R2 原生净额更差，因此不能只选这一项宣称增量。两者均超过 12 笔筛查下限、DD 小于 15%，但净额未达 +25 USDT、PF 未达 1.10；R2 额外增量条件亦失败。12 笔以及此前正态尺度算术都不代表真实事件频率或独立有效样本证明。

手续费按原生逐笔 amount、open_rate、close_rate 和实际导出费率（均为 0.0005/side）重建；原生 archive 未导出 fee_open_cost / fee_close_cost 金额字段，不能冒称直接读取该字段。原生 funding_fees 全部存在，非零笔数分别 318 / 121；`价格毛额 − 手续费 + funding` 与逐笔 profit_abs 的最大误差小于 5×10⁻⁹ USDT，符合导出舍入。实际滑点仍 UNKNOWN；2bps/side 仅为冻结说明性算术，表中 PF/DD **未计入**该扣减。

全部 1263 笔 entry 以及 signal exit 已通过真实 OHLCV 只读对账：前一根 closed-bar 信号、当前 next-open 价格，0 错位、0 越窗。原生终点 Jul30 23:55 是右开窗口内最后一根 K 线的开盘标签，与 Jul31 00:00 截止一致。R1 持仓 0–640 分钟，19 笔零分钟全部为同根 K 线 stop_loss；R2 为 10–610 分钟。均无 ROI、force_exit，不把6小时统计窗口称为固定持仓。

每月结果均已在审计 JSON 并列保留，没有挑选赢家月份。R1/R2 都只有2个月净正、4个月净负。此结论仅终止本轮单品种时序外推，不否定原论文的横截面结论，不恢复旧退役机制。A、B 共用探索池，监督已确认 A 2 次、B 实际2次，总计4次；不是独立统计证据或已回测组合，不能相加 PnL。

## 执行与证据

真实入口：[B Research Console](http://127.0.0.1:8792/console)。浏览器已复核两次尝试、`SEARCH_TERMINATED_NO_FINALIST`、`consumed_total=2 / remaining=0`、探索标签和 Dev/H/Stress 封存。通用 Preflight 的 NOT_READY/FreqUI UNAVAILABLE 不影响单独已验收的 Search 能力，也不宣称 FreqUI 可用。

- 公共代码：`8ae57c1ff05baa9fb6aa0dfcef83554e17890873`；原生 FT 2026.7：`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`。B 工作树未改公共代码，#69/PR70 留待监督验收。
- Profile：`exploratory-low-activity-link-v1`；campaign：`3d8a9b13-e2a5-48e5-a39e-4ffb4fa43b06`。
- R1 真 Codex Generation：`2146092b-97b9-4743-9a1c-f41e9b218b77`；Candidate：`3dadb9c0-c502-49cf-b66d-ac8505a6bc0a`。
- R2 真 Codex Generation：`679eec9b-60a9-485e-b4fd-794ae816e8a6`；Candidate：`6842ade8-7dcb-412d-ab3f-ba03e47d2e52`。两者模型输出 tool_event_count=0、源码逐字匹配，R2 通过公共 exact-factor 门。
- 首份语义漂移 Generation `0a8dc770-e7b4-4054-beaa-85a38327fbb5` / Candidate `3e10c664-860f-4815-bfc6-8b6c2482a422` 永久保留为 REJECTED；监督批准一次提示修复和一次技术重试。没有额外真实回测。
- 六表计数：research_profiles **1**，generation_runs **4**，candidates **3**，research_runs / backtest_executions / releases **各0**。4 个 generation_runs 中3个是真 Codex，另1个是项目 API 原生登记的 MANUAL Search campaign，非额外模型或经济尝试。

[完整原生审计与各原始 archive 路径/SHA](native-results-audit.json)、[页面 API 终态快照](search-terminal-context.json)、[项目终态](search-campaign/search-terminal.json)、[两次尝试 ledger](search-campaign/trials.jsonl)、[事前合同](frozen-contract.md)。源 provenance、receipt、独立消费者、终态、ledger、archive 及源码全部 SHA 见审计 JSON；原始源和事前冻结文件再验未变。01:46 UTC 检查 native backtest 进程数为0，研究槽位已释放，Console 保留供复核。实际服务端 Fast 档位 UNKNOWN。

下一步：将本轮负面探索交监督归档，不调门槛、不加试验、不打开独立验证。
