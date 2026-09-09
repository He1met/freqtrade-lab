# XLM_SPOT_SMA90_TREND_V1 — 唯一值前提案，待监督批准

2026-09-06；任务 01a0746e-1a6c-74b2-b7d7-e134d15ff97a；工作树 /Users/shenjianpeng/.codex/worktrees/7183/freqtrade-lab。当前与远端默认 HEAD 均 f3ada868f8ea737756b7a68227cfd1829086f600，工作树干净，Issue87已关闭。本文件不是采集授权或盈利结论；新Issue待监督确认方向。Generation应用 reasoning/tier UNKNOWN。

## 选择

| 假设 | 毛收益来源与适用状态 | 当前可执行性 |
|---|---|---|
| A：XLM现货、季度尺度均线趋势、仅做多 | 多周价格延续，持有趋势而非赚单日反弹；震荡时会连续小损，长期下跌时现金规避部分暴露。低换手使每次毛价格波动有机会覆盖固定双边成本，但大小未知 | 推荐。现有单币spot 1d、rolling、Profile和native均支持，无业务改动 |
| B：XLM 1倍永续，同一90日均线双向趋势 | 同一延续机制，在持续下跌中做空增加毛收益机会；增加资金费、空头反弹及mark核算风险 | 不判经济NO_GO。现producer仅支持严格8h完整资金费及归档2秒合同；多年样本兼容性UNKNOWN，见下文 |

只有一个策略进入Search；不是A/B均回测。XLM优先于ATOM沿用已审元数据顺序；两者当前listTime完全相同，无历史容量收益，故不换ATOM。不是TRX短期反转改币/改参；与历史趋势文献及已见BTC趋势家族有机制重合，承认采用已知机制，不宣称学术独立或全局未见。

原始研究依据：[Moskowitz、Ooi、Pedersen, Time Series Momentum](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)，传统期货/远期长期样本中的趋势证据，只支持“检验延续”动机；不证明XLM、spot、SMA90或本协议会盈利。90日为值前设计的季度尺度，非论文复制、非市场优化；200/365日会进一步减少现有独立事件，未采用。第二份资料为[OKX官方API文档](https://app.okx.com/docs-v5/en/)，用于history-candles、history-mark-price-candles、funding-rate-history与instruments生命周期合同；未查更多论文或市场排名。

## 历史容量和暴露

仅请求instruments生命周期；初始无User-Agent的2次请求HTTPError，随后有User-Agent的3次元数据请求成功，零OHLCV/mark/funding值。XLM-USDT与ATOM-USDT：listTime=1611907686000（2021-01-29 08:08:06 UTC），state=live。XLM-USDT-SWAP：listTime=1587463971000，contTdSwTime=1611916860000，state=live。元数据不保证历史连续性，也不证明实际最初上市日期；现spot producer在scripts/fetch_okx_profile_data.py:1249起要求listTime早于pre-roll，故不能无修复承诺2021年前样本。

成功响应SHA：XLM spot 2552dd3de214def5141195d1139a649f484efed3803d98027d069c48778cb72f；ATOM spot 5bbbb3f7401970dc10f15ad6716e1a1e5eeee40b0d7c79f71e0baec2d9e0d72a；XLM swap 5877d6b40f622ebdbad1aba3811be6c83cd9f4e796abd7fa255db72a5ac119e9。仅工具内身份投影，未保存完整响应。

全局ledger只读SHA 79a798f44a5427e3c339c632f3632536db5043ebed8b0bcbbc2482a1a658703e；99物理行含95/98空行，跳过后全部可解析，未改写。只输出身份白名单和键名；XLM/ATOM结构身份叶无命中。当前远端87条Issue/PR正文在进程内仅做pair/instrument匹配，无XLM/ATOM命中，未输出正文或经济指标。加上已授权四份非市场说明，这是有限覆盖证据，不能证明全球未见。#32 XRP六月绑定和#30实际receipt/SHA UNKNOWN继续保留；所有资产[2026-05-31,2026-07-31)保守排除的监督裁决继续适用。没有打开旧S/D/H市场文件，也未重做旧曝光调查。

## 唯一冻结规则和窗口（均UTC左闭右开）

- 市场：OKX XLM/USDT现货、仅做多、无借贷；1d（交易所1Dutc）。唯一信号：当日完整收盘close > 当日含当前bar的rolling(90).mean()则enter_long=1；close < SMA90则exit_long=1；等于均线两信号均0。完整窗口才可发信号，不用成交量/周几/波动/市场状态附加过滤。
- 下一个bar开盘按原生信号语义成交；不开盘前读当日收盘。持有至反向退出信号或20%价格止损；minimal_roi={}，无追踪止损，无固定到期，允许止损后新的下一bar重入。startup_candle_count=90，process_only_new_candles=True，can_short=False。
- 每阶段E0=1000 USDT、固定stake=500 USDT、单仓、无加仓/复利；资金不足以放置完整固定stake则停止并报告风险失败，不缩仓救结果。阶段从现金开始，不继承前阶段持仓，最终强平计费但不算自然完成的独立样本。
- S [2021-05-01,2023-01-01)，预热[2021-01-31,2021-05-01)，约20个月；D [2023-01-01,2024-07-01)，预热起2022-10-03，18个月；H预留[2024-07-01,2026-05-31)，预热起2024-04-02，约23个月。所有90日预热仅初始化，不计收益、不入场。D预热来自已消费S尾部，H预热来自D尾部，阶段评分不重叠。
- 这是当前生命周期下给D/H留足历史的分配，不能称“多年S已经充足”。S仍只有约20个月，可能UNDERPOWERED；若必须至少3完整年S且2年D和2年H，现metadata合同无法提供，本协议不能满足该更高要求，不能借未获许可的数据补齐。
- 首次source只生产pre-roll+S+D，D仅producer/QC物化，模型不读数值；H本轮不采集。现producer支持S/D时间范围，无扩充窗口合同；H/Stress调用路径在正式放行前须按同一ResearchRun复核，未知不伪称ready。

## 成本、基准及四类门

费用是假设预算，不冒充账户实际费率：原生每边taker_fee_rate=0.001；每个成交腿另外扣该腿成交名义额0.001作为基础滑点预算，双边约40bp；敏感性每边费用0.002、滑点0.002，双边约80bp。现原生没有独立滑点成交参数：附加成本只做同一交易路径审计扣减，清楚标注成本敏感性估算，不伪称真实滑点重放。真实H Stress另行获用户授权才执行原生费用倍数2；滑点仍是账后扣减。Funding/mark在spot为N/A，不是缺数据填0。

基准：现金收益0（只作为USDT计价算术基准，不代表USDT无风险）；同窗口500 USDT一次买入持有+500现金，首可成交开盘买入、窗口末按同一强平语义卖出，完全相同费用和滑点。基准用于收益/风险机会成本诊断，不另加“每年跑赢B&H”淘汰门，不算第二个候选Search。

1. **经济**：每个获准阶段扣基础费用和滑点后总净收益严格>0；成本敏感性净收益也>0。Profile PF=1.0仅作与净正一致的机械检查，不设PF1.5、每年盈利、持仓时长等额外门。若原生PF为NULL，保留UNKNOWN并停止资格判定。
2. **风险**：Profile原生DD≤20%，且逐日持仓盯市、计成本的峰值相对DD≤20%。前者不能替代后者；另报告日内low保守估值的风险局限。20%是个人研究风险预算，不是用户实际资金承受能力；半仓与20%价格止损意图将一次普通止损损失约束在初始资金10%附近，跳空可超出。
3. **样本及独立验证**：S和D各至少6个自然平仓；还须至少4个相距90日的非重叠交易暴露组。组从最早尚未归组的入场起覆盖连续90日，其内所有入场归同组；跨组未平仓交易仍归原组，不能拆长仓凑样本。H至少6组，D+H合计至少12组才可讨论最终合格。组不是被证明IID；最终还须H月度净盯市收益的3个连续自然月块bootstrap单侧95%均值下界>0（固定10000次、seed=7183、循环移动块、含现金月份），不能用普通trade t检验冒充独立。若仅净正但组数或置信证据不足，UNDERPOWERED，不QUALIFIED，不降门。不保证单资产约41个月D+H能达到它。
4. **集中度**：移除本阶段贡献最大的一个90日暴露组后，净收益仍>0。该门避免靠一次趋势宣称可重复；年度收益、胜率、持仓天数、基准差额均只诊断。组归属跨界收益全归原交易组，日盯市风险仍按真实日期计算。

附加审计用本次已授权阶段原生交易/行情产物，结果写既有JSON或Git外receipt；不增加业务字段/runner。如果现入口不能将必要成本/风险审计绑定到终态，在“原生门通过但监督资格待定”处停止，不把工程finalist当全部经济门通过。

## 合约最小兼容改动的判定

现状限定到本仓库合同，非“全部合约不可研究”：scripts/fetch_okx_profile_data.py:49-51固定8h和2秒；:864附近归档floor到8h；:1147 validate_funding_history要求完整8h；lab/bounded_research.py:1141消费端也要求8h。合格的其他资产归档仍可能无需改动，尚未取值验证。

最小代码提案若保留原timestamp：producer的_parse_funding_archive及validate_funding_history、consumer的_search_series_contract/实际序列校验和tests/test_search_data_producer.py、tests/test_rest_funding_completeness.py都需明确新合同。**但并非足够**：固定native exchange.py:3922按date inner-merge funding与小时mark，秒级时间戳会丢事件；:3979-3985用入出场包含端点决定资金费。直接floor可以改变边界入出场的费用归属，抬高2秒容差只是继续扩大该假设，不能当兼容修复。

若官方能证明归档秒偏差仅是记录延迟、经济结算时点为整8h，未来独立新合同可保留原timestamp审计映射至官方结算时刻，native不改；仅映射/收据/针对性测试约4–8小时，但该事实目前UNKNOWN，不能根据旧3秒事件推定，更不恢复#84。若是真实秒级结算，需选择事件时刻mark语义并修原生合并/边界计费，小时OHLCV无法提供精确秒mark；估计至少1–3工程日且仍有模型误差，不属于本轮零开发。针对测试必须覆盖8h前/整点/后几秒开平、多空符号、重复/缺失/跨月、4h切换、mark未匹配必须失败、旧2秒合同不变。故本轮选现货是可验证核算成本决定，不是宣判合约失败。

## 预算与下一门

唯一candidate，SINGLE_BASELINE_V1一seed一轮一个真实S；本批累计前两次已消费，新S上限1，不换币/改参数重放。监督审方向后本任务继续唯一Issue、冻结源码/Profile/Generation/Candidate/hash、必要纯合成时序检查最多1次；不开新任务，不重用旧服务。

提议source一轮60分钟、最多64 HTTP（包括instrument与分页，零自动重试），仅spot日线，失败停止不换根；S/D连同90日预热共1247日，现100行分页约13次加元数据，64是协议硬预算而非隐含重试。原生S最多30分钟；来源/完整性失败标BLOCKED_DATA或对应合同错误，不算经济假设失败；一旦观察经济结果即消费唯一S，技术失败也不擅自恢复。

S核心门全部通过交监督一次放行D；否则NO_FINALIST或UNDERPOWERED诚实终止，不造ResearchRun。D通过仍不打开H；用户另行授权H/Stress，同一research_run_id。H封存、Release/Demo/交易均未授权。若无足够独立样本，终止本协议的资格结论，不为“找到盈利策略”无限追加试验。

## 监督复核补充 v2：终点缺口与精确定义（覆盖上文含混表述）

### 1. H/Stress 当前确实不能接续，需先决定补齐范围

只读代码已确认，不能把“最终可从现入口同run执行H”当现有能力：

- `lab/research_console.py:875-885`：Search模式直接构造SEALED_UNREAD的H capability；`:3775-3782`在实际authorize路由之前阻断所有later phases。重启为旧模式也不能解决下面的合同冲突。
- `lab/holdout_run.py:283-290`：freeze未传profile_contract给Development freezer；`:312-313`保留strict窗口30天；`:332`要求5m。`:940-970`使用旧EXPECTED_GATE（30笔、0.5%、PF1.1、DD5%）；D的pipeline/schema字符串仍同旧版，字符串本身并非阻塞原因，缺的是normalized_profile_contract和对应gate分支。
- `:666`物化provenance写死5m；`:1206`H/Stress两行也写死5m。`:1038-1043`还要求H来源plan/source/config hash与D原来源一致，本提案首次source只采S/D，未来独立取得H无法直接满足该绑定。不能篡改D已冻结来源哈希来绕过它。
- `scripts/run_freqtrade_backtest.py:979`有Profile时只接受base taker_fee_rate。即使H接线修好，保留原Profile、H Stress费率倍数2也会被该应用wrapper拒绝；这是lab wrapper的窄场景合同补齐，不是修改Freqtrade native。
- 正面证据：`lab/bounded_research.py:623-677`的Profile validator允许PF1.0，`:3744-3779`真实Profile Search finalist使用>=Profile阈值；`lab/development_run.py:1714-1767`读取normalized Profile gate，`:1872`用该门判PF；该路径不走legacy计划的PF>1限制。本轮仅静态路径证据，未启动Search或用合成结果代替运行证据。

**最小交付提案，待监督另行授权代码范围：**继续同一任务、同一Issue范围内补齐Profile spot 1d的H continuation，保持六表、既有API/worker和同research_run_id。只调整 `lab/holdout_run.py`（freeze、eligible、物化、动态timeframe、同run结果绑定），`lab/research_console.py`（单独显式用户授权H时接入冻结Profile能力；Search默认封存和Judge/Release边界不变），`scripts/run_freqtrade_backtest.py`（仅已绑定HOLDOUT_STRESS允许snapshot的stress_fee_multiplier，其他场景仍base且拒绝任意倍率）。未来H acquisition必须作为同run的独立追加来源收据，经既有input_snapshot_json授权记录绑定；保留D原hash且不混写，不能把新的D/H来源伪装成原S/D来源。`scripts/fetch_okx_profile_data.py`若需支持只取H+90日预热，在现下载/验证函数内增加这一个显式阶段入口，不能以S/D别名隐藏H打开，也不建runner。该producer补齐是必要范围的一部分，不再假定旧producer自动支持。

预计主动工程/验证12–24小时：H continuation及Console 5–9h、H-only source和不可变追加绑定3–7h、Stress wrapper及合成/HTTP/原子性验证4–8h；原生不改、无新DB字段。不是45分钟前置预算内的实现授权，也不是4–8h资金费映射提案。超出该窄范围即交回，不扩成通用阶段平台。当前整个策略研究的终点状态为 **BLOCKED_ENGINEERING_PROFILE_H_CONTINUATION**（本提案描述标签，非冒充项目已存在状态码）；不取行情，先请监督决定是否值得补齐。

必要验证限定为 `tests/test_holdout_run.py`、`tests/test_holdout_console_http.py`、`tests/test_holdout_atomic.py`、`tests/test_run_freqtrade_backtest.py`、`tests/test_search_data_producer.py`：合成spot 1d D经真实API授权H/Stress并只追加同run的两条execution；未授权或负D、Profile/hash/窗口/倍率漂移在H读取和DB副作用前失败；旧5m gate不变；真实H值未打开时保持封存；重复授权拒绝；两份artifact全通过后原子附加；source读取边界和失败不发布。最多一次纯合成native端到端（含需要的场景，不使用市场数据），其预算须由监督在工程授权时明确，不能暗用此前“一次探针”运行多次。

### 2. 成本与现金：确切公式

令每个实际成交腿j的成交数量q_j和原生成交价p_j来自原始订单/交易receipt，名义额N_j=q_j*p_j，入出腿分别计算，不假定退出名义额也等于500。无加仓/部分成交的假设须以receipt验证；若原生舍入导致数量有微小差别，用实际数量并记录差额。

- `P_native`是原生fee=.001的净PnL，已经包含一次完整的native手续费，绝不再重复扣基础fee。
- `P_base = P_native - sum(N_j*.001)`。
- `P_sensitivity = P_native - sum(N_j*(.001+.002))`：额外fee .001、滑点 .002，连原生fee后总成本每腿.004。
- 真正H Stress使用其自身fee=.002的原生成交路径：`P_stress_adjusted = P_native_stress - sum(N_j_stress*.002)`；若成交路径因钱包约束不同，不把base路径估算写成其结果。base/sensitivity是固定路径估算，H Stress是另获授权的实际费用执行。

对应现金审计从C=1000开始，base在入场扣`N*(1+.002)`，退出加`N*(1-.002)`；sensitivity分别为`1+.004`、`1-.004`。持仓按实际数量计价；费用/滑点在成交时间扣除，现金和资产分开追踪。审计现金应与原生现金减累计附加成本一致，否则核算UNKNOWN并停止资格判定。

每次入场前必须同时满足现native的`0.99*C >= 500`和该成本情景的`C >= N*(1+总每腿成本率)`；amend_last_stake_amount必须维持false，禁止缩水成交。若同路径现金不够，不能仍报告该路径可执行盈利，标固定仓位路径不可行。仅静态定义和精确十进制算术已核验：首仓名义500后base现金499、sensitivity现金498；平价平仓后分别998/996；20%价格止损（卖出名义400）后898.2/896.4，下一次0.99可用额889.218/887.436，均容纳固定500。不是经济smoke，也未证明未知实际交易序列始终有现金；正式执行仍逐笔核验最小订单/精度和余额。

B&H的500明确定义为**名义本金**，不是含费用滑点的总预算；因此E0=1000下买入后现金base=499、sensitivity=498，同策略成本公式。按原生市场精度向下取整数量，剩余零钱留现金；不可通过多买或忽略买入成本凑到500。末端退出收同率成本。上文“500现金”指成本前配置，成本后按本节。

### 3. 分组、force_exit和bootstrap：确切算法

不增加阈值；S/D自然完成交易>=6、阶段组数S/D>=4、H>=6、D+H联合>=12及原bootstrap/集中度门均保留。以下定义消除“交易组即IID”的误读。

**交易与组：**每阶段自然完成交易指exit_reason不是force_exit且exit_time严格早于阶段exclusive end的已完成交易，包含正常信号退出和stoploss；原生窗口最终force_exit不计自然完成数，但全部利润、费用、滑点、风险必须纳入阶段总账。交易按(entry_time, exit_time, 原生trade_id)排序。最早未归组交易的entry_time为组起点a；初始组右端a+90日，所有entry<右端的交易纳入，右端扩展至这些交易的最晚exit_time（若更晚），重复直到不再扩展。entry恰等右端属于下一组。这样同一长持仓不会跨两组贡献两个独立样本，90日只是最短观察间隔而非IID证明。

完整组只有当组右端<=阶段end且含至少一个自然完成交易才计入样本数；尾部不足90日的组、纯force_exit组都不计数。它们依旧存在于收益分解，不能扔掉正/负尾部改善结论。force_exit交易按其真实entry归原组，永不凭退出时间新建样本；所有腿成本随该交易归组。

**D/H边界：**阶段单独组数用于各自门；联合12组必须把D、H全体交易按时间重新执行上述算法，不能把两个计数相加。跨边界距离不足90日或持仓暴露使组区间相连时归一个联合组；D末端force_exit与H起点重新入场仍按同一时间规则归组，不能因为现金重置制造两个独立样本。联合组只数含自然完成交易且完整观察的组；未获H授权前联合数为UNKNOWN，不查看H来估计。

**集中度：**对阶段内所有组（包括不计样本的尾组、pure force_exit组）按该成本情景计算组净PnL；取净贡献最大组，平局取最早组，检验`该阶段总净PnL - 该组全部净PnL > 0`。base与sensitivity各按自身组PnL处理。不能保留被移除组的force_exit利润，也不能删掉其他尾部损失。这只是对既有路径的利润集中度诊断，不重放“删去后现金/信号”的另一策略。

**H bootstrap：**H实际评分仍完整覆盖[2024-07-01,2026-05-31)，但bootstrap只使用完全落在H的自然月，即2024-07至2026-04共22个月；2026-05截至31日00:00缺最后一天，该部分收益不进入bootstrap，仍计总净、DD、集中度。月度净收益r_m=(月末边界盯市权益-月初边界盯市权益)/1000，固定E0分母、无复利。权益采用边界之前最后可用日线收盘盯市，月初边界成交及成本归新月；在窗口初始以1000作前一边界权益，不从预热虚构持仓。必须对齐真实交易时间重建现金+数量权益。

对base成本后的22维月收益向量作循环移动块：块长3个自然月，起点0..21共22个，各次均匀有放回抽取8个起点（ceil(22/3)），每块按原顺序取3项、超尾取模，连接24项后仅取前22项，计算算术均值。numpy.random.Generator(PCG64(7183))，顺序产生10000组8起点，不重设seed；固定NumPy版本随审计receipt记录。10000均值的5%分位数用`numpy.quantile(..., .05, method='linear')`（Hyndman-Fan type7），下界严格>0才过原门。缺失月份/不够22完整月不填0，标UNKNOWN/数据不完整。真实现金月份的0必须从账本验证。小样本bootstrap仍有模型不确定性，不能称统计上已证明稳定盈利；不得结果后换块长、收益分母或分位法。
