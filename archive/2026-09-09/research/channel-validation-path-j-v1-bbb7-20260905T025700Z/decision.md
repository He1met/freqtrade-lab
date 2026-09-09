# J：历史完整验证路径（只读提案，未冻结）

**结论：唯一保留的条件方案是 SOL 同币日线 S→独立 D→封存 H；当前完整后段尚未可用（`NO_GO_CURRENT_FULL_CHAIN`），不等于S/D不可研究。** 无日历等待。checkout干净，仍为`a0a6229`；交付时独立回读远端main已为`0ace04b7c10ea35fb8ce6f25e043ac78be87c19e`（PR75固定factor已合并）。PR文件清单确认本审查window/producer/D/H模块未变，未fetch/pull。日期均UTC半开；尚未冻结/取值，非SEARCH_READY。

| 阶段 | 唯一提议评分窗 / 日数 | 29 日 OHLC/mark pre-roll | 消费顺序与资格 |
|---|---|---|---|
| S | [2024-03-01,2025-03-01) / 365 | 2024-02-01 | 固定 SOL/USDT:USDT、OKX linear perp、1d；最多 R1/R2 两次，真实 smoke 算 R1 |
| D | [2025-03-01,2026-02-28) / 364 | 2025-01-31 | 只允许唯一合法 finalist 一次；评分严格晚于 S，pre-roll 重叠只作因果 warmup |
| H / Stress | [2026-03-01,2026-08-31) / 183 | 2026-01-31 | Dev 通过并经用户另行授权才取值；同一 ResearchRun 两个后段 execution |

**一天间隔 [2026-02-28,2026-03-01) 是事前的原始包保护边界，不是择时。** 当前 source producer 可直接表达上述邻接 S/D；H 的独立起点尚不能表达，须随下述真实后段缺口一次补齐。已有计划自动令 H 从 D.stop 开始，不能把其 Feb28 标签冒充本方案 Mar1。

**资产取舍。** BTC在2024Aug31后：余下2024有已见spot训练影响；#49 Sep H、2025 outer保持保护；2026有#45 Dev、Jan/Feb lagged-pressure、Apr–Jun cross-asset、Jul/Aug basis/既有日线消费或保留，未确认足够长连续独立D再加H。只比较SOL、ADA：官方上市分别2021-01-22、2020-03-13；ADA #61 S[2024Apr1,2025Apr1)已评价，D[2025Apr1,2026Apr1)仅QC/物化、未执行、Agent语义暴露UNKNOWN，H[2026Apr1,May1)封存。不把QC等同消费；ADA仍不是全未消费S首选。选择不依据收益/信号数，不查第三币。[SOL上市](https://www.okx.com/en-eu/help/okx-to-enable-margin-trading-savings-and-list-perpetual-for-sol-lon)、[ADA上市](https://www.okx.com/en-sg/help/adausd-adausdt-perpetual-swap-now-available)、[#61](https://github.com/He1met/freqtrade-lab/issues/61)。历史流动性/可成交性UNKNOWN。

**暴露。** #57 SOL请求OHLC/mark至2024Jan1，funding失败后未发布/保留source；0 Search不证明完全未接触，请求也不证明永久研究消费。#58校验2022–2023 funding、未做经济分析，但这些月份不符0..2000ms规则；不重用。2024Jan H含pre-roll仍封存。所查元数据未识别SOL自2024Feb1起评分值被Agent查看/择模；同日期其他币研究影响保留。等级：**限定范围无已识别消费/适用封存，外部未登记UNKNOWN**，非全球绝对盲测。[#57](https://github.com/He1met/freqtrade-lab/issues/57)、[#58](https://github.com/He1met/freqtrade-lab/issues/58)。

| 数据层 | 现有方案允许的接触 | 不得冒充的结论 |
|---|---|---|
| 物理取数 / 确定性 QC | 监督最新澄清允许 S 前一次准备 S+D，由可信 producer 仅完整性检查；给 Agent 的输出限元数据 | 不等于 Agent 看过 D，也不等于已通过 D |
| Agent 语义查看 | S 只见 S 切片/结果；D 图表、统计、信号、值和结果入口保持关闭至 finalist 固定 | 文件存在不是消费证明；实际暴露不清保留 UNKNOWN |
| 评价 / 择模 | S 两次后冻结唯一源码；D一次不择模；H/Stress一次、无救援 | 同币时间顺序成立不代表市场环境统计独立 |

**取数包络。** S+D 完整 source 的 OHLC/mark 为 [2024Feb1,2026Feb28)，funding 选择 [2024Mar1,2026Feb28)。需要2024Mar–2026Feb共24个月包，预计 raw UTC+8包络 **[2024Feb29 16Z,2026Feb28 16Z)**：多取开始前8h、截止后16h及完整 D，末端仍早于 H Mar1。H另取2026Mar–Aug六包，预计raw [2026Feb28 16Z,2026Aug31 16Z)，其首8h及尾16h不评分，尾部以后不得假装未接触。实际 raw 时间戳未验证；越界、缺失、漂移即阻塞，不能补零或扩窗。不能将 D.stop 改为 Mar1，因为那会额外下载含 H 的 March 整包。

官方 funding **30个月 L2目录已确认**（5组×6个月，全200，无429）；未下ZIP。OHLC/mark仅官方接口能力 L1；全窗连续性、funding L3/归一化、历史合约限制、精确源绑定全 UNKNOWN。当前instrument状态也未新查。[官方历史资料](https://www.okx.com/en-gb/historical-data)。

**现有S/D链。** producer一次取S+D；`bounded_research.py:_load_search_source/prepare_search_data/prepare_development_data`分别裁切，`research_console.py:847–865`核相同source SHA，支持正式Profile→same-profile D；不必新增分期系统。若后发现S真已用于择模，须保留EXPLORATORY_ONLY，现D拒绝该标签；不能洗标签。**监督补充、已独立确认：`_profile_window_contract:1144–1146`每阶段≤366天，H原883日S会被consumer拒绝，不是仅缺factor。** 本365/364日符合代码容量，不等于样本充分；更长窗需单独窄duration guard验收，并非必然大平台。

**真正挡住完整链的是 Profile 1d H/Stress。** `holdout_run.py:281`不传 Profile 给 Development preflight，触发 `development_run.py:511–516`旧60日限制；`holdout_run.py:332`又限定5m；显式Search Console直接封闭H。`bounded_research.py:2063–2075`及 `holdout_run.py:1030–1048`还强制 D/H邻接。改启动参数不能解决。最小后续工作是沿现有六表/JSON与一次性同Run流程，接 Profile/1d、冻结一天间隔、授权后H-only acquisition与Stress成本、同Run验收；不建平台，不改原封存/旧绑定。估计 **8–16活跃小时**（未经实现验证），先限时范围审查；不并入I的factor补丁。

**事前门与终态顺序。** 保持H两份源码SHA、28/14规则、唯一盘整增量、双向1x/stop8%、wallet2000/stake400、每腿基础5bps及额外2bps。提议 S/D各≥24、H/Stress各≥12（半年仅覆盖下限，非统计功效）；各阶段native及额外成本净≥25USD、native PF≥1.10/DD≤15%、holding非NULL且≥0、ROIexit0；Stress按fee×2另跑同窗。R2在S还须双净及price gross/entry notional都优于R1；附加门不得被原生finalist投影绕过。方向/季度/持仓/benchmark只诊断。365/364天约每15天一笔才能过24，能否达到 UNKNOWN；不足或失败即终止，不调门/扩窗/换币。D/H不得合并评分；全部通过才可提交人工合格判定，仍非可交易证明。

**唯一下一门：监督先冻结完整路径、一天间隔及后段预算，再决定是否授权这份365日S的source/consumer验货。** 无须为尚不存在的finalist提前实现H；但自动生成H=Feb28的旧metadata与本提议Mar1不一致，必须在S前明确绑定处理办法，不能结果后无痕换窗。H代码仅在合法D通过、用户授权前兑现，不能称I补丁已闭环。本任务只写两文件；零新行情/封存值、ZIP、回测、DB/ledger/GitHub/代码/服务变更。公开旧结果未用于选币/选窗。
