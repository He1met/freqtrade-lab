# Issue 96 首次评分前协议提案 v1 — 尚未冻结

监督任务 01a05dcc-17fd-7972-9177-9fed95e4b07a。工作树 60d5，branch codex/binance-bch-bounded-research-v1，已独立 fetch/switch 到远端 main fa1d19e8b56ed7cc5a9bf78d24b6d1be6114f9ac，干净。Issue 94 CLOSED / PR95 MERGED 已远端读回；Issue96 OPEN。准备阶段没有策略执行、数据采集或新数据库；没有读取技术 smoke 经济指标。台账检查时筛除指标字段，但旧 ETC/TRX 几个非标准命名的净额字段曾出现在输出，属于不同资产旧终态，不用于本机制或门槛选择；BCH 技术经济值未读。

## 机制与事前参数

唯一种子 family `prior_close_channel_trend_v1`，建议 class `BchPriorCloseTrend28`。既有趋势家族适配，不声称新独立机制，也不是旧 SOL 试验的独立复现证据。

在完整 UTC 日线 t 收盘：U28=max(close[t-28:t-1])，L28=min(close[t-28:t-1])；U14/L14 同理。close[t]>U28 且 volume[t]>0 发出 long；close[t]<L28 且 volume[t]>0 发出 short。long 在 close[t]<L14 时退出；short 在 close[t]>U14 时退出。所有指标表达式为 close.rolling(28 或14).max/min().shift(1)，严格不含当前 bar 的区间；不使用 future、funding 信号、跨资产、波动率缩放或额外过滤。信号于 t+1 开盘按锁定原生语义成交，冲突/反转顺序遵循原生，不自行模拟同价翻仓。

唯一参数集合 {(28,14, stoploss=-0.08)}。can_short=True，timeframe=1d，startup_candle_count=29，process_only_new_candles=True，minimal_roi={} 禁用 ROI；只用三 populate 方法和现有安全 AST 形状。无定时强制周交易、trailing、自定义执行 callback 或加仓。自然退出/止损可短于14日，也可持有远长于28日，窗口末原生 force_exit 单列，不当自然样本。

依据：Moskowitz/Ooi/Pedersen (2012) 的自有价格趋势机制 https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum 。论文是多市场较长周期证据，不证明 BCH 或28/14有效；28/14 是事前固定4周/2周简化假设。执行和双边 fee 参考 https://docs.freqtrade.io/en/stable/backtesting/ ，以本地锁定源码为最终执行依据。

## 窗口、台账、容量

全部 UTC 左闭右开。S=[2023-11-13,2024-07-15)，245日/35周；price/mark pre-roll=[2023-10-15,2023-11-13)，29日。S 持仓必须从空仓开始，预热期仅指标，不评分、不继承仓位；已暴露 technical week [2023-11-06,2023-11-13) 只能作为历史指标输入，不称独立未暴露价格。

固定5个7周观察块：边界2023-11-13、2024-01-01、2024-02-19、2024-04-08、2024-05-27、2024-07-15。只分解同一原生 artifact，不分块重跑/重置仓位，不各选参数。交易按入场时间归块，跨块持仓仍属同一笔；各块 realized PnL 不能冒充逐块 MTM 收益。

D=[2024-07-15,2025-07-14)，364日；H及原生Stress=[2025-07-14,2026-05-25)，315日，Profile holdout_days=315。D pre-roll2024-06-16；H pre-roll2025-06-15。前阶段历史可作因果预热，绝不计作后阶段独立评分。所有持仓在各阶段清空重启。末端若原生退出落在排他终点、而核算缺少额外边界源，则 BLOCKED_DATA，禁止假设该边界已覆盖或修改日期救援。

全局账本原样105613 bytes，SHA256 4a3a95c716b90b3bf065fc52ad6d7a11a8fca2027087c2ff6bf35b589ece0459。110物理行含2空行，108 JSON记录；不重写空行或前缀。BCH相关记录105–110：OKX QC、Binance QC、单次技术周暴露；发现的 BCH 唯一经济评分暴露是该技术周。全资产 UNKNOWN [2026-05-31,2026-07-31)排除；同币跨交易所按同资产处理。早期未标资产记录无法证明全局绝对独立；已发现时间在本提案之外或使用旧窗口标签，外部未登记接触始终UNKNOWN。执行前在既有锁机制下重核完整前缀和新增记录后追加，不重开旧terminal。

项目纯理论容量=(245-2)*1=243笔，可容纳最低8笔；这不是自然信号数。以14–42日持仓仅作算术情景，满时暴露最多约6–17段，真实等待空仓与止损可改变数量；实际自然成交数在首次原生Search前UNKNOWN。35周只够筛查，不能作显著性/盈利确信。保留全部35周，不因对齐月界缩短；不足就UNDERPOWERED，不能降低门槛或改更快参数。

## Profile 与成本

BINANCE_CRYPTO_PERP/binance/BCH/USDT:USDT/futures/isolated/1d，1x，max_open_trades=1，初始1000 USDT、每笔固定500 USDT名义保证金（不复利加仓），tradable_balance_ratio=0.99；现金不够必须按原生和现有保守审计拒绝/记录，不提高余额。

taker_fee_rate=0.001/side，拆为手续费假设0.0005 + spread/slippage保守代理0.0005。原生 entry/exit各扣一次；人工报表只拆分已扣fee，不再外扣相同代理。不是实际账户费率，也不是实证估计的BCH冲击函数。原生Holdout Stress fee倍率2，合计0.002/side，可解释为手续费0.0005 + 流动性/滑点压力0.0015；不新增模型。

沿用 BINANCE_ASSOCIATED_MARK_BOUNDARY_V1：内区间funding用native/associated中较不利现金流；边界不确定付款计入、收款不计；保守扣减进入净/PF/现金/MTM DD；小时extrema压力只作另外风险诊断。按原artifact价格毛利、原生fee（拆分手续费与代理）、原生funding、审计附加扣减逐项对账。不把资金收款当价格趋势毛利。

## 固定门槛与解释

核心 Profile：min_development_trades=8（同时作用S），min_holdout_trades=10，min_profit_factor=1.10，max_drawdown_pct=15。economic Gate PROFILE_DRIVEN_ECONOMIC_GATE_V1/v1：minimum_net_profit_after_base_fees_pct=1.0；minimum_average_holding_period_minutes=4320；maximum_roi_exit_count=0。原生与保守投影均保留；按现有更保守资格执行，现金约束须全部通过；PF缺失/无亏损导致UNKNOWN不可伪造。

S额外人工门：至少8笔正持仓时长、自然信号/止损完成的有效交易（排除force_exit/liquidation）；long、short各至少2笔；至少3/5块有自然完成样本（按入场归块）；剔除单笔最大正保守净利润后，其余保守净和仍>0。原生总数过核心而有效数不足仍无合法finalist。块的盈亏只报告，不附加多数块盈利要求，不作参数选择。

D额外门：自然有效完成至少12笔，两方向各>=2；去最大赢家后保守净>0。H/Stress：有效自然>=10、两方向各>=2；各自同核心净>=1%、PF>=1.10、DD<=15%、现金通过、无ROI退出。原生加费可能改变路径，分别如实报告；不以固定路径扣费用替代真实Stress。

风险依据为个人1000余额、500固定仓、8%名义止损约4%初始钱包单次价损（费用/跳空另计），15%账户DD作为有限损失容忍；净1%与PF1.10只保留最小成本后缓冲，非统计显著性阈值。8/12/10及方向、去赢家门用于排除极少数/单次行情支撑。均为事前研究判断，不是论文推荐门槛；容量不足是一种预期可能终态。

## 预算与真实终态

建议 SINGLE_BASELINE_V1：一条源码、一轮、一次实际Search，零child。上层最多2轮/6次不是本协议再试授权。首次前冻结实际Profile快照、Generation/Candidate批准源码SHA、协议SHA和single-baseline JSON；源码生成只准实现本机制，静态偏离在首次取值前修正并重新审核，不反复生成选优。经济取值后不得换源/换窗/改参数重跑。

净/PF/DD/样本/人工门任一不达：项目真实NO_FINALIST或外层REJECTED/UNDERPOWERED_NO_EVIDENCE，D/H保持封存；不得伪造ResearchRun。技术INVALID保留null指标并分类BLOCKED_TECHNICAL；不标经济负例，未经监督处置不重跑。来源缺失/429/associated缺mark为BLOCKED_DATA。有效Search过全部门后报告原artifact绑定人工审阅，监督单独D授权；D过后再由监督显式授权同run H采集及H/Stress。无Release/交易。

总预算8–16主动小时，首次准备<=约45分钟；不为凑预算循环。只做源码/输入因果静态或合成T0及所需产物对账，不重复367测试或native smoke。

## 来源准备范围（监督已裁决，待整体协议冻结）

普通/单基线 configure_profile_acquisition 固定非空development_timerange；compile_source 按其stop验证全S+D candles/funding/associated。现存合规raw仅到2024-07-15，不能包装成本协议S+D来源。README也要求S与D从同一完整来源SHA导出。

监督已经明确授权：精确协议冻结后，允许机械采集完整D=[2024-07-15,2025-07-14)并立即物理隔离，仅身份/UTC连续性/associated mark完整性/来源QC；不看D收益、价格/率分布或策略评分。H仍不得采集/读取直到D通过后的明确授权。该准备不是Development实验，不建Search-only平台、不换runner。

最小来源方案：保留原S HTTP receipts/raw不改；调用项目现有 lab.binance_source.capture_native（内部唯一原生download-data）只采D及29日因果预热[2024-06-16,2025-07-14)，避免重新获取整段S。采集调用从冻结Profile派生数据范围（search_timerange设为此采集D区间、development_timerange=None，pre_roll=29）仅用于existing capture函数网络界限；它绝不作为研究source/profile冻结身份，最终compile_source必须使用原始冻结的S+D完整contract。capture原样记录请求、UTC与SHA。

合并来源仅为文件打包：复制已验证S和新D解码响应字节到新Git外目录，为文件名加S-/D-前缀避免碰撞，在新manifest中记录原receipt SHA、原body_file到新body_file映射，URL、时间、bytes、body SHA全部保持。由现有retained_responses严格核重复行完全相等；不拼接数字、不修改原rec/raw，不把两个采集批次称为一次原始抓取。capture本来支持保留多请求；本批是一个冻结研究来源、两个透明采集批次（S历史QC + D新增），不是拼接经济结果。若监督认为必须是单次物理检索，再明确授权新取完整S+D；未经该处置不执行。

最终现有fetch_binance_profile_data.py retained模式发布完整source；source provenance SHA和retrieval_receipt SHA现场产生，不能预造；prepare-search-data与prepare-development-data绑定同一实际SHA、Profile、窗口和economic Gate/single-baseline。D立即导出物理独立目录，Search只传S目录；直到合法finalist及D授权均不启动D策略。

一次新增D capture预算：最多2000 CCXT fetch、2GiB解码、5GiB存储、2小时、一个download-data进程，自动重试0。错误立即BLOCKED_DATA并保留响应/Retry-After；本协议不自动开第二次capture。后续重试必须先由监督处置且总尝试仍<=5，不复用失败目录。transport内部重定向实际次数UNKNOWN。现有已有S保留区间与D预热交叠仅用于输入一致性QC，不计第二次Search暴露。
