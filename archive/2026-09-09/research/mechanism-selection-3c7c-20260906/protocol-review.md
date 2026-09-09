# 建议一次检验：LTC_VOLUME_LIQUIDITY_REBOUND_V1

**交付状态：REVIEWABLE_PROTOCOL；尚未冻结或授权采集/Search。** 建议用 OKX `LTC/USDT` 现货日线，检验“异常放量的显著下跌可能包含短期流动性抛售，下一开盘承担风险，持有两天获得补偿”。只推荐这一条完整规则、一轮一次 Search。当前盈利、真实样本量和成交量增量贡献均 UNKNOWN。

这属于**条件反转家族内的新假设**，不是已证实的新独立因子。与过去低活跃反转有亲缘关系；不能把高/低量谓词翻转、换成 LTC 或新增几个常数算作独立发现。本次选择的增量是明确检验高量下跌的流动性补偿解释，不是替旧负结果救援；没有胜率或收益率承诺。

## 为什么选择它：三个机制、六份原始资料上限

| 机制与原始依据 | 样本、成本、独立性与复现 | 本次决策 |
|---|---|---|
| **流动性供给／量价条件反转**：[Campbell–Grossman–Wang (1993)，作者 MIT PDF](https://web.mit.edu/wangj/www/pap/CampbellGrossmanWang93.pdf) | 主样本美国股票 1962–1987，扩展至1988，并检查更早指数及32只大股票；高量时日收益自相关下降。是模型与分样本计量结果，不是本规则的费后交易回放，也不是今天的加密 OOS。原始 CRSP/成交股数数据不随论文免费交付。 | **选一次证伪**。风险厌恶承接者需要价格补偿，方向与1–2日尺度明确。24/7市场的强制／流动性抛售可能适用是推断；成交量不能识别知情交易、洗量或真实清算原因，坏消息持续发酵会使本假设失败。 |
| **价格信息的迟缓反应／动量**：[Liu–Tsyvinski (2018 working paper)](https://www.nber.org/system/files/working_papers/w24877/w24877.pdf)；成交量扩展：[Huang–Sangiorgi–Urquhart (2024)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4825389) | 前者 BTC 2011、XRP 2013、ETH 2015 起，均至2018-05；有以前两年确定分位点的后续样本检验，未核实可执行费后逐腿账。后者作者摘要称量加权 winner-minus-loser 优于其他 TSMOM，排除若干因子和洗量解释；全文403，确切样本年代、OOS切割及成本处理 **UNKNOWN**。 | 价格动量有更直接的旧加密证据，但重复已研究动量家族；不能把摘要中的多资产多空组合改成单币“放量追涨”冒充复现。真实量加权组合需要点时资产集合、多个源与组合会计，当前单币链路不能忠实承载；约2–5主动工作日的有限组合适配只是估计，本次不建新 runner／多腿平台。 |
| **波动预测与风险配置**：[Moreira–Muir (2017)，作者 PDF](https://amoreira2.github.io/alan-moreira.github.io/VolPortfolios_published.pdf) | 美国因子长样本主要1926–2015，其他因子起点不同；月度按前月实现方差反比缩放，讨论交易成本和杠杆限制。主要展示长样本表现，归一化常数使用全样本；不等于冻结常数后的本市场独立检验。 | 暂不选。它主要改善已有风险溢价的持有方式，不能替代正的价格收益来源；已知 BTC 类似家族有历史技术退役记录，不冒称经济证伪。忠实复现需要动态仓位／再平衡；若日后批准，有限回调与会计测试估计1–2天，有研究价值，但不能用固定 stake 加“低波过滤”冒充原机制。 |

另两份执行原始依据是 [OKX API 文档](https://app.okx.com/docs-v5/en/#order-book-trading-market-data-get-candlesticks-history) 与本地固定 Freqtrade 源中的 [backtesting.md](/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade/docs/backtesting.md:541)。合计四篇论文＋两份官方执行资料，没有把检索摘要中的其他论文纳入选择依据。

**信息差别。** 波动和均线仍是历史价格的函数；基础币成交量是另一条实际观测，可区分相同跌幅下不同交易活跃度，但具有内生性，不能直接称独立信息。原论文主要使用市场换手率，本方案用单交易所基础币相对量作代理，这是待检验的映射，非原论文复现。此次只检验完整交易规则，不做消融或第二个 native 路径。即使通过，仍不能单独归因于 volume；不得把删掉 volume 的版本登记为另一 MECHANISM_SEED，或失败后晋级诊断臂。

## 值前固定的资产、窗口与历史接触

资产在看行情收益前锁定为 `okx / SPOT / LTC-USDT / LTC/USDT / 1d (1Dutc)`。选择依据是长期非锚定资产身份、现货单腿可执行性、官方当前 `live`，以及 `listTime=1611907686000`（2021-01-29 08:08:06 UTC）早于本次前史。身份响应还给出 `minSz=0.01 LTC`、`lotSz=0.000001`、`tickSz=0.01`、`maxMktAmt=110000`；这些只证明当前限制，**不证明历史连续性、历史点时限制或流动性**。没有查询 ticker、盘口、价格、成交量或资金费率；不设置失败后的替补币。

| 阶段，UTC左闭右开 | 评分日数 | 40根前史起点 | 隔离输入行数 | 完整30日历块上限 |
|---|---:|---|---:|---:|
| S `[2021-05-01,2024-01-01)` | 975 | 2021-03-22 | 1015 | 32 |
| D `[2024-01-01,2025-01-01)` | 366 | 2023-11-22 | 406 | 12 |
| H `[2025-01-01,2026-05-31)` | 515 | 2024-11-22 | 555 | 17 |

首次源仅 `[2021-03-22,2025-01-01)`，应1381行。D只交 producer作连续性/字段QC，不向模型展示行情或经济指标；S消费者只得到1015行。H目前仅拟预留，不采集；未来另授权时自己的40根前史来自D尾部，不对前史评分。日历块不是有效样本数，实际交易、活跃块、相关性与置信区间均 UNKNOWN。

[必要曝光投影](/Users/shenjianpeng/.codex/runs/freqtrade-lab/mechanism-selection-3c7c-20260906/exposure-projection.json)核对的全局ledger为93576字节，SHA `8defdf5888380fe9c0ae95a99cc15be3c140de392441d67e7f229b893dd20f49`，99个非空记录中未命中LTC身份。它支持“没有已知LTC占用”，不能证明外部未登记接触为零。BTC/ETH训练曝光、其2025封存、ATOM/XLM已消费S与仅QC的D、未取封存H都保留；DOT时间戳阻塞不改称经济失败。原生资产、现货／合约、跨交易所同币同段不被当作独立样本。LTC与加密市场的相关性未读取，不能把不同币同一历史危机算作新的独立市场验证。独立验证目标是**同一冻结规则的未来于S/D的时间窗口**，不是跨币独立性的主张。

## 唯一入出场规则

按UTC日K开盘时间编号t，收盘后才用当天完整OHLCV。记 `r_t=C_t/C_(t-1)-1`，`vbar_t=前30根V均值`，`m2_t=前30根r*r均值`，`liq_t=前30根(V*Low)最小值`；后三项全部截至t−1，不含当天。m2是二阶矩尺度，不冒充去均值实现方差。

1. 基本事件 `Q_t` 同时满足：`r_t <= -0.02`；`r_t*r_t >= 2.25*m2_t`；`V_t >= 2*vbar_t`；`m2_t>0, vbar_t>0`。这固定了显著负向冲击与异常成交活跃，而非任意小跌幅。
2. 唯一买信号 `E_t = Q_t AND 前3根均无Q AND liq_t >= 500000 USDT`。下一根 `O_(t+1)`入场；初始资金1000 USDT、固定stake500、最多一仓、long-only、无杠杆、不复投扩仓。过去三日事件去重是限制同一抛售簇和保证静态退出排程，不依据结果改变。
3. 唯一时间退出信号在t+2收盘生成，即 `E.shift(2)`，于 `O_(t+3)`执行：无止损时持有48小时。期间原生价格止损为−8%，`minimal_roi={}`；没有均线出场、趋势过滤、追踪止损或加仓。同bar按原生顺序处理；止损后仍不提前结束预定事件冷却。
4. 30日量与波动尺度、2倍量、1.5倍二阶矩尺度、2%下跌、两日持有均是**本协议事前操作化**，不是论文最优参数或复现参数。2%事件相对基本/压力约0.4%/0.8%往返摩擦要求约20%/40%的价格回补量级，仅作盈亏平衡量级比较，不能预测一定回补。8%止损、50%资金仓位服务风险预算，不代表现金最大回撤8%。

上述只需静态算术（平方写作乘法）、`shift/rolling/mean/min`和三个populate方法，40根前史覆盖依赖链；不需要custom_exit或新指标库。本次仅核对现有源码支持的表达式，**未写策略或运行validator/native**。授权准备时须用合成样例验证事件在t+1入场/t+3退出、相邻冲击去重和同bar止损，不许以测试为由读取行情。

原生先trim前史再shift信号；不允许前史交易带入阶段。每阶段现金重新从1000开始，仓位不跨阶段继承。若期末存在唯一未到时间退出的仓位，使用原生期末平仓并计足成本；不将其算自然完成交易。该笔必须单列，且**剔除该笔后净收益仍须正**，不读取下一阶段补足48小时。

## 事前晋级门与失败停止

所有门取交集；内部 native finalist 只可候审。以下对S/D/H分别检查，统计CI只在D/H且前面决定性门通过后计算。

- **经济与风险**：native费后净收益严格正、PF≥1.10、native DD≤20%；每腿fee=0.001，另扣每腿实际名义额×0.001滑点后的净收益严格正，逐日现金＋持币按当日close盯市（持仓扣预计清算费用）的cost-MTM DD≤20%。核对native实际q与每腿费，不重复扣费或用stake固定乘笔数替代。
- **成本承受**：同一已实现路径上fee=0.002、额外slippage=0.002每腿的敏感性净收益仍>0；重建现金，每次必须付得起完整500 stake及费用，否则失败，不缩仓。S/D这个算术检查不是第二次native或精确滑点重放；H Stress仍需同一run的单独授权原生双倍fee执行后补滑点。
- **成交可行性**：事前liq门把stake限定为过去30日每日保守成交额下界的0.1%以内；还核对每个实际成交腿数量≤该日总基础币volume的0.1%。后者是回放可行性检查，不能倒灌进信号。不把全天量等同开盘深度。止损日若open低于原生stop，须用更差的open补足跳空损失及摩擦；若无法在原始事件/成交记录上保守核账，记技术/模型保真阻塞，禁止拿理想止损晋级。当前历史精度限制与开盘深度均UNKNOWN，任何已知不满足的交易限制均阻止晋级。
- **样本与集中度**：各阶段≥12笔自然完成交易；按阶段起点固定30日非重叠块，将跨块交易全部归其入场块，末尾不足30日块不计完整活跃块；完整活跃块S≥8、D≥6、H≥8。块只是聚集检查，不是IID证明。移除成本后最好完整块，保留其他损益后的净收益仍>0；完整活跃块中正收益块须严格过半。反复发信号或期末强平不能凑自然交易。
- **时间证据**：D/H分别对整段逐日基本成本MTM收益序列做固定30日循环移动块bootstrap，10000次、seed=20260906、取均值分布的第5百分位，必须>0；先报告日收益ACF1–30、交易数与活跃块数。这是预设依赖尺度的有限样本证据，不保证完全独立。CI门失败为证据不足，不能换块长/种子/置信度救结果。计算可用已固定运行环境，不新增依赖或服务。

技术有效但净收益/风险失败即 `SEARCH_TERMINATED_NO_FINALIST`；净正而样本或CI不足的人工结论为 `UNDERPOWERED`，仍无可晋级候选。数据缺行／HTTP失败为 `BLOCKED_DATA`，账务无法重建为技术阻塞；保持UNKNOWN/NULL。若毛收益或更便宜的核心门已决定性失败，昂贵MTM/CI可停止并明确NULL，不再做收益寻找。**最多一轮一次Search、无R2/child、无重跑/换币/改窗口/调参数/消融救援**；技术失败也不自动重试。D/H/Stress不因S候选通过而自动解封。

## 一次采集与实际承载路径

官方支持`history-candles`、`1Dutc`、9字段、`confirm=1`，SPOT的`vol`为基础币数量；文档称可取近年历史，但没有证明本LTC区间齐全。现producer日线页长固定100，即**14页行情＋1次身份，预计15次HTTP，硬上限24次实际请求/30分钟、零自动重试**（失败也计数，先计数再请求）。只允许这个instrument的身份与指定历史端点；不调用ticker、盘口、mark、funding或H。一次新源QC核对1381行UTC精确连续、边界、confirm、OHLC有限一致、基础币volume、无填补、raw→Feather一致及文件/provenance/receipt SHA。失败即停，不再预审空目录或换根重取。

本地checkout干净、detached HEAD `9a5c00ba2ad1617645b67c1d0475508ba02c401a`，是 **STALE_CODE_CONTEXT**。只读`git ls-remote`与GitHub compare核实远端main为 `7ae2b6b6c45cfb57c40a13dccd697ce1c57d08a4`，领先2 commits，PR91已包含多年spot日线资源上限1830天，S/D/H本窗口均在内。没有fetch/pull/switch或动原项目脏checkout；后续授权执行必须从该已核远端基线的独立工作树起步。Issue92当前CLOSED（2026-09-06 04:33:32Z），没有新增Issue。

固定native源 `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade`，已核commit `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`；Python使用同级父路径`venv/bin/python`。此为源码身份，不是已跑本策略的证据。

授权后在新Git外root和非敏感独立SQLite注册真实Profile/Generation/唯一Candidate；Profile设spot、1d、上述资金/费/PF/DD、history_start_date=2021-03-22、holdout_days=515、各阶段最低自然交易12。冻结协议/源码、`SINGLE_BASELINE_V1`、Profile快照与预算；获取前不预造source SHA。

路径为 `scripts/fetch_okx_profile_data.py --profile-database … --profile-id … --window-spec … --pre-roll-candles 40 --single-baseline …` → `scripts/run_bounded_research_pilot.py prepare-search-data`（绑定真实receipt/provenance、S与40根前史）→ 现有Research Console的唯一Search入口（`POST /api/search-campaigns`，调用既有screen-search）。CLI `screen-search --campaign-root … --freqtrade-python … --freqtrade-source …` 是同一路径的替代入口，**不能两个入口各启动一次**。

原生TRIAL/receipt/terminal投影至现有generation_runs JSON；Git外补充审计绑定同一ZIP/源码/协议/数据SHA。只有全部S门通过、监督审阅并单独授权，才通过现有`protocol_review`交接ResearchRun和`prepare-development-data`。D/H/Stress沿现有spot 1d continuation，同一research_run_id。六表保持research_profiles、generation_runs、candidates、research_runs、backtest_executions、releases；没有finalist则后三者不伪造。现有页面能显示流程与原生结果，额外手工门不会被页面自动计算成PASS；无Profile写页面亦不另建UI。

**预计最小准备量：2–4小时主动工作**（Git外唯一策略/注册/计数保护绑定、少量合成因果与账务检查、已有审计脚本的本协议化），采集约数分钟至30分钟，唯一native约数分钟，正结果追加审计约30–90分钟；均是估计。项目业务代码/native/Schema修改预算0。如果准备暴露不在已支持表达式内的必需能力，只报告具体缺口并停该动作，不扩scope。下一门就是监督审阅本文件后授权一次“冻结＋采集QC”，再按原授权边界决定一次Search；不需另开概念选择轮。

本阶段未采集市场值、未登记Candidate、未改代码/数据库/ledger/Issue、未运行Search或创建其他任务。文献是研究先验，只有后续完整成本、风险与时间证据才能回答是否盈利。
