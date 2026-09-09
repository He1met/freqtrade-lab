# Issue98 DOGE_CONFIRMED_SHOCK_REVERSAL_3D_V1 — 待监督按原字节冻结

2026-09-07。监督任务01a05dcc-17fd-7972-9177-9fed95e4b07a；独立执行工作树bb9d；研究根为本文件目录。本文是最终冻结请求，不伪造已获Search许可。PR99已按head 8abddba4319382f9c3e173feb9d15cd7ccb8afca保护合并，运行lab基线为远端main/merge df3dc41dba4ccba6dba84031de7e2568f7e63399。旧报告中的35预热和小采集硬预算由本文明确替代，经济规则/阈值不变。

## 1. 假说、模型与唯一实现

Binance DOGE/USDT:USDT / DOGEUSDT，USDT线性永续，isolated 1x，UTC 1d，单仓多空，OHLCV收盘因果信号、下一日open成交。已知短期回归家族的学习性改进及跨品种研究，不称新独立alpha或确认因子已证明。经济动机：冲击后等待一日价格反向确认，尝试回避持续单向信息冲击，同时保留部分价格回归空间。确认也会错过快速反弹；停止追涨/抛售并不能从OHLCV直接识别。DOT2h成本负例、LTC条件回归负例保留；XRP/DOT数据阻塞不作为经济否定。BCH旧趋势负例不通过降费/换窗重播。

研究规划/真实项目Generation模型gpt-6-astra，reasoning medium；它只实现固定源码，不接触D/H或进行参数选择。策略不是机器学习模型，无训练、AI价格预测、funding信号或跨资产输入。原生运行固定Freqtrade2026.7/commit52bc96f4480b1a0da6a9b455bd00b17fbb6786a5，Python3.13.13、ccxt4.5.68、pandas3.0.3、pyarrow25.0.0；使用issue-43-profile-driven-v1下原生源码与venv，不改native。

令r[t]=C[t]/C[t-1]-1，L[t]=前30个完整日min(Low×base_volume)，本日volume>0且L[t]>=500000 USDT。
- 原始多事件Q+: r[t-1]<=-0.04、r[t]>0、C[t]<=0.98×C[t-2]、流动性条件通过。
- 原始空事件Q-: r[t-1]>=0.04、r[t]<0、C[t]>=1.02×C[t-2]、同流动性条件通过。
- Q为任一原始事件；E[t]=Q[t]且Q[t-1:t-3]全假。抑制检查前3日原始Q，包括曾被抑制的Q，不能只看获准E。
- E[t]方向对应t+1 open入场；E.shift(3)在t+3给两方向退出信号，正常t+4 open退出，目标72h。退出必须来自获准E，不来自被抑制Q。多空互斥；依原生entry后exit populate顺序，无未来列依赖。
- stoploss=-0.08，minimal_roi={}，can_short=True，process_only_new_candles=True，startup/pre-roll=37。无trailing、加仓、复利仓位或自定义执行callback。止损可提前，force_exit单列。

唯一准入源码：DogeConfirmedShockReversal3D-v2.py / class DogeConfirmedShockReversal3D / family closed_shock_confirmation_reversal_v1；SHA256 **61488a724e54fca3dfe11a47294c3a3a02077090cb38baaef5385d16ef43d05f**。文件中的数值乘积/平方只是布尔定义的等价表达，最后以该代码的浮点比较为唯一执行字节；不在市场数据上择实现。998 AST节点通过现validator，max_lookback=37。

已完成一次小合成对照：两组180行人工序列，含原始事件连锁抑制、边界4%/2%、流动性与当前volume失败，逐行原数学定义与实际信号相同；前缀不变、方向互斥、E.shift3退出均通过。调用锁定IStrategy.ft_advise_signals（entry→exit），并只读核锁定backtesting.py先trim后全部signal shift1；未运行matching engine或native backtest。原布尔列版本被AST拒绝、数值版35根被lookback拒绝的草稿保留，不是经济尝试。root已明确同意37根纠正，理由仅依赖图，不是结果调参。合成回执synthetic-equivalence.json不等于经济证据。

## 2. 窗口、隔离和容量

所有端点UTC 00:00:00Z、左闭右开。S=[2023-11-06,2024-11-04)，364日；D=[2024-11-04,2025-11-03)，364日；H及H Stress=[2025-11-03,2026-05-25)，203日。各阶段空仓启动，预热只给价格/mark指标输入，不产生持仓或收益；评分funding严格从阶段start至stop之前。没有继承前阶段仓位。

| 范围 | 37根预热起点 | 物理日线 | 物理小时mark | 评分funding事件 |
|---|---|---:|---:|---:|
| S | 2023-09-30 | 401 | 9624 | 1092 |
| D | 2024-09-28 | 401 | 9624 | 1092 |
| 首次完整S+D来源 | 2023-09-30 | 765 | 18360 | 2184 |
| H / Stress | 2025-09-27 | 240 | 5760 | 609 |

原生capture请求总范围为[2023-09-30,2025-11-03)，其原响应可能含预热funding；既有compile_source仅发布从S评分起点起的funding，后续phase_source再按S/D评分切片。预热funding不成为策略输入/评分，不以它填缺失事件。完整来源分S-only/D-only消费者，必须同实际来源SHA/Profile/window/gate；Search进程只可见S视图。D仅producer物化/QC，不输出行情/率分布、信号、收益或策略值；H本次不请求、不物化。H将来单独同Run授权；S+D采集与H采集绝不同时执行。

S固定块边界2023-11-06/2024-02-05/2024-05-06/2024-08-05/2024-11-04；D为2024-11-04/2025-02-03/2025-05-05/2025-08-04/2025-11-03；H为2025-11-03/2025-12-22/2026-02-09/2026-03-30/2026-05-25。按入场时间归块，不重跑/重置跨块仓位，不做逐块选参。E最小间距4日使一年理论数量上界约91、H约50，末端实际更低；18/10门约需每20日自然一次，实际数UNKNOWN，不足即UNDERPOWERED，不改频率救样本。

台账原112022字节SHA84e8c49eab8b40eb39559e0468a914ae80506dbf7b60cb93402e9ecb18891271已保留；本QC追加后113454字节SHAaf0a1c3287e1162995e40636471d395016d2e1301df64f310bdabf987b1c2af0。唯一DOGE新增为FUNDING_QC_ONLY，Search_consumed=false、未作future reservation。此前未见具名DOGE消费；不完整早期记录/外部未登记接触仍UNKNOWN，不要求证明绝对全球未接触。其他币同日历已研究，不能宣称跨资产统计独立。执行前在同ledger锁下核前缀及新增具体DOGE冲突后登记本冻结cohort；冲突即停。

不使用BCH旧S、技术周或保留D/H；不以跨交易所同资产当独立。全资产未知暴露[2026-05-31,2026-07-31)在本窗口之外。DOGE选择因2020已上市、锁定原生tiers具名、无已知本币消费而非PnL排名；尚未证实历史流动性/精度档位适用性或完整行情可得性。

## 3. 资金、成本和事前门

Profile拟id issue98-doge-confirmed-reversal-v1，domain BINANCE_CRYPTO_PERP/exchange binance/futures/isolated/1d/max_open_trades1，detail_timeframe=None，E0=1000 USDT，固定stake250 USDT，tradable_balance_ratio0.99，history_start_date2023-09-30、holdout_days203、smoke_days7（仅现有Profile字段，本协议native smoke预算0）。不借用真钱/凭据或旧敏感DB，只建本根新六表lab.sqlite。

base taker_fee_rate=0.001/side：手续费假设5bp+价差/滑点代理5bp，原生入/出各扣一次，不再外部双扣；stress_fee_multiplier=2即每边0.002。不是账户费率或实测冲击函数。250/500000=0.05%只是历史粗交易额比例，不代表开盘深度。原生止损和日线open成交近似仍有限制，跳空与盘中路径未被完整建模，不宣称连续风险上界。

funding沿BINANCE_ASSOCIATED_MARK_BOUNDARY_V1，真实时间戳保留、native分钟映射，完整8h日历及正associated mark；native与associated现金流取较不利者，边界不确定付款计入/收款不计，附加扣减进入逐笔净/PF/现金和小时close MTM DD。价格毛利、native funding、fee假设/滑点代理、额外资金扣减分别对账；原ZIP/native指标不改。小时extrema压力只诊断，不能冒充H Stress；未有完整小时mark就BLOCKED_DATA。

预算算术（非观测）：72h按最多10次边界付款敏感性，若每次1bp或5bp，往返费用加funding约30bp或70bp名义仓位。18笔要使1000钱包净1%，每笔平均净需22.22bp，价格毛利需约52.22bp或92.22bp；2倍交易费加5bp资金情景约112.22bp。实际funding可能更高，不封顶，不以有利收款代替价格毛利证据；2%几何距离大于费用仅是待证伪空间。

核心Profile门：S/D min_development_trades18，H/Stress min_holdout_trades10；min_profit_factor1.10；原生及保守小时close MTM DD均<=10%；保守净收益率>=1%；全时现金可执行。economic gate用现有PROFILE_DRIVEN_ECONOMIC_GATE_V1：minimum_net_profit_after_base_fees_pct1.0、minimum_average_holding_period_minutes1440、maximum_roi_exit_count0。

额外门：S/D自然有效成交>=18、每方向>=6；H/Stress自然有效>=10、每方向>=3；每阶段至少3/4块有自然样本；删去最大正保守净交易后其余净和>0。自然=正持仓时长且自然signal/stoploss完成；force_exit/liquidation/零分钟不计自然样本但盈亏不删。若PF因无亏损无法定义则UNKNOWN，不能假装自动通过。10%DD/1%净/PF1.1和样本门是个人筛查缓冲，非统计显著性证明。单仓8%stop预期价损约钱包2%，不能保证跳空损失止于此。

任一门失败则停止该假说；数据、技术、经济负例、UNDERPOWERED分开记录。项目机械finalist如产生而额外门失败，保留原terminal事实，外层审阅REJECTED并禁止finalist交接/D，不篡改为不存在的项目终态。S成功不抵消D/H失败，阶段不合格不跑以后阶段。

## 4. 固定执行/生成预算及来源资源附件

本次下一授权请求范围：一次完整S+D来源准备和唯一Search；D仅机械QC，D策略仍需要S全门通过后的root阶段授权。整体最大：Search1、Development1、Holdout1、Stress1，各后期均需当时资格及单独许可；R2=0、children0、重播0、换币/换窗/换费救援0。SINGLE_BASELINE_V1绑定本文SHA及唯一代码SHA，maximum_attempts=1、maximum_rounds=1。无论正负均不在S做消融；整体假说的结果不证明确认增量的独立贡献。

项目Generation预算1个真实CODEX generation，要求逐字复现已绑定源码；不提议参数/工具搜索/看值改写。取值前静态或生成传输失败可报告修正，但未经root具体处置不创建第二候选或额外generation。本轮已完成小合成T0；仅在实际项目生成源码SHA核对后再做必要静态同一性检查，不重复合成批次、工程全套或native smoke。原始拒绝草稿保留，不是研究候选。源码SHA不一致即停；不批准偏离版本。

真实Profile→Generation→Candidate审阅/批准沿现有入口，批准只针对已静态/合成核验的这一源码，不伪造候选来源；当前上述记录均未创建。source/candidate/Profile/runtime实际SHA、ID在首次capture/Search前作为本文授权附件记录，未产生时不预造。唯一native Search超时采用现有SCENARIO_TIMEOUT_SECONDS=3600s，不自动重试；任何终态都保存stderr/receipt/partial artifact并通知root。

来源资源已由root在首次经济取值前裁决采用现有capture，不开发新预算接口。**撤回128fetch/32MiB/30min硬限提案**；固定实际合同为：
- 一个新根native-capture，一次capture_native→一次锁定native download-data。最多2000次CCXT fetch调用，guard在调用前检查；它不等于线缆HTTP请求数，wire attempts及内部transport重定向次数UNKNOWN。
- SIGALRM7200s。累计CCXT decoded UTF-8响应2GiB、目录5GiB是单响应落盘后的检查阈值，可超出一个响应，不是严格流式内存/下载上限。失败/阈值触发保留本次根，零自动重启；不改端点或窗口恢复。
- 只允许匿名GET fapi.binance.com/exchangeInfo、DOGEUSDT klines 1d、markPriceKlines 1h、fundingRate；请求前校验身份和UTC范围，endTime<=stop-1ms，预热起点按37根冻结，发现式since=0仅按原guard夹到允许起点。无签名、key、secret、账户或交易接口。
- 内建捕获遇错误设置stopped，后续请求被拒绝；不另加采集批次/重试/拼接。小3GET QC是先前单独诊断，保留但不伪称这次完整原始抓取；本次完整来源必须独立、透明保留新响应。estimated fetch/体积不作为更小硬阈值，实际回执决定计数。

现有发布器以同一冻结S+D contract编译，校验UTC连续日线/小时mark、完整评分funding和associated mark、base-volume语义、market/tiers、同源SHA、无插值/无last-bar丢失。原生静态tiers历史适用性仍UNKNOWN。prepare-search-data/prepare-development-data必须验证同源且物理隔离；任何失败不进入Search。根路径或来源验证不满足就BLOCKED，不关掉校验。

## 5. 交付与停止

Search真实campaign/trials/terminal和native ZIP留Git外；六表中Generation response_json保留真实Search摘要及来源绑定，外部门回执如实附加；无合法finalist不建ResearchRun/Execution/Release。Console显示真实原生/保守口径、失败/封存/UNKNOWN，不能靠UI绿色判盈利。S全门及root放行才建D Run；H/Stress必须使用同research_run_id，不先取H。Release/交易始终0，无真实账户动作。

Source错误、非法绑定/混源、缺事件/mark、超预算或技术INVALID立即停并保留证据；不重新取数或改数据合同。本次假说净/风险/样本/分散任一失败，报告失败归因并保持D/H封存；不自动新币/新窗/新参数。下一方向由root根据已冻结负例决定，不把本文或工程完成当长期盈利目标完成。

当前事实：仅3GET资金QC已执行并PASS，S OHLCV/小时mark完整性、D/H来源、历史流动性、自然样本、经济结果UNKNOWN；项目真实Profile/Generation/Candidate/Search/D/H/Stress均0，本文待root冻结。总体研究预算不超过6主动小时完成获准S阶段或明确阻塞，native/S来源各沿上述固有限额；不为凑时长增加实验。
