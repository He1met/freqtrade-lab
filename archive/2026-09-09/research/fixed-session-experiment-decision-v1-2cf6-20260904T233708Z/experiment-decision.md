# 固定时段历史研究：窗口与协议决定

**BLOCKED_WINDOW_OR_PROTOCOL。** 当前只完成窗口元数据审查，未形成可执行研究合同。监督明确：没有授权豁免跨资产同日历曝光，也没有授权把本币未命中称为独立 Development/Holdout；故按工作顺序停止，不写 R1/R2，不查业务源码，不做 AST 或工程试验。不是时段假设已被经济证伪，也不是所有历史已经耗尽。

开始 2026-09-04 23:37:08 UTC；截止 2026-09-05 00:07:08 UTC，墙钟同时约束活跃时间。新 worktree `2cf6/freqtrade-lab` 为 clean detached HEAD；HEAD 与本轮 `git ls-remote` 的 live main 均为 `dc82c61fe8a27a654977344755c088412518d858`。原 checkout 的 `?? docs/product-requirements-v1.md` 保留。请求为 gpt-6-astra/high、Standard/default；未选择 Fast/priority 或改设置，实际调度层级 UNKNOWN。

已通过 read_thread 读取上一任务“发现可由现有项目执行的下一项历史策略研究” `01a06eb6-08eb-7a71-ab6e-7f23f3ea6008`。其最终 selection/metadata 哈希与派发一致，旧 `NO_VIABLE_HYPOTHESIS_WITHIN_SCOPE` 和旧 root 不变。本轮是监督的新协议评估。Shen/Wen 仅是此前机制线索；论文成本分母、完整费用函数、各 η 持仓与 DST 仍 UNKNOWN。不能由 25bps 示例推出本项目 5bps/side 亏损，也不能用杠杆救结果。本轮新增文献检索为零。

以下是 **LINK/USDT:USDT 的协议讨论候选，未选定、未预留**。所有区间 UTC、左闭右开。LINK 的已知 raw 曝光为 2023-12-31 16:00:00.152 至 2024-01-31 15:59:59.729（含端点），以及 2026-06-07 16:00:00.985 至 2026-06-08 15:59:59.079（含端点）；前者非时间字段解释范围为 Jan30，后者为 June8 07:59 的 100 行。本轮没有重读这些值。

| 讨论候选 | 本币已知曝光 | 跨币曝光及保留边界 | 本轮判定 |
|---|---|---|---|
| Search `[2024-02-01,2024-08-01)` | 指定索引无 LINK 区间命中；旧 Jan raw 在此前。pre-roll 未定义，不能认为也已排除冲突。 | BTC/ETH 的 2020–2024 exploratory training 包含全段；#49 BTC、#52 ETH、#62 XRP、LTC/BCH/DOGE Search，以及 #61 ADA 的相交 Search/Dev 元数据存在。旧 Dev 不挪用。 | 有本币新信息的可能，但不满足当前未消费协议；不能把跨币相关性等同于数学上零新信息。 |
| Development `[2024-08-01,2025-02-01)` | 指定索引无 LINK 命中。 | 2024 部分在 BTC/ETH 训练内；LTC/BCH/DOGE Search 覆盖全段，#61 ADA、#55 ETH 的 Search 相交；#49/#52/#62 的 Dev 元数据相交。#49 H `[2024-09-01,2024-10-01)`、#52 H `[2024-10-01,2024-11-01)` 保留；2025 Jan 属 BTC/ETH outer sealed。 | 不能称独立 Dev；既有封存不因未运行或更换币种而释放。 |
| H/Stress `[2025-02-01,2025-08-01)`，同一候选窗口 | 指定索引无 LINK 命中；没有本轮数据包或封存收据。 | 全段在 BTC/ETH 2025 outer `SEALED_UNREAD` 内；#45 BTC、#55 ETH、#61 ADA 的 Search/Dev 相交，LTC/BCH/DOGE 与 #62 XRP Dev 元数据覆盖。 | 仅纸面候选，不是已独立或新建的封存；不得借用旧 outer/H 名义取数据。 |

元数据合并为 114 个去重路径，另核验 77 行 ledger；底层市场文件没有重新核验。所有候选的真实 5m/mark/funding 完整性、未登记外部研究、实际滑点均 **UNKNOWN**。若将来获得窗口授权，数据完整性仍须一次正常采集及消费者校验，不能把 UNKNOWN 写成缺失或 READY。此前未授权的 March/April/May 及 June/July/August 方案不继承。

其他边界保留：2018 旧精确采集曾 BLOCKED_DATA，不外推所有早期历史；2019/2021/2023 旧 Dev 及 2025 outer 保留。2020/2022 会计无效、2024 drawdown 无效、2026 July carry 因果无效均不恢复为新数据。2026 Jan Search、Feb Dev、March 旧覆盖/#45 H、April/May/June 跨币研究、July carry/XRP/AVAX、August Dev、#43 September H 等消费或预留逐项保留，细分与出处见 metadata；索引之外 UNKNOWN。

**唯一下一动作：由监督请用户决定是否建立明确降格为探索性训练的新协议。** 该决定须明确允许复用哪些“已见且非封存”的训练区间、跨资产曝光如何记账、一次固定假设/有限尝试的预算，以及独立 Dev/H/Stress 的另行来源与合法未见依据。若尚无真正未见验证，训练只能产生探索性结果，不能形成合格策略；若需未来数据须另定等待协议。该建议不授权复用旧 Dev/H，不释放任何封存，也不自行采用本表日期。没有用户的新协议决定前，不创建实现或历史研究 Issue。

经济资格保持：1x；净收益严格 >0 且 ≥初始 wallet 的 1.25%；PF ≥1.10；峰值 DD ≤15%。样本量、stake、时区/DST、入退场、资金费与滑点方案本轮均未冻结；窗口先阻塞，故不以成本算术或源码草案包装研究进展。最小实施范围本轮未审定，不能声称已有能力或需要扩大 schema。

实际交付仅此文及小 metadata，Git 外目录 0700。业务/native/Freqtrade Ai/全局设置修改 0；市场 API/下载/新市场原值读取 0；业务 DB 读写 0；真实 backtest/Search/Dev/H/Stress 0；Candidate/窗口 claim/Issue/PR 写入 0；源码草案、AST、T1/T2/T3 为 0。仅做文档与哈希检查。**可见信息例外：首次 read_thread 与未过滤 ledger 工具输出包含旧历史指标摘要；未另开底层 metrics/trade 文件，不据此选择资产、时段、日期或放宽资格。** 不能报告“本轮完全未见旧指标”。
