# 资金费变化机制：一次有界发现审查

本轮完成实际检索与来源盘点，唯一保留“已结算资金费一阶变化”的最小开发机制卡，状态为 `RESEARCH_PREPARATION_REQUIRED`。它尚未成为可执行市场任务；没有新增 native、行情 HTTP 或策略收益计算。冲击反转/主动成交转换分支按已完成结果停止，既有 `carry_nonpaying` 确认候选及固定窗口保持。

实际开始：2026-09-09T01:12:17+00:00；完成：2026-09-09T01:17:25.591885+00:00（上海当日 09:00 后）。本轮计入 2026-09-09 首次 DAILY 发现，同时满足 round-004 结束空槽的补充需要；初始 supplemental 标签归并到这一轮，不再消耗一次补充名额。去重键：`2026-09-09/daily-v1`。检索为 4/4 个 query、打开 5/6 个独立来源；达到 query 上限后停止扩展。每个 query 的实际执行状态和总体时间界见同名 JSON。含落盘整理实际耗时 308.6 秒，比约 5 分钟目标多 8.6 秒；未追加检索或市场工作。

## 实际检索及日期限制

1. `perpetual futures funding rate changes predict returns paper arxiv` — 完成，定位原始论文与公开研究线索。
2. `site.developers.binance.com futures Funding Rate History fundingTime fundingRate markPrice` — 完成；排除搜索中出现的 COIN-M 页，实际核对 USD-M 官方字段。
3. `"funding rate" "perpetual" discussion September 2026` — GitHub/Reddit，近 7 日，完成；没有确认发布日期且适用的近期讨论。近期抓取日期不能证明近期发布。
4. `perpetual funding rate settlement historical data discussion` — GitHub/Reddit，扩展近 30 日，完成。论坛搜索日期与打开页面的相对日期冲突，保留 `UNKNOWN`。实时 BTC 信号摘要、宣传内容、不同保证金币种和陈旧讨论未用于选型。

## 依据及其可支持的范围

- [Kim、Park 原始论文](https://arxiv.org/abs/2506.08573)，提交日期 **2025-06-10**。本次读取摘要及版本历史：它研究通过资金费设计约束永续价格与目标价值的关系，提供定价机制依据；不证明资金费差分预测 BTC/ETH 方向收益。本轮没有完整复现论文。
- [Binance USD-M Funding Rate History](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History)，发布/更新时间 **UNKNOWN**，实际重定向到官方市场数据目录。`fundingRate`、`fundingTime`、`markPrice` 分别提供结算费率、结算时间及该资金费对应标记价格；它没有提供历史公告可用时刻或结算前预测快照。同页 Funding Info 说明资金费上限、下限及周期可能调整。
- [Binance 资金费规则](https://www.binance.com/en/support/faq/detail/360033525031)，页面发布 **2019-09-09 02:27**、更新 **2026-03-06 07:01**（页面时区未标）。资金费来自溢价平均、利息项、clamp/cap 及可调整结算周期。由此推断：差分可能反映基差激励变化，也可能只是公式约束或周期变化；不能直接称为 OI 增长、资金净流入或已识别拥挤仓位。
- [funding-rate-alpha 公开仓库](https://github.com/OctopusTakopi/funding-rate-alpha)，发布/更新时间 **UNKNOWN**。作者报告价格效应、carry 和不同阶段结果存在差别，并指出组合条件可能缺乏增量。这里只作为“必须分别核价格、资金费与条件增量”的发现线索；未复现其代码、数据或收益，不采用其数值作为本项目证据。
- [Kalshi 论坛讨论](https://www.reddit.com/r/Kalshi/comments/1vp6rs8/has_anyone_actually_been_credited_funding_on/)，准确发布日期 **UNKNOWN**：搜索展示 2026-08-15/三周前，打开页面展示 3 小时前。它讨论不同平台的资金费支付，回复也相互矛盾，故不选作机制或实现依据。

## 本地数据能表达什么

只读核对 `first-capture-v1` 的资金费元数据、字段、时间连续性与有限值。BTC、ETH 各 **1,638** 条实际结算记录，来源范围 **2025-01-01 至 2026-07-01（右开）**，全部已曝光开发数据。每条保留 `event_time`、`cost_time`、`rate`、`mark_price`、`available_at`、`fetched_at`、`quality`、`vintage`、`source_version`；SHA 与原 receipt 一致。双币事件严格递增、观察到连续 8 小时 UTC 槽；原始毫秒保留。`available_at` 为实际结算后 1 小时的保守假设，历史实际抓取发生在 2026-09-08，因此不能声称历史 PIT。

这些字段能表达两个**已经可用**的相邻结算费率差；本次未计算差分绩效或读取行情收益。周期变更不能靠填零、前向填充或假定永久 8 小时掩盖。首次只准入当前已核的同周期连续片段，并保持原始时间/费用语义。一次本地时间字段检查因脚本括号错误失败，修正后完成；这是只读命令修正，市场重试为 0。

## 三个候选的选择

| 候选 | 数据与信息价值 | 决定 |
| --- | --- | --- |
| 已结算费率变化 | 能由已有两次结算记录表达；可检验变化相对水平是否有额外价格成分 | 唯一保留，等待零 native 准入 |
| 结算前后抢资金费 | 需要当时预测费率、分钟成交/盘口及边界执行；现有 settled+1h 与小时撮合不能忠实表达 | `BLOCKED_DATA`，不排市场任务 |
| OI/链上条件化费率变化 | OI 单位/历史 PIT 未核实；日频 TxCnt/AdrActCnt 缺历史发布 vintage，不能识别瞬时持仓拥挤 | `BLOCKED_DATA`，不并入首切片 |

## 唯一最小机制卡建议

假说（推断，尚未验证）：结算费率的增量改变持有永续的相对成本与基差套利激励，可能含有一段反向价格调整；若仅表现为收取资金费或已有价格反转的重复，该解释应被否定。定义 `delta_k = rate_k - rate_(k-1)`，只用两条已声明可用且同周期连续的结算记录。

预建议固定两个对照：费率**水平**逆向 `-sign(rate_k)`，费率**变化**逆向 `-sign(delta_k)`；零值空仓。二者没有 breakout/persistence 入场、没有 nonpaying 符号门槛、没有 taker-flow 条件。逻辑上，同样当前正费率，前次更高时差分可为负、前次更低时可为正，故差分不是当前符号的改名；真实经济独立性仍待检验。

首次可交易时间是严格晚于两条 `available_at` 最大值的首个小时边界。每个新可用结算事件最多一次入场，固定持有 8 小时；未平仓则跳过重叠事件，不加仓。只用 BTC/ETH、1x、1000 USDT 共享研究钱包、每币 0.4 分配、每仓 -20% stop、单边 6bp taker 加 2bp 现金滑点，资金费按实际结算毫秒及持仓核账。约 20% 是研究风险目标，略超不机械淘汰；这不扩大实盘权限。

可证伪条件建议：毛价格成分不为正、完整费用后不为正，或变化对照相对水平对照没有正增量，则停止这张卡，不搜索阈值/持有期。至少 30 个仓位周期与 12 个共同 72h 入场簇才作有限开发描述；门槛不代表显著性。必须拆分毛价格、taker、滑点、资金费和共同成交压力；即使支持也不形成第二个确认候选或盈利资格。

**唯一下一条件**：先完成不读取收益标签的零 native 准入，核清当前来源/时间/费用绑定、非零变化和水平/变化决策是否具有足够分歧；满足后再冻结独立版本的两个对照执行协议并申请现有调度器准入。否则明确 `BLOCKED_DATA` 或 `NO_DEFENSIBLE_HYPOTHESIS`。当前精确阻塞为 `RESEARCH_PREPARATION_REQUIRED`：最小两个对照协议、真实可用时间核验及现有原生组件的薄适配尚未完成，没有可运行的已绑定 task。本次发现不新建 runner、不改冻结代码、不入市场队列；既有 8/day、28/week 名额及单 writer 保持。
