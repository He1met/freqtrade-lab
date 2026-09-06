# Issue 96：BCH 28/14 日线趋势单基线负例

2026-09-07 完成一次原生 Search，技术状态 `VALID`，项目终态 `SEARCH_TERMINATED_NO_FINALIST`。这是冻结范围内的经济负例，同时有效自然样本不足；没有合格策略，没有 Development、Holdout、Holdout Stress、ResearchRun 或 Release。后续阶段不会为了完成流程而运行。

## 冻结实验

Binance BCH/USDT:USDT、1d、isolated 1x、单仓；1000 USDT 初始钱包、固定500 USDT仓位。日收盘突破先前28日收盘区间开多/空，跌破/突破先前14日区间退出，指标 `rolling(...).max/min().shift(1)`，29日预热，8%止损，`minimal_roi={}`，原生下一根执行。没有定时周交易、调参或 child。

S 为 UTC `[2023-11-13,2024-07-15)`，35周，固定5个7周块。已暴露技术周 `[2023-11-06,2023-11-13)` 不评分。D `[2024-07-15,2025-07-14)` 只机械采集与QC并物理隔离；H/Stress `[2025-07-14,2026-05-25)` 未采集。原协议SHA `8f1962194098b76704301443609fda95d05d45a55e96ce50d473f66549d049a4`，监督在首次取值前冻结。一轮一次 Search，零追加尝试。

每边原生fee `0.001`，拆为5bp手续费假设和5bp滑点/价差代理；两边原生各扣一次，没有外部双扣。资金审计沿用 `BINANCE_ASSOCIATED_MARK_BOUNDARY_V1`。费用假设与分钟桶/日线成交近似不保证实际可成交。

## 原始结果和冻结门

| 指标 | 实测 | 要求 | 结论 |
|---|---:|---:|---|
| 原生总交易数 | 9 | ≥8 | 通过 |
| 自然有效交易数 | 7 | ≥8 | 失败 |
| 自然多/空样本 | 5 / 2 | 各≥2 | 通过 |
| 有自然样本的固定块 | 4 / 5 | ≥3 | 通过 |
| 保守净收益率 | -4.221679% | ≥1% | 失败 |
| 保守 PF | 0.836102 | ≥1.10 | 失败 |
| 原生 DD | 16.873488% | ≤15% | 失败 |
| 保守小时收盘 MTM DD | 25.299915% | ≤15% | 失败 |
| 平均持仓 | 16320分钟 | ≥4320分钟 | 通过 |
| ROI退出 | 0 | 0 | 通过 |
| 最低可用现金 | 322.695556 USDT | ≥0且可执行 | 通过 |
| 去最大赢家后保守净额 | -195.768148 USDT | >0 | 失败 |

原生净额 -42.085199 USDT、PF 0.836552。原生DD是原报告 `max_drawdown_account` 投影；25.299915%是含保守资金扣减、持有完整小时收盘与真实成交费用的观察点MTM回撤，口径不同，不能替换原生字段或宣称连续路径上界。额外小时内先有利后不利极值压力为27.890252%，也不是原生 Holdout Stress。

一笔同日止损（0分钟）与一笔期末 `force_exit` 从自然有效样本数排除，仍完整保留其盈亏。最终退出在2024-07-14，未触发排他终点核算失败。5块按入场归属的自然样本数是3、1、2、1、0；全交易保守净和依次为 -85.697691、-83.087348、106.621321、-41.863895、61.810826 USDT。跨块持仓没有重跑或重置，这些数不是各块MTM收益。

| 成本分解 | USDT |
|---|---:|
| 纯价格毛利 | -13.250440 |
| 手续费假设支出 | 4.468098 |
| 已包含的滑点代理支出 | 4.468098 |
| 原生资金费净现金流 | -19.898564 |
| 原生净额 | -42.085199 |
| 附加保守资金扣减 | 0.131588 |
| 保守净额 | -42.216787 |

逐笔验证 `价格毛利 - 原生双边fee + 原生funding = 原生净额`，再减保守扣减。项目字段 `gross_profit_before_fees_pct` 仍包含原生funding；上表“纯价格毛利”明确剔除了资金费。价格本身已负，不能把降低费率当成这项假设的解答。

## 来源、执行与页面证据

运行代码为已合并 `fa1d19e8b56ed7cc5a9bf78d24b6d1be6114f9ac`；原生 `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5` / Freqtrade2026.7 / Python3.13.13 / ccxt4.5.68 / pandas3.0.3 / pyarrow25.0.0，干净原生源码已核。无新runner、schema或产品代码改动。

复用原S 33响应；唯一D采集33次CCXT fetch、3,095,502解码字节、自动重试0。透明保留两个批次原receipt和响应字节，仅文件名映射打包；重复行完全一致，两次BCH市场快照无变化，历史精度/档位适用性仍 `UNKNOWN`。首次本地打包误加JSONL空行，在来源发布前被拒绝；保留失败目录，新目录仅纠正换行，网络没有重取，验证器没有修改。

来源provenance SHA `5997bc2923d05e1fc55490f0ad74c202e47281e849ffb70a9d125e474e69ff9f`；receipt SHA `40c9304025e8acc140472db335d444b8f76465297e6d78ab99840c166578dec8`。S物理274根日线（含29预热）、6576小时mark、735 funding；D物理393日线（含29预热）、9432小时mark、1092 funding。两阶段绑定同一完整来源和Profile，Search实际只读S切片。

本地运行根：`/Users/shenjianpeng/.codex/runs/freqtrade-lab/binance-bch-research-60d5-20260907`。数据、DB、完整artifact与审阅文件均在Git外。根目录下：

- `frozen-protocol.md`、`supervisor-authorization.json`、`single-baseline.json`、`profile-snapshot.json`：事前绑定。
- `search-protocol-review.json`：逐笔成本、所有门、5块、DB记录；审阅函数只读取一次既有artifact。
- `search-campaign/search-terminal.json`、`search-campaign/trials.jsonl`：项目真实不可重开终态。
- `aggregated-retained-v2/aggregation-manifest.json`、`source-aggregation-qc.json`、`packaging-failure-note.json`：批次、来源摘要、失败恢复证据。
- `terminal-ledger-record.json`、`terminal-ledger-receipt.json`：追加终态与保留前缀证明。
- `verify-readonly.sql`、`ui-verification.json`：只读复核入口与实际浏览器观察。

| 记录 | 实际标识 |
|---|---|
| Profile | `issue96-bch-trend28-v1` |
| CODEX Generation | `bdd08312-e427-4ce8-9145-5612a862704b` |
| Candidate | `89c0c792-93a3-4e3b-b8ac-67a56eca4dea` |
| Search campaign / MANUAL Generation | `7c7450dc-67bb-4f27-baa3-961a4eaa043b` |
| 源码SHA | `797e6d7e48e5a0ff6169f0a0ac0bbd1f2504ca887b817fab3c1df314df2cac82` |
| 原生ZIP SHA | `395aa758d92e79eb26fcbc5e3c569ee2b4fd56cad7095d5b0c15a02b83ec588b` |
| 项目terminal SHA | `e3e51fe8293ee869861291c7ff7171338ecf7c844fe54b97938c517445e17374` |
| 项目trials SHA | `d751e498fdfcc24df1ddf33a6bc27c6eae7357703f30fe8f3b28f10d797da4ea` |

原生ZIP位于上述根的 `search-campaign/search-results-round-1/89c0c792-93a3-4e3b-b8ac-67a56eca4dea/raw/backtest-result-2026-09-06_17-50-03.zip`。

全局台账 `/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl` 终态追加后112022 bytes / SHA `84e8c49eab8b40eb39559e0468a914ae80506dbf7b60cb93402e9ecb18891271`，旧105613字节前缀和原空行完整保留。后续其他研究可能追加，核验本次前缀和receipt，不要求全局文件永远不变。

新 `lab.sqlite` 恰好六表，计数依次是 Profile1、Generation2、Candidate1、ResearchRun0、Execution0、Release0。Search终态放在现有 `generation_runs.response_json` 并绑定原生artifact；没有伪造ResearchRun。只读示例：

```bash
sqlite3 -readonly /Users/shenjianpeng/.codex/runs/freqtrade-lab/binance-bch-research-60d5-20260907/lab.sqlite < /Users/shenjianpeng/.codex/runs/freqtrade-lab/binance-bch-research-60d5-20260907/verify-readonly.sql
```

[Console](http://127.0.0.1:8796/console) 实际浏览器已核：Search终态及原生/保守指标可见，Round1/2、D、H按钮禁用；D候选 `BLOCKED_SECURITY` 明确因为没有verified finalist，D卡片“暂无数据”，H/Stress `SEALED_UNREAD`，latest ResearchRun为null。单独FreqUI未启动，`UNAVAILABLE`/版本`UNKNOWN`，全局Preflight因该服务缺失为`NOT_READY`；这不抹去已完成的原生Search，也不宣称FreqUI可用。

只做冻结源码的无市场T0（先前窗口、prefix因果不变、多空方向、ROI/stop/startup）和现有来源/产物验证、逐笔费用对账、实际页面检查。没有重复工程367项或native smoke。终态后没有额外回测。

## 后续方向，仅提案

本次趋势基线既没有价格毛利，也缺乏自然样本与分散收益，不能通过换币或加快参数声称独立证据。下一门应先做旧机制去重、未消耗窗口与成本/容量预筛；可评估“短期过度反应后的价格回归”这个已知逆转家族。经济动机不同于追随突破，但不能据此假定BCH有效；[Lehmann的原论文](https://www.nber.org/papers/w2533)研究的是股票短期逆转，不是本合约证据。较短持仓或许减少资金费暴露，同时会增加周转费，因此先要求事前可解释的毛价格空间超过完整往返费用，并预留足够自然样本窗口。不得重播本次S、挪用封存D/H或现在试跑。
