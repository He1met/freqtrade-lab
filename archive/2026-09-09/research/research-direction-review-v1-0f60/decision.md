# RESEARCH_DIRECTION_REVIEW_V1

**修订提案：GO，仅建议另行授权 A 的“近期日档×官方API同ID桥接＋原生JSON合成验收”小 Gate；G2及真实策略研究仍 NO-GO，B/C仍不选。** 先前只等待2024专属语义材料的结论过窄：January诊断失败限制该次G1，不应永久限定整个机制的取证日期。以下是新协议提案，本轮未获采集／执行授权；#66原样停止。

2026-09-05 北京时间核验：本 worktree clean、detached HEAD 与实时 remote main 均为 `dc82c61fe8a27a654977344755c088412518d858`；原 checkout 的 `docs/product-requirements-v1.md` 未提交内容保留。原生 2026.7/`52bc96f…` clean。#66 最新监督回执为 OPEN/BLOCKED，#62 OPEN/旧 BLOCKED_DATA 不动。指定四份证据 SHA 全部匹配，详见同目录 [review-metadata.json](review-metadata.json)。G1 仍为 `BLOCKED_NATIVE_COMPATIBILITY / STOPPED_AT_G1`：独立 FLOW 通过，native backtest 未调用，一bar/R2/stop/force未运行；真实 Feather 写读因父目录缺失未完成，不能称数据坏。本轮没有执行测试或研究。

| 路线 | 经济依据与独立证据机会 | 因果数据、原生链路与维护成本 | 决策 |
|---|---|---|---|
| **A 真正 taker 信息／原 LINK 一bar承接假设** | “转涨且sell share≥.60预测下一5m”仍弱；[Cont等](https://arxiv.org/abs/1011.6402)是股票同时间、含挂撤单的订单簿OFI，不能支持该精确预测。单bar成本压力大。 | 官方支持最近三个月API与逐笔日档：同ID字段桥接可成为主动、低成本证伪入口。原生JSON为既有配置，仍需隔离与RSS实测。 | **选作唯一下一小Gate**：约2小时活跃上限即可否定输入／配置不可用；不是因为已有沉没工程而选，也不是策略研究GO。 |
| **B 现货多头＋永续空头 carry** | [BIS](https://www.bis.org/publications/working-paper-1087-crypto-carry)给出杠杆需求与套利资本约束解释；三者中收入来源最直接。但[永续没有到期收敛保证](https://arxiv.org/abs/2212.06888)，资金费可反向，保证金及融资占资本。不能拿未对冲单腿替代。 | 官方有现货／永续／资金费档案入口，但不证明历史资金费何时可知。Lab consumer/artifact 仅 futures；原生单一 trading_mode 未提供已验证的双腿同步成交、融资、结算和共同权益链路。两份回测相加或会计模拟均不合格。总工程工期 UNKNOWN，超出当前可承诺的原生窄接入。 | **NO-GO**。经济动机较强，却是已试过的方向且当前执行模型不忠实；不为它搭组合平台。 |
| **C 波动率管理的 BTC／现金真实敞口** | [Moreira–Muir](https://www.nber.org/papers/w22208)依据是波动率变化未获同比例预期收益补偿，主要证据来自股票因子／货币；[后续样本外研究](https://www.lehigh.edu/~xuy219/research/COWY.pdf)不支持普遍优越。[Bitcoin研究](https://www.sciencedirect.com/science/article/pii/S1062940824001852)是股债组合与政策状态结果，不证明独立 BTC 策略。 | 闭合 OHLCV 可估滞后方差；须真实调节仓位和剩余现金。原生 callbacks 存在，Lab AST 不允许，spot入口亦未支持。仅 callback 窄接入估2–4工程日，未含spot与指标合同差距。月／周调仓不等于独立交易；长期单仓即使多次部分成交，仍不能产生足量原生 Trade 样本或可解释的 PF。 | **NO-GO**。不得换成 binary filter、暗加杠杆、全样本归一化或人为平仓造样本。不能为过 PF 改写论文机制。 |

B/C **不是新发现**。给定持久 ledger 与三个 correction receipt 的 SHA 已核对：B 的 July 2026 cohort 为 `RETIRED_TECHNICAL_CAUSALITY_UNPROVEN`（杜撰 settlement+1s 可知时刻、未来整窗价格参与资金准入）；42项 accounting PASS 不是有效经济研究。C 的 2022 cohort 为 `RETIRED_TECHNICAL_ACCOUNTING_INVALID`，2020 cohort 为 `RETIRED_TECHNICAL_DRAWDOWN_INVALID`；2018方案后来 `BLOCKED_DATA`。这些失败不证明机制亏损，也不允许重放、把保留的 Dev 改作 Search，或继续换年份／币种。

A 的新增静态发现：[2026.8](https://github.com/freqtrade/freqtrade/releases/tag/2026.8)、实时 stable `9f10e357…`、develop `31cea07c…` 均仍用最后一根 open 构造 stop，Arrow 使用 `<=stop`；[#12151](https://github.com/freqtrade/freqtrade/pull/12151)引入范围过滤，近期 [#13525](https://github.com/freqtrade/freqtrade/pull/13525)是性能改动。增大 max_candles/cache 不修复该上界。不过原生 [`dataformat_trades=json/jsongz`](https://github.com/freqtrade/freqtrade/blob/52bc96f4480b1a0da6a9b455bd00b17fbb6786a5/freqtrade/data/history/datahandlers/jsondatahandler.py#L122)会忽略 timerange、整文件加载，可能避开 Arrow 截断；只是源码推断，未测试，且必须使用物理隔离文件并实测资源。它不改变原 Feather G1 的失败、预算或冻结断言。

[OKX目录说明](https://www.okx.com/docs-v5/en/#public-data-rest-api-get-historical-market-data)支持module1/SWAP/daily，日期按UTC+8、覆盖仍在回填；[history-trades](https://www.okx.com/docs-v5/en/#order-book-trading-market-data-get-trades-history)支持最近三个月、`type=2&after=timestamp`取更早成交、单页最多100条，并定义side=taker、sz=contracts。这不自动证明CSV，但**近期日档与同ID官方API字段逐项一致**可直接补证该样本；无须先解决January2024语义。实际滚动保留、日档存在、CSV/API是否同原始ID仍UNKNOWN，不能从文档或文件名猜出PASS。

成本与有效样本须先算清：按旧 A 的 wallet1000、stake100、每边5bps，用固定仓位一阶近似，若只有30笔，达到 wallet净1.25%要求每笔平均仓位净约0.4167%，加往返费后毛约0.5167%；300笔时毛约0.1417%，均还未计滑点／资金费。这是门槛算术，不是预期收益。B 若两腿各占一半无杠杆资本，wallet净1.25%需要单腿名义上约2.5%的收益贡献，另需覆盖四次成交及融资成本。C 的低换手不自动解决均值估计：月度调仓一年最多12个调仓时点，不能把日K线或部分成交当独立经济重复。

**唯一下一 Gate 提案：`LINK_RECENT_ARCHIVE_API_JSON_GATE_V1`。须先获监督明确授权，在新唯一Issue冻结以下范围、源码／fixture SHA和停止规则，然后才能执行；当前一项也未执行。**

1. **唯一拟样本与调用**：目录日2026-06-08（UTC+8），目录GET一次；只接受它实际返回的唯一LINK-USDT-SWAP日档URL，禁止猜URL／退回月档。API GET一次，固定`type=2, after=1780905600000`（June8 08Z）, `limit=100`；禁止分页／换截点。要求100条均在拟日档范围内且buy/sell均存在。API不满足即止，不下载ZIP。随后唯一ZIP GET一次、完整有界扫描一次；只解释匹配ID的价格／数量，其他行只查timestamp/ID。逐项比对instrument、trade_id、毫秒timestamp、side、精确Decimal price/size，任何缺失／重复／聚合ID差异即停；不计算真实flow、信号或PnL。
2. **预算与原生**：活跃工作≤2小时；目录≤64KiB/30秒、API≤256KiB/30秒、ZIP压缩≤16MiB/300秒、累计解压≤128MiB，扫描≤300秒；受控子树RSS≤2GiB，无法落实即停。新Git外root仅选`dataformat_trades=json`，原版本／R1/R2及原合成fixture期待不变，最多FLOW及原5个执行案例各一次、每次≤300秒；原生handler写读、完整DataProvider路径、尾根+1/+2ms、一bar、R2/stop/force均须原样验收。无补尾K线／改时间／弱化断言／引擎patch；实质失败立即终止，不跑后续案例。真实100行仅可作**合约数量格式**roundtrip，未证历史contractSize前不得宣称base amount正确或喂真实策略。
3. **小Gate成功的限度**：桥接通过仅支持该日／该样本；JSON合成通过仅支持该配置的原生执行语义。历史contractSize、跨文件版本／全窗完整性、JSON全研究窗RSS、funding合同及Lab接入仍需另证。不得把两个局部PASS合称#66/G1恢复、全窗READY或经济通过；G2仍须独立范围决定。

**日期可行性（仅算术及metadata，未选择／冻结研究日历）**：拟日档范围[June7 16Z,June8 16Z)，实际须查内容。June8 08Z在Sep4 22:29Z约88.6天前，处于90天和日历三个月的算术范围内，API保留仍未实测；建议新协议仅在Sep5 08Z前启动，错过即过期，不自动滚动换样本。例示pre-roll June14，Search[June15,July1)、Dev July、H/Stress August均已历史闭合；诊断末端距pre-roll128小时。Search16天只有4608根5m评价K线，不是4608个独立事件，30笔及经济底线均不降低。

给定小索引去重114条＋77条ledger未发现这些日期的LINK消费；#66 January暴露及预留2024日历也不相交。因此仅为`NO_IDENTIFIED_LINK_CONFLICT_IN_CHECKED_SCOPE`。BTC/XRP/AVAX等有同日历暴露，不是全市场独立时期；若要求跨币日历也完全未消费，此例不合格，不能暗换窗口。范围外未登记运行UNKNOWN，正式冻结前仍须核对精确metadata身份／sealed合同。

新协议不与#66停止承诺冲突的条件：旧“不得换日／源重试”继续约束原G1；新Issue必须明示是**另行授权的同期API桥接和原生存储配置实验**，不得改旧证据、预算或终态。本轮建议不构成该授权。小Gate预计活跃1–2小时、网络／扫描／合成硬上限合计约41分钟、无市场日历等待（实际耗时UNKNOWN）；不自动等待／监控。A后续窄接入仍粗估1–2工程日、全窗执行/RSS未知；B/C的总成本及此前NO-GO判断保持。

所有后续提案保留 **net>0 且≥1.25% wallet、PF≥1.10、DD≤15%**，周期／持仓／样本数必须在新值前根据机制和有效观测量确定；不事后降门槛。仍须 Search→独立 Dev→用户另行一次性授权 H/Stress，同一 research_run_id。January raw 整包已暴露；原 Feb/Mar/Apr 草案撤回，Mar Search／Apr Dev／May H及Feb29 pre-roll仅未授权 metadata。H/Stress 全部 SEALED_UNREAD。本轮没有新增窗口，旧负面／技术退役及 #62/#66 均保留。
