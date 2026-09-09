# XRP_WEEKLY_PERSISTENT_DIRECTION_V1 最终事前设计

本批为 Issue 107 的新普通 SINGLE_BASELINE_V1 / INDEPENDENT_VALIDATION_REQUIRED，有条件的目标资产历史外样本验证。它是已知动量家族改进，具有跨资产学习；不是旧 EXPLORATORY 结果转正，不宣称全球市场未见或统计独立。所有下列定义、阈值、实现源码及预算在完整新行情/信号/经济结果之前冻结。缺失证据为 UNKNOWN，不转零或自动视作通过。

## 唯一规则与原生时序

Binance XRP/USDT:USDT，UTC 1d，14 根日线 warmup。周日 candle 完整收盘后 m=close/close.shift(7)-1：m>0 目标 long，m<0 目标 short，严格 m=0 目标 cash；不设幅度阈值或 epsilon。信号由冻结主源码计算。周一原生开盘执行：相同方向继续持有，反向先平旧仓并结算费用/资金再开新方向；cash 只平仓。周内只允许原生 8% 保护止损，止损后等下个周一重新判断，不周中重入。没有 ROI、trailing、自适应参数、加仓、复利或第二标的。

wallet=1000 USDT，fixed stake=250 USDT，isolated 1x，max_open_trades=1。实际成交数量受原生精度取整；不能改 stake 以追求过门。原生不允许首评分 candle 或最后 candle 新入场；主策略首个可执行周决策为各阶段第二个周一（S 2023-11-13、D 2024-11-11、H/Stress 2025-11-10）。之前的 candle 只形成因果信号，不假定第一周一从 warmup 带仓。S/D 各最多51个可执行周决策，H/Stress各最多28个；这是日历上界，不是独立样本或实际交易次数。

基准只在首评分 candle 发一次 long 信号，原生移位后第二个评分 candle 开盘入场：S 2023-11-07、D 2024-11-05、H/Stress 2025-11-04。同 wallet/stake/1x/单仓，数量不重平衡。stoploss=-1.0 对应零止损价，不使用主策略8%止损；ROI空、无自主退出/重入，保留原生 liquidation。基准是同成本诊断，不是可晋级 Candidate，也不能在它更好时切换研究策略。

统一接受 Freqtrade 2026.7 最后 candle 模型：先执行该 candle 常规 exit/stop，余仓再按该 candle open force_exit；不是排他终点收盘价，也不是保证先于末K止损的无条件开盘退出。原生最后K分别 S 2024-11-03、D 2025-11-02、H/Stress 2026-05-24。所有末端强平成交、费用和资金保留在阶段最终块；剩余时间视现金，无虚构利息。禁止末K新仓。此为回测假设，不是可保证的实盘成交。

## 时间窗口与数据权限

所有窗口左闭右开 UTC：S [2023-11-06,2024-11-04)，D [2024-11-04,2025-11-03)，H 与 Stress [2025-11-03,2026-05-25)。S/D 各364日52周，H203日29周。每个阶段从现金开始，不跨阶段带仓；14根紧邻历史只供预热，不计阶段收益。

初次采集仅 [2023-10-23,2025-11-03) 的 S+D+S warmup，D只允许机械日期/完整性/有限值/哈希QC和物理隔离，不读取D目标方向、指标、容量、PNL或挑选D子窗口。H及其独立数据源此时不采集；将来必须在D所有门通过、root单独授权后用既有H-only源入口。H warmup计划自2025-10-20，仅到其阶段授权时处理，不能据已有D源提前读取H信号。

已批准的五个代表日资金 metadata GET 已发生，合计1841 decoded bytes；只验证日历/正associated mark，没有完整OHLCV、信号、收益或全源就绪证明。此前原生主策略两组共2次与基准1次均为人工2030数据，合计synthetic3次，不是市场结果，不重跑以扩大本批证据。

## 费用与核算

S/D/H 每边fee=0.001，为5bp手续费假设+5bp滑点/价差代理；Stress每边0.002。它不是观察到的账户费率；不再额外重复扣同一滑点。原生费用双边支付。资金沿 BINANCE_ASSOCIATED_MARK_BOUNDARY_V1：保留原事件时间，按现有分钟桶映射8h日历及associated settlement mark，边界收款不提前抵扣、付款保守包含。缺失associated mark/事件、错时区、未知/无法对账流量不填补，不放宽timestamp合同。

逐笔纯价格毛利=sum(direction*(close-open)*actual_amount)；另外分别展示entry/exit fees、native funding、保守扣减、native net与conservative net。原始ZIP不改写。通过既有audit_native_trades从实际成交、冻结mark/资金事件复核，所有数可追溯到原始收据。净百分比用起始钱包1000作分母。正常DD采用已确认完整小时mark close、实际成交和费用事件的running-peak回撤；小时high/low顺序压力仅补充报告，不替换正常DD或冒充原生Stress场景。

## 自然episode、样本和稳定性定义

自然方向episode由实际可执行周目标序列划分：一个连续的相同非零目标方向区间为一组；下个周目标反向或cash时完成。区间内止损与同向下周再入的所有实际trade归同组，现金间隙不拆样本。没有实际成交的方向区间不算自然episode。必须在当前评分窗口内开始，并在末端force_exit之外的有效周决策处结束，才算自然完成样本。最后被评分边界截断的方向区间即使止损后暂时现金也标CENSORED，不算自然完成次数；其全部经济结果仍计入总净、PF、DD和最终块。

分别报告每笔native trade持有分钟、每个完成episode的成员trade持仓分钟之和及episode日历跨度。自然episode平均持有以各完成episode的累计实际有仓分钟的算术平均计算，不含中间空仓等待；native平均则为全部原生trade时长的算术平均，包含止损与边界强平。两个平均都需>=4320分钟，不能用较长组跨度掩盖短trade。

敞口周以从阶段起点分出的固定UTC七日块计数；某周实际仓位持有区间与该周有正长度交集才算1，零时长交易不贡献。相邻有仓周不是独立样本。每方向完成次数使用目标long/short，不按净盈亏符号。

固定时间块：S与D各四个连续13周块（各91日）；H/Stress前14周98日、后15周105日。MTM块收益用相邻边界可清算equity快照之差，不按入场日/退出日把整笔长期收益归入一个块，不在边界重置持仓。边界快照使用前一完整小时收盘mark，持仓扣预估退出fee并保留已付entryfee；仅计timestamp严格小于边界的成交/资金，恰在边界的事件归右侧块，不能重复扣款。期初equity=1000，排他终点equity=保守最终钱包（余仓已按原生末K关闭），所有块必须精确加总到阶段保守净值，计算误差容差1e-6 USDT；不成立则核算门失败。只读分析器使用相同资金保守归属规则，不生成新成交/价格或回测路径。

最大正块份额=max(positive block net)/sum(positive block net)，只以正块总额作分母。正块要求严格>0。去最大episode门：按保守净收益选净盈利最大的自然完成episode（并列按最早实际入场），从含所有censored和完整episode的阶段保守净额扣除它后仍须>0；没有完整盈利episode则该门失败，不用删除一个亏损组制造通过。所有完成/censored组及其净值、最长连续方向期、每块敞口均报告。禁止重采样生成新native证据；本批不实现bootstrap，也不把它作为继续理由。

## 所有强制门

| 门 | S | D | H | Stress |
|---|---|---|---|---|
| 保守净钱包收益 | >=1.0% | >=1.0% | >=0.5% | >0 |
| 纯价格毛利 | >0 USDT | >0 | >0 | >0 |
| 原生PF和保守trade PF | 各>=1.10 | 各>=1.10 | 各>=1.10 | 各>=1.10 |
| 原生DD和正常保守小时MTM DD | 各<=10% | 各<=10% | 各<=10% | 各<=10% |
| 完整自然episode数 | >=12 | >=12 | >=8 | >=8 |
| 完整long/short episode数 | 各>=4 | 各>=4 | 各>=3 | 各>=3 |
| native平均和自然episode平均有仓分钟 | 各>=4320 | 各>=4320 | 各>=4320 | 各>=4320 |
| 有敞口周数 | >=26/52 | >=26/52 | >=14/29 | >=14/29 |
| 固定MTM块 | 四块>=3正、最大正份额<=60% | 同S | 两块均正 | 两块均正 |
| 去最大完整盈利episode后保守净 | >0 | >0 | >0 | >0 |
| 同成本基准比较 | 主net/max(MTM_DD,1%)>=基准同式 | 同S | 同S | 同S |

每阶段还须：ROI exits=0、最低保守free cash>=0、无资金不足/借款补洞、主/基准无liquidation、完整来源/费用/因果/隔离/哈希合同成立。undefined PF、空集均值、缺基准等保持UNKNOWN，不能算通过；Profile trade数12/8只是必要条件，不可代替自然样本。完整episode PF另行披露，不替换上述trade PF。若既有核心门更严格，必须同时满足；手工外层PASS不能覆盖core拒绝。

## 最多八次市场调用与阶段停止

1 S primary；2 S benchmark；3 D primary；4 D benchmark；5 H primary；6 H benchmark；7 Stress primary；8 Stress benchmark。每一项最多一次、无结果重试，每个阶段开始前root单独放行。主策略core/完整外层已失败时可不花该阶段基准预算；任何未满足、BLOCKED或失败后后续阶段全部停。失败/超时的实际调用亦消耗对应slot，已运行基准不免费重算；零交易不是重试理由。

本协议不是调用授权。当前所有八项均NOT_AUTHORIZED_NOT_RUN。初次采集/机械QC/隔离/仅S信号容量需要另一次root明确授权；Profile/Generation审批也是独立已审步骤。若原入口另外要求市场smoke/lookahead，先报告预算冲突，不把它藏在工程验证里。不得换币、方向、周期、fee、阈值、窗口或源码救结果，也不建另一Candidate让基准晋级。

## 来源派生、保存与真实项目

使用新独立sanitized研究DB：/Users/shenjianpeng/.codex/runs/freqtrade-lab/xrp-weekly-persistence-d699-20260907/lab.sqlite。只有一个全新普通主Candidate、一次single-baseline Search；后期主结果始终同一个research_run_id。Generation必须走真实项目入口并保留来源/审阅证据，输出源码必须精确匹配本协议主SHA；不伪造模型执行、复制旧Candidate去除探索标记或补写旧结果。源码不一致先停止，不更改协议去迎合输出。

双方使用同阶段data SHA和相同raw acquisition父，但分别创建独立config/策略及派生retained provenance。只改副本中的策略路径/bytes/SHA与config收据，原source/原主收据不覆写。基准不创建Generation/Run/Execution；使用既有原生低层入口、同一sanitizer及本批比较附件，S显式绑定Search terminal/raw位置与独立artifact-root/S的解析派生；D/H/Stress仅用真实已完成主Execution路径。解析派生不是新的研究次数。每阶段原ZIP、derived audit、次数receipt和账本暴露都保留。

所有新文件留Git外；六业务表不增表/字段/索引/服务。Issue107保持打开，工程合并不等于数据就绪或研究合格。S结果仍属于选拔；即使D/H历史全过，最终“真正合格”仍需评估共同因子学习与证据强度，不能承诺盈利或实盘可交易。

## 跨资产学习与保护边界（完整披露）

首次XRP metadata前的原台账SHA为8b6fb2c4141411da5f3d114ecb68800e27f868c9a0d2a3d0e2fe462da1cee2da，133物理行；只追加metadata后的SHA为1b6b3c2cb2156ebaa8aae2f5907d2cce8efa23f58cdb7f367429475b1cc59fbd。未见目标XRP同评分窗直接信号/经济记录不证明独立；未登记外部暴露UNKNOWN。原台账缺币名记录不视为未暴露。

已知：BTC/ETH 2020–2024多轮趋势/波动/日历学习及2025保护；BTC/ETH 2026-01及04–07多个信号及后期保护；AVAX 2026-07/08；LINK 2024资金/冲击；SOL 2024/2025通道及之后保护；NEAR/DOT 2026短周期；DOT/ETC/TRX 2024 S及2025 D QC/保护；XLM/ATOM/LTC多年S及随后D/H；BCH2023/2024 S及之后D/H；DOGE/ADA/BNB2023-11至2024-11 S已消费，DOGE D也执行，其余D QC/H保护。旧BNB完整协议REJECTED不重解释，旧技术作废与经济负结果不混淆。不新增查看这些旧D/H值。

本批排除全资产UNKNOWN[2026-05-31,2026-07-31)，不借用XRP旧[2022-01-03,2022-07-01) S和2022 D，也不借用未来XRP H[2026-10-01,2027-04-01)及startup 2026-09-29。采用本历史窗不意味着重新分配任何旧保护窗。完整旧设计、采用记录、人工证明与五日metadata原件继续保存在weekly-persistence-design-d699-20260907，均通过package收据引用其原SHA，不重写。
