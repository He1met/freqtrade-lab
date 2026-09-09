# L：短时价格冲击反转，有限研究终态

**NO_GO_FOR_NEW_SEARCH_V1；NOT_EXECUTED，原生 Search 0/2。** 本轮审查的单币5m反转方案能通过现有入口的静态契约，但没有足够理由把它升级为值得消费新窗口的研究。关键是经济机制的代理不等价，不是缺少512回看或定时退出能力。下面冻结的是**被评审、暂不推荐执行的 PROPOSED 方案**，不是已完成 Generation、待批准 Candidate 或已预留 cohort。结论仅限这一个机制的无条件/低活动两个版本；不宣称所有反转无效，也不以F或K的结果替它作判决。

本工作树 `/Users/shenjianpeng/.codex/worktrees/84ec/freqtrade-lab` 干净、detached HEAD；两次只读 `git ls-remote` 与 HEAD 均为 `0ace04b7c10ea35fb8ce6f25e043ac78be87c19e`。已读 AGENTS、audit技能及两篇引用、最新 #74/#76/#66/#62正文；本任务非工程Issue，无新Issue/PR。native只读源码干净、commit `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`、2026.7。K仅接触其公开窗口/协议元信息，没有读取其行情、信号或结果。

## 被评审的精确定义

LINK/USDT:USDT、OKX linear perpetual、5m、双向1x、单仓；wallet 2000、stake 400 USDT。以下 t 为已闭合bar，信号在 t+1 open 最早成交；不会在仍未闭合的当前bar使用成交量。

- `r[t]=close[t]/open[t-11]-1`：完整一小时价格变化；`m[t]=mean(close[t-72:t])`：不含t的前72根均价；`v[t]=mean(volume[t-72:t])`：不含t的前72根均量。72根=6小时；不是72天，也不是论文30日量状态。startup/pre-roll均73根。
- **R1**：`r`首次向下穿越−2%，且 `close < .985*m` 时做多；首次向上穿越+2%，且 `close > 1.015*m` 时做空。两边要求过去73根low均>0、当前volume>0。这里只是跨阈值事件，持续越界不重复发入场信号；绕回阈值再次穿越仍可能产生新事件。已有单仓时按原生规则忽略新入场，不做加仓或自定义翻仓。
- **R2唯一增量**：向两个原有入场mask各追加 `volume[t] < .5*v[t]`。其他指标、退出、stop、ROI、时间与配置完全相同。R1也声明prior_volume_mean，避免隐含第二项代码改变。
- 做多在close回到当前m以上、做空在close回到当前m以下时发退出，t+1 open执行；m是移动均价，**不是入场时固定的目标价**，故均价追上价格也可能退出，不能将目标距离当已赚收益。固定stoploss −3%；`minimal_roi={"360":-1}`，没有0分钟ROI项。先发生的信号/止损可更早退出，剩余正常仓位到持有360分钟的bar按原生open退出；窗口末强制平仓照常计费。

双源码：`ShockReversalR1.py` SHA `387dcedf63752efbdb69e9a76cd5d6582dcb1c921f0def0609c34c56b3b649f9`；`ShockReversalR2.py` SHA `d936a29564c96e0bc22e25f00510b342ebd48e8ffb7d1b1b31e3e5de6e67c6ec`。这些2%/1.5%/6h/3%是本次用于可执行性审查的值前判断，不来自论文最优值、市场频率或收益调参；未证明其优越性。只保留这两份，不提出参数网格。

## 文献正文与为什么不推荐运行

经济设想是：非信息驱动的暂时订单压力造成价格偏离，承接库存风险后赚取价格恢复。**低交易活动可以意味着更差的成交条件，不能当作低成本；OHLC成交假设不能证明400 USDT实际可成交。** 本轮只比较无条件冲击反转及其低活动条件版本，没有研究趋势或funding过滤。

1. [Caporale、Plastun，November 2018作者稿](https://bura.brunel.ac.uk/bitstream/2438/17194/3/FullText.pdf)，PDF pp.4–11及附录报告p.21：2013–2017四币聚合价格；按日高低幅度相对均值/标准差找异常。次日open逆向、当日末退出，BTC 2015/16/17各段反向交易均负。30日/1σ经样本规模与2017收益图选定，无干净后置时间留出。文本称计spread，示例为“Current”，精确历史费率不明确，更无永续funding。更大次日反向振幅不等于能在收盘前赚取该振幅；这是直接负面警示，不淡化。
2. [Bianchi、Babiak、Dickerson，Riksbank WP413，May 2022](https://www.riksbank.se/globalassets/media/rapporter/working-papers/2022/no.-413-trading-volume-and-liquidity-provision-in-cryptocurreny-markets.pdf)，PDF pp.7–12、15–16、20–23、38：2017-03-01至2022-03-01，聚合现货USD日数据、动态流动性前100币；按前日收益与同日去趋势量做3×3横截面排序。量是相对自身30日均量取log再标准化，附录60日稳健性；不是单币最后5m半均量。此版本long/short固定成本为30/40bps，不能套用另一版20/30；等权有正证据，市值加权费后不显著。正文的样本外指跨市场检验理论，附录另以t月流动性选t+1月币池避免前视；两者都不是本提案冻结后的独立时间检验，没有OKX永续净收益证明。
3. [Caporale、Plastun，CESifo WP7917，October 2019](https://www.ifo.de/DocDL/cesifo1_wp7917.pdf)，PDF pp.5–12：日冲击/小时走势多数延续，BTC上涨后、ETH下跌后有反转例外；BTC反转毛结果不显著，ETH负冲击反转毛结果显著，故不能声称所有单币反转负。方向、时点由样本形态选择，k也按样本量选择；CAR使用全样本均值，未提供独立时间留出，正文明确未计spread/fees/swaps。摘要/结论称2017起，方法段称2015起，不能无声合并样本。该文不支持LINK双向5m/6h费后优势。

**本次推断与否决范围。** 跨截面排序收益可以包含跨币相对表现、规模与流动性暴露，不能直接搬成单币绝对跌涨预测。把日尺度压缩到5m还改变了风险承担期。更具体地，R2观察最后一根量，R1却定义整小时冲击；合成两例：基准小时量1200，冲击小时量22020、末bar20→R2接受；冲击小时量200、末bar90→R2拒绝。它们证明该filter不等价于同一期冲击低活动，不证明最后bar条件绝无预测力。对于这个不同条件，三篇正文没有补上机制或费用后的证据；故**不以现成factor倒推理论，也不消耗新窗口试试看**。新证据若能针对同币、同一信号期/活动期、可实现价格恢复支持此条件，可推翻本次推荐；不能靠换币、减费、降门或再看未封存收益推翻。

## 入口证据与真正缺口

`lab/bounded_strategy.py:22–68,193–275,344–425` 支持5m/1d、三populate、rolling/正shift、512回看及负ROI字典。`lab/search_campaign.py:1506–1512`已有精确 `entry_low_activity_filter_72_v1`，严格双入场conjunct/full-AST一致。53项小型合成检查通过，含双源AST/max_lookback73、dispatcher正负、未来shift/startup不足拒绝、6个prefix与未来尾部扰动、镜像冲击/零量/无重复level信号，以及上面两个定义反例。`synthetic-checks.json` 是技术收据，没有真实PnL或数据ready含义。

原生 `strategy/interface.py:1698–1726`在时限前没有可用ROI门，时限后取−1；`optimize/backtesting.py:667–671`对bar整倍数的−1明确取该bar open。直接无市场的函数probe在359min不触发，360min对−2%/+5%输入都触发，多空都返回给定open；零Backtesting实例/循环。还需真实执行配置维持 `ignore_roi_if_entry_signal=False`（resolver默认），并核没有字段覆盖。到时净亏损≤−100%、数据缺bar或无法成交不是无条件保证；本1x/stop3%假设下按原生处理，异常应失败。L无需继承K的ROIexit0。

**S/D没有新代码缺口。** 纯Profile/window契约已验，Search→same-Profile Dev既有source/SHA/finalist绑定保持；真实Generation/批准/来源QC都未发生。若改为“整个小时量相对更早窗口”的新fixed filter，AST可表达，但正式R2 dispatcher没有该分支；那只是最小模板缺口，仍不能补齐本轮科学桥梁，**不建议为它立工程**。H仍有现成后段限制：`holdout_run.py:281`未向Dev preflight传Profile，`development_run.py:511–516`回落60日，`holdout_run.py:307–314`保留30日H。本文92日D/90日H不能宣称全链直接运行；只在真正finalist/Dev证据后再议最小接线。

监督要求列明的**后续未选择假说**仅为：同一小时 `volume.rolling(12).mean() < .5 * volume.shift(12).rolling(72).mean()`；左端量与一小时r严格同区间，右端来自其之前6小时。两版本若事先共同startup84即可受限AST表达，纯静态实测max_lookback84；现有低活动factor和未注册新slug均拒绝它。最小能力差异只是为这一个固定双conjunct注册dispatcher并校验whole-AST/来源绑定，不需要聚合服务或1h新runner。其收益理由仍只是把检验对象对齐，不能证明有毛优势。本轮未写该候选源码、未计算它的信号或结果，**没有替换上面被否决的R2，不建议未经新证据就开工程/Search**。

## 唯一候选窗口路径：未预留、未取值，全部UTC右端不含

| 阶段 | 评分候选窗口 | OHLC 73根pre-roll起点；mark再向下整点 | 接触资格与尚缺证据 |
|---|---|---|---|
| S | LINK [2024-08-01,2024-10-31)，91日 | Jul31 17:55；17:00 | E审计列为B级，旧LINK探索评分/包络截至Jul31 00/16Z；所查记录未识别该S已用于择模，但未登记接触UNKNOWN。三个月funding目录为既有L2记录，非本轮实物QC。 |
| 独立D候选 | LINK [2024-10-31,2025-01-31)，92日 | Oct30 17:55；17:00 | 对本S时间不交叉；所读有限ledger/Issue未识别该LINK评分被消费，完整接触核对UNKNOWN，目录/实物UNKNOWN。只能成为有条件同币时间外样本，不能称已获独立资格。 |
| 封存H/Stress候选 | LINK [2025-01-31,2025-05-01)，90日 | Jan30 17:55；17:00 | 本任务完全未看值；既有适用保护/外部接触UNKNOWN。仅是未来若接受方案须先冻结的窗口元信息，本报告不写共享ledger、不占用它。需要单独授权和同一ResearchRun。 |

LINK #66 January诊断与May2024保留不触碰。旧BTC/ETH2025、BTC Sep2024、ETH Oct2024、SOL Jan2024与K全部S/D/H、ADA Apr2026、XRP #62仍按原资产合同保护；换成LINK不创造市场日历盲测。同期BTC/ETH既有知识影响保留，不假称跨币验证独立。旧LINK Feb–Jul探索不能洗成新Search；如仅在旧池继续，现EXPLORATORY标签也不能被改写后直接进Dev。

如果方案曾获重新预审，取数只能先核接触史再单次限定producer：S+D OHLC/mark截至Jan31 00Z；funding Aug2024–Jan2025整包预期raw [Jul31 16Z,Jan31 16Z)，D截止后16h属于H时间，须记录opaque取得事实，timestamp-first排除，不解读费率。H另取Jan–May包预计[Dec31 16Z,May31 16Z)，额外尾部不能藏匿或再称未见；实际包络尚UNKNOWN。严格8h网格与0..2000ms原规则，缺包/漂移/越界即停，不补零/猜as-of。预期S的OHLC/mark/funding行数26281/2191/273；D26569/2215/276；H25993/2167/270，全是日期算术，实物实际行数NULL。

## 值前成本与最多两次预算（被否决方案的固定判据，不是执行授权）

设 `G=Σ direction*amount*(exit-entry)` 为纯价格毛额；`F`为原生signed funding净收入（正=收，负=付）；`A=Σ amount*(entry+exit)` 为实际双腿成交额。基础净额 `G+F−.0005*A`；额外每腿2bps后 `G+F−.0007*A`。实际fee/notional必须逐笔核，funding缺失为UNKNOWN不可默认为0。Lab的 `gross_profit_before_fees_pct=net+fee` **仍含funding**，不能拿它代替G。

近似每笔双腿各400：打平价差 `14−平均F_bps`，每笔0.56 USDT；若平均付2bps funding则需16bps。48笔还要求全窗净≥25时，平均价格毛额需 `14+625/48−平均F_bps=27.0208−平均F_bps`。即使观测前的2%冲击有200bps，收回15%约30bps仅是假设，扣14bps后留下16bps，绝非预期收益。Stress基础fee翻倍到每腿10bps，再加2bps，即24bps往返；48笔达净25需37.0208bps减funding。多空收付按真实settlement和notional，6h也可能跨funding时点。2bps是假设，不是已证spread/impact。

- S/D/H各至少48笔完整持仓，分布于≥24个UTC入场日和≥8个ISO周；平均持仓≥5min，除窗口末强制退出外时长≤360min。一天内相关冲击不按多个独立样本宣传；48只是90日量级的最低覆盖（约每两天一笔），不是统计功效或胜率承诺。达不到只记不足/失败，不延窗或降门。
- 各阶段基础净额及额外成本后净额均≥25 USDT，纯价格 `G/Σentry_notional ≥30bps`，基础PF≥1.10、账户MDD≤10%。完整持仓、费用和funding字段不可NULL；方向/周度/持仓尾部只诊断不救援。H/Stress另须两个成本情景都通过，同Run且一次授权；不叠加S/D数据评分。
- 最多R1、R2各一次原生Search；技术有效R1后无论正负都只做固定R2，任何真实smoke占其中一次。R2须自过门，且相对R1基础净、额外成本净和纯价格G/entry notional三项都严格改善；省费不满足最后一项。预定唯一后续候选是R2，R2失败不回退R1救援。原生finalist投影即使挑出其他合格项，也只能记录技术终态、不得绕过附加门进入Dev。
- 数据/因果/来源/合同失败即停；经济或样本失败终止本版本。只有唯一合法且通过附加门的R2才可能经监督预审获一次独立D；D失败即终止，H继续封存，无第三Search、重跑、变门、换币、延窗或假造pending。

**可接续的一步：监督接收本轮有限NO_GO，停止L并保留0/2未执行记录；不要按本文启动取数、Generation或两轮Search，也不新增修补Issue。** 本任务已完成机制审查，当前不是技术BLOCKED等待工程。任何重新考虑须给出能改变上述代理/转移判断的新证据并另行预审；不能将三篇文献的有限结论扩大为“没有策略”。全程仅写本Git外0700私有目录，未改业务代码/schema/runner/producer、原工作树、DB、共享ledger、网络/模型设置或GitHub状态，未做回测、Candidate批准、D/H或第三条线。
