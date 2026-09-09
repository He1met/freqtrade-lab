# 下一机制决策：滞后已结算 funding × 拥挤后转弱

**选择一项值得检验的假设，尚无合格策略：每日一次观察价格转弱，以至少滞后32小时的已结算 funding 识别残余多头拥挤，检验随后8小时的下行。** 建议监督下一步只授权最小接线及合成语义门，过门后再冻结、授权两次历史探索。当前代码不能直接执行此信息增量；预计总计5–8活跃小时，不应按“已有funding记账，所以零工程”安排。

## 1. 选择依据与两个候选

当前40bb干净但为旧main `dc82c61`；本次只读审查准确实现 `8ae57c1ff05baa9fb6aa0dfcef83554e17890873`。交付前已核 PR70 MERGED、#69 CLOSED、远端main `869b0d394a95f45bbcf0d25ae16dc61031a092ba`。没有切换工作树。A/B全部指定合同/终态SHA匹配；A两次费用前即负。B原生审计显示R1价格毛额+221.7561、funding−1.146269、交易费394.491057、净−173.881226 USDT；R2分别−76.8608、−1.550210、109.865760、−188.276770。公开 `gross_profit_before_fees_pct=net+交易费` 仍含funding。弱毛边际不足付费，低活动过滤又损害毛收益；减少交易不是alpha。

| 候选 | 经济机制与判断 | 技术 / 窗口 / 经济不确定性 |
|---|---|---|
| 日级冲击延续＋高成交量 | 信息逐步进入价格；低成本表达，但**不选**。旧AVAX已用range-expansion＋volume-increase-filter，BTC亦有positive-shock＋signed range-volume。换日级/持有期无法证明新信息。 | OHLCV可表达；已有探索历史可用但非独立；高量混合投机和风险转移，不能确认知情成分。即使有新严格filter，信息重复仍未解决。 |
| 已结算funding拥挤＋价格转弱 | **选择**。多头支付高资金费反映杠杆需求，价格转弱后可能出现去杠杆延续；唯一增量是过去的衍生品持仓成本信息。 | 原生可读取历史funding，项目尚不允许该信号接线；历史as-of发布时间UNKNOWN，采用明确32h以上滞后假设；费用后的正收益、8h预测力均UNKNOWN。 |

这不是旧spot-perp现金套利：不持现货、不对冲两腿、不将年化basis当作每期funding收益；价格损益、手续费、实际持仓funding分别核算。旧basis账本第47行 `RETIRED_TECHNICAL_CAUSALITY_UNPROVEN` 保留。#62为资金费时间漂移数据失败，#66为原生兼容性阻塞；#68的固定订单流规模RSS NO_GO不因本计划解除；#65简单双均线仍退役。

**实际阅读的四份主要一手资料：**

- [Llorente等，Dynamic Volume-Return Relation，2002作者稿](https://web.mit.edu/wangj/Public/Publication/Llorente-Michaely-Saar-Wang02.pdf)，正文pp.1005–1008、1018–1023：NYSE/AMEX，1993–1998，2226只至少交易1000天股票；日收益，去趋势换手量，横截面信息不对称代理。检验条件自相关，不是扣除手续费/借券费的可执行净策略。高量可延续也可反转；本项目单币成交量不等于其横截面识别。
- [Schmeling等，Crypto Carry，BIS原始2023稿](https://www.bis.org/publications/working-paper-1087-crypto-carry.pdf)，已读封面、摘要及引言pp.1–4；版本2023-03-24，BTC/ETH，跨交易所，主要区间2019-04至2022-01；讨论日级持续性及一个月到期预测。basis为到期期现差、不是LINK永续的已结算费率；引言约10%年化carry没有证明本方案扣费净回报。预测衰退/拥挤风险给出机制动机，8h外推与单币阈值由本计划提出。旧BIS链接和SSRN失败后改读BIS新版页面实际链接；未把2025修订样本混入2023稿。全文其余表格成本实现细节UNKNOWN。
- [Freqtrade Backtesting官方文档](https://www.freqtrade.io/en/stable/backtesting/#assumptions-made-by-backtesting)：下一根open信号成交、OHLCV无实际滑点、stop与信号有既定优先次序。本轮规则仍须合成原生验证。
- [Freqtrade Strategy Customization官方文档](https://www.freqtrade.io/en/stable/strategy-customization/#funding_ratepair)：实时 `funding_rate()` 不能当历史预测数据，历史数据必须按时间合并。stable文档可能新于2026.7；本计划以所读本地原生2026.7源码为执行准绳，不照搬新文档列名。

## 2. 可证伪的冻结提案（尚未执行）

**市场与两轮：** LINK/USDT:USDT，OKX linear perpetual/isolated，5m执行，short-only，1x，单仓。R1价格转弱对照，R2只增加funding条件；两份都计算同一funding特征并要求可用，避免数据缺失造成不公平的样本选择。R1/R2源码、成本、时钟、停止条件和日期需在新市场值读取前一起冻结；R1有效即执行唯一R2，即使R1亏损。最多2次真实Search，真实smoke算R1，不另跑，不扫描阈值/币种/时间；技术/数据失败保存后停，经济负或样本不足结束此版本。

令D为每日UTC 00:00，t为D开盘、00:05刚闭合的bar（date是open标签）。`r24=close_t/close[t−288]−1`，要求289根所需价格/量有效、正值且UTC连续。R1仅在 `r24<=−0.02` 时于00:05 next-open做空；阈值是事前定义的2%价格转弱事件，不来自历史最优参数。R2唯一附加 `F_D>0.0001`：F_D为D−48h、D−40h、D−32h三个精确8h结算事件的平均已结算费率，正数代表多头支付；1bp/8h是有经济含义的正资金费水平，未声称其最优或等同杠杆清算。

退出信号只在同日08:00 bar闭合后发出，next-open 08:05退出；因此正常持仓8h，固定 `stoploss=−0.03` 可提前退出，`minimal_roi={}`。入/出时钟互斥；每日最多一次，连续冲击日各自处理；不做多、不翻向、不止损后重入、不加仓。00:05/08:05使成交不恰落结算边界，持仓跨过08:00的实际资金费仍由native计入。完整数据中最后有效入场也有同日退出；任何native `force_exit` 单列且核查原因。没有恒真exit，没有custom_exit/时间ROI或“变长持有=固定8h”。UTC时钟也需新增窄白名单，现有纽约时区规则不能冒充UTC。

**资金、样本、成本：** wallet2000、fixed stake400（20%初始wallet），3% stop约12 USDT即0.6%wallet风险加成本；预留余款用于费用/结算，仓位不用于放大门槛。至少5bps/side、真实signed funding；另按逐腿实际notional扣2bps/side作为说明性冲击，实际滑点UNKNOWN。native门：净额≥25 USDT且>0、PF≥1.10、peakDD≤15%、ROI exit=0；额外冲击后亦≥25。25是预先选择的非零经济筛查下限，不是统计显著性或预期利润，沿用可比门而非结果后放宽。PF/DD原生值不能称包含附加扣减。

两者至少20笔；R2原生净额和扣减后净额均须严格超过R1，且自身通过上述门。日历配对并列每个机会的入场/跳过及净差；同时报均笔价格边际、funding、费用、持仓、月份和最大单笔贡献，不从中删除亏损月份。若R2不足20即underpowered并结束，不扩窗补数。窗口152天，funding滞后使最早两天不交易，**最多150个每日决策槽，实际bar信号数、可执行成交数与独立有效样本都UNKNOWN**；20只是覆盖至少约13%槽位的探索筛查，不用高斯块数预测成交。止损不增加当日机会。以近似每笔400 notional，N=20达到25需31.25bps/笔净边际；加10bps费及4bps说明冲击，价格毛边际约需45.25bps，再减实际平均funding收入（支付则增加）。N=40约29.625bps。2%是已发生运动，绝非后8h利润预报。

## 3. 最小缺口、窗口与下一安全门

**不是零改动。** `8ae:lab/bounded_strategy.py`只准OHLCV、3个populate、5m/1d、固定导入与NY时钟；不准任意DataProvider/merge。`search_campaign.py:1478`已有严格单因素helper可复用，但没有funding过滤。原生2026.7 `DataProvider.get_pair_dataframe()`能按 `funding_rate` 读本地历史；项目producer把费率存于OHLCV的 **open**，close/high/low/volume为0。原生history默认可能将8h事件按1h补行，不能直接rolling(3)或把补出的0当真实结算。`merge_informative_pair`给1h资料加55分钟到5m的open标签，对更快资料合并到1d则拒绝。因此不靠daily直接合并来隐瞒工程。

最小方案是在既有策略验证/生成路径加入**一份固定历史funding模板**：仅当前metadata pair、固定1h funding类型；在producer/consumer已经证明完整exact 00/08/16 UTC事件网格后，从native读出的1h表保留这些事件（真实零费率保留），取open、rolling3，再用原生1h→5m合并并shift288根。每日00:05决策最终应恰等于上文48/40/32h三事件；缺值禁交易、禁止bfill/实时API/任意路径/额外资产。不能依赖“填充后网格完整”证明原始完整。289只表示OHLCV pre-roll；funding特征另需48h的Search内部烧入，不能把三个8h事件当三根5m K线。模板需绑定来源SHA、时间范围及既有JSON合同；禁放开通用代码执行能力。

预计：native列/补行/事件网格/滞后2–3h；受限模板、UTC白名单与静态lookback/合同/生成提示1–2h；唯一funding conjunct及全剩余AST相等0.5–1h；定向合成Console/API回归1.5–2h，合计约5–8h活跃工作，机器运行时间另计。**先用60–90分钟确认同一native链路的零费率/缺事件/补行/时间边界/三事件选择；不能忠实表达即停止报告，不改native或自制runner。** 数据输入仍是已有三类，不新增服务/表/字段/索引/队列/缓存。零改动替代只测价格R1，不能识别funding增量，又接近退役价格机制，故不建议花新经济尝试预算。

拟议新探索窗 `[2024-03-01,2024-07-31)`，仅metadata规划。pre-roll289根5m从Feb28 23:55Z；mark从Feb28 23:00Z；依当前合同预计OHLCV44065、mark3673、funding456行。完整funding月包March–July预计raw `[Feb29 16Z,Jul31 16Z)`，正式原始时间戳审计须核实际边界。这些区间包含在A/B已接触历史范围内，**仍是同一个已见LINK探索池，新的信息假设不产生独立数据**；需另建冻结cohort，不能续写A/B两轮或给其“第五次”救结果。本轮没有读其source或建立消费者；下一任务需决定合法的独立运行root/source绑定，不能手工拼JSON绕过producer。现成5m源不能因标签相似就跳过新pre-roll/合同校验。

global账本当前77行、SHA未变；旧索引消费记录只作局部覆盖，不能证明所有外部运行未见。#49/#52已执行Dev可降格探索，不释放未执行Dev/H；其Sep/Oct起H、2025 outer及#62等保护均保留。当前已验证、可直接用作真正未见Dev的历史窗口为 **UNKNOWN**，这不阻止上述合法历史探索。若R2成为探索候选，冻结源码/门/总选择次数，先做metadata-only独立窗审计；若无可证明未见窗，前向预留180个完整UTC日，最早从最终冻结之后开始，先完成因果特征warmup，预注册一次Dev、至少40笔，未达即不足而非延长到盈利；另预留后续180日Holdout/Stress，逐阶段单独授权。未来费率实际可用时点应同步记录，替代历史archive无法证明发布时间的局限。历史32h滞后是明确保守建模假定，不是历史as-of已经证明。当前探索finalist不能自动转ResearchRun；需复用/审查既有独立验证绑定路径，不能伪造日期或待跑状态。

交付仅此计划与metadata；未开发、取新行情、回测、读取DB或封存市场值。首次ledger浅层过滤误带已有公开的嵌套旧汇总，已记录为输出范围失误，后续使用显式metadata白名单；无须借此重新发起权限阻塞。下一步是监督决定上述最小接线与合成门，文献/计划不叫READY，更不叫找到合格策略。
