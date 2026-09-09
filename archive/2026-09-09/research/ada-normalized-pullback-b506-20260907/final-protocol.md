# Issue101 ADA_NORMALIZED_TREND_PULLBACK_3D_V1 — 待监督最终冻结

2026-09-07。基线main8079856520a961237079ba86cd1295485a03a20d；唯一固定源码AdaNormalizedTrendPullback3D.py / class AdaNormalizedTrendPullback3D。学习性已知回归家族，不宣称独立alpha。当前资金QC通过、工程与合成附件完成，完整行情/Generation/Candidate/Search/D/H/Stress均未执行。本文件没有给予执行授权。

## 可冻结的一页协议

- **唯一假说/合约：** `ADA_NORMALIZED_TREND_PULLBACK_3D_V1`，Binance `ADA/USDT:USDT` / `ADAUSDT`、USDT线性永续、UTC 1d、isolated 1x、单仓。短期逆向流动性需求可能在既有趋势内回归；这是从 DOGE/DOT/LTC 负例学习的已知回归家族改进，不是独立新 alpha，不是论文复现。ADA选择依据为成熟上市及无具名本币台账冲突，不根据价格表现；流动性、历史精度/tiers、完整 funding/mark 覆盖均 UNKNOWN。
- **精确因果规则：** 日 t 收盘后令 `r[t]=C[t]/C[t-1]-1`，`v[t]=mean(r[i]*r[i], i=t-20..t-1)`（事前20日均方，不称去均值标准差），`m[t]=mean(C[i],i=t-59..t)`。事前上行状态 `U[t]=(C[t-1]>m[t-1] and m[t-1]>m[t-6])`，下行状态对称反向。流动性 `L[t]=min(Low[i]*base_volume[i],i=t-30..t-1)>=500000 USDT` 且本日 volume>0。原始多事件 `Q+[t]=U[t] and r[t]<=-0.0125 and r[t]*r[t]>=2.25*v[t] and v[t]>0 and L[t]`；空事件为下行状态、`r[t]>=0.0125`，其余相同。`Q=Q+ or Q-`；准入事件 `E[t]=Q[t] and Q[t-1:t-3]全部为假`，检查全部原始Q而非只查E。t+1 open按E方向入场；E.shift(3)在t+3生成双向退出，正常t+4 open退出，72h。无下一日确认、无每日强制开仓；止损8%，ROI空字典、无trailing/加仓/自定义callback。阶段空仓起步，预热不计收益/持仓。数值计算仅需乘除、rolling mean/min、正shift；现有AST允许，不增std/sqrt许可。预热72根：60日均线+6日滞后=66；Q的3日抑制=69；退出3日=72。实现前仅合成序列验证因果性、抑制和原生entry→exit顺序；源码/AST摘要作为冻结附件，不能在市场值上改写择优。
- **时间窗（UTC、左闭右开）：** S `[2023-11-06,2024-11-04)`，D `[2024-11-04,2025-11-03)`，各364日；H/Stress `[2025-11-03,2026-05-25)`，203日。各自72日预热起点 `2023-08-26 / 2024-08-24 / 2025-08-23`。S/D物理日线各436、小时mark各10464、评分8h事件各1092；H为275/6600/609。首次完整S+D捕获范围 `[2023-08-26,2025-11-03)`，800日线、19200小时mark、2184评分事件；H不在该捕获中。S块边界2023-11-06/2024-02-05/2024-05-06/2024-08-05/2024-11-04；D为2024-11-04/2025-02-03/2025-05-05/2025-08-04/2025-11-03。H块边界2025-11-03/2026-01-05/03-16/05-25。不跨块重置仓位，按入场归块。
- **钱、成本与事前门：** E0=1000 USDT、固定stake250、余额比例0.99。base fee每边0.001=手续费假设5bp+滑点/价差代理5bp，原生双边扣一次；H Stress每边0.002。实际资金费无封顶，严格沿 `BINANCE_ASSOCIATED_MARK_BOUNDARY_V1`：完整8h事件、正associated mark、原timestamp及原生分钟映射、内部事件取native/exact较不利现金流、边界付款计入/收款不计，额外扣减进入净/PF/现金/小时close MTM DD；独立列价格毛利、费用、资金和额外扣减。S、D分别要求自然交易>=24、多空各>=8；H与Stress各>=14、多空各>=4。自然定义为持仓>=1440min且exit_reason仅exit_signal/stop_loss；force_exit、liquidation及其他退出一律不计自然样本，所有退出仍计全部盈亏/风险。各阶段原生总笔数至少相同门、平均持仓>=1440min、ROI退出0、价格毛利>0、保守净>=初始钱包1%、保守PF>=1.10、原生和保守小时close MTM DD均<=10%、现金可执行且>=0、去最佳单笔后净>0。S/D至少3/4块净>0，H/Stress至少2/3块净>0；全部块均有自然样本，最大正块盈利占全部正块盈利<=60%。这些是新的值前淘汰门，不是统计显著性证明，也不反向评定旧D。
- **唯一预算及停止：** 1次真实Generation/1 Candidate/1轮1次native Search；0参数网格、0第二币/第二窗、0native smoke、0自动重试。技术无效也占已调用native预算，不重播；S任一门失败即终止且D/H封存；S全门后监督另放D，D全门后才同一research_run_id一次H/Stress。D/H失败则本基线终止，不改阈值救援，不新增runner/表/服务/Release/交易。已观察收益不用于重新安排块或调整门。

## 两阶段省成本流程与最小下一授权

**阶段A：先排数据/容量明显不成立。** 本文冻结后，先在新Git外净化QC根做最多3次匿名HTTP GET、10分钟、2MiB解码、零重试/重定向：exchangeInfo一次只读取ADA身份/交易类别/状态，fundingRate两页覆盖上述S、每页<=1000。请求前约束symbol和start/end，endTime<=排他终点-1ms。只输出事件个数、UTC连续/重复/分钟映射、associated mark正值布尔及SHA；不输出价格或资金分布，不读D/H经济值。1092完整事件及全部mark有效方通过。失败即 `BLOCKED_DATA`，不缩窗、不修资金合同；这只能确认资金子合同。

QC通过后才批准窄pair映射和固定源码实现，再一次现有native capture/compile/prepare S+D，D机械QC与物理隔离；H不取。完整来源沿现有2000 CCXT fetch、7200秒、2GiB解码/5GiB目录阈值（后响应检查可超一个响应，wire attempts UNKNOWN），不另造更小硬预算接口。S廉价值前规则检查只计算冻结Q/E与方向/分块计数、流动性准入，不计算未来收益或模拟成交；这也算S信号暴露并登记，不能称纯机械QC或因此改参。若E总数/方向/分块已不可能达到自然门，直接 `UNDERPOWERED`，零native Search；实际自然样本仍由native决定。D/H永远不做该信号检查。

**阶段B：唯一native Search。** 阶段A通过且冻结源码/Profile/来源/窗口/经济门SHA后沿Console现有Generation→Candidate审批→prepare-search-data→单基线Search。不先跑另一个“便宜回测”窥探毛利。Search计算时间沿现有3600秒，失败证据保留；正常完成后对同一次产物分解价格毛利和完整成本，过门才有finalist。新净化六表DB与Git外证据使用现有JSON字段；无finalist不制造ResearchRun。D/H仍按上节各自门控。

**成本容量算术（非数据结论）：** 72h至多10次边界付款敏感性，每次1bp/5bp时，加20bp往返交易费用约30bp/70bp仓位成本；24笔达到钱包净1%需要每笔平均净16.67bp，即平均毛价格46.67bp/86.67bp；双倍交易费+5bp资金情景为106.67bp。1.25%入场冲击只是几何空间，回归比例未知，不能当预期盈利。E相隔至少4日，一年理论上限约91次、H约51次；24/14门有数学容量但自然到达率UNKNOWN。实际付款更大必须照扣，不以这些敏感性值封顶。

最小工程预计1–3主动小时：`lab/futures_costs.py::binance_identity`增加唯一ADA映射并纠正错误文案；现有Profile/producer/consumer已通过该helper传播，复核而非重写。补ADA身份、错币、funding/mark缺失、H绑定的合成定向回归；不改资金合同/validator/native。锁定native是否有ADA静态tiers必须只读确认，缺少则报告新的具体差异，不擅扩范围。固定策略合成验证/冻结约1小时；QC通常数分钟、硬限10分钟；后续来源与Search墙钟分别最多2小时/1小时，主动审计约1–2小时。没有历史窗口的自然等待，但H数据完整性直到获准QC仍UNKNOWN。PR100的38项测试不重做，本轮未运行测试。


## 实际固定源码及实现解释

源码 SHA256 `eb1f551464519f52b6f29469843dfe0acc880b53a6e86b778b94f09a88eda4b8`。AST现有验证器PASS，963节点、startup72/max_lookback72，无validator/native修改。实际代码字节为未来执行唯一版本，不使用市场数据挑表达式。`gap=C[t-1]-m[t-1]`、`slope=m[t-1]-m[t-6]`；对合法非负volume及均方v，`gap*slope*v*volume>0`等价于趋势两项同号且v/volume正；`r*gap<0`限定逆当前冲击。`r*r>=0.00015625`与r符号实现1.25%双向阈值，`r*r-2.25*v>=0`实现归一化阈值。浮点边界以冻结源码为准；这种数值等价表达用于现有AST预算，不改变经济参数。

合成两组各300日上/下趋势人工序列与独立循环原定义逐行一致，各有原Q85/87/90/94/210/250，准入E85/94/210/250；87被85抑制后仍抑制90，验证不错误采用仅E抑制。零当日volume、前30日低交易额排除；另120行平价v=0无信号；20次前缀截断无未来依赖。真实IStrategy.ft_advise_signals调用entry再exit；纯时间算术核8个获准事件t+1open至t+4open=72h，不调用matching engine、不计PnL、不称native smoke。正常时序仍以冻结原生backtesting.py信号整体shift(1)语义为依据，止损可以提前。

纯人工测试不证明实际自然样本充足或可成交；自然计数严格只含持仓>=1440min且exit_reason为exit_signal/stop_loss，liquidation/force_exit/其他退出不计样本但所有盈亏风险计入。Generation未来只实现本冻结代码，不重新选参数；只有监督批准后才通过现有项目入口形成真实Candidate。尚无真实ID/来源SHA时明确未产生，不预造。

## 当前验收附件与最小工程

唯一业务改动为binance_identity映射ADA及对应错误文字。Profile验证、capture配置/请求、retained response/compile、source consumer、成本审计和同Run H通过既有helper传pair，不新增业务模块。直接测试27 passed、37 deselected、0skip、67依赖弃用warnings、3.35秒；包含BCH/DOGE正向兼容、ADA错币/缺事件/associated mark、原子失败、真实HTTP同Run H授权及重复拒绝、Release封存。没有重跑PR100的38测试或整库。

资金QC根仍 /Users/shenjianpeng/.codex/runs/freqtrade-lab/ada-funding-qc-b506-20260907；1092事件/3GET/1241729bytes，状态仅资金子合同PASS，qc-report SHA3b63a74cdd4be4c6b7320e18ed99a24352565820b72bd2f53ef7ec1d2cedda0e。锁定native ADA tiers具名；历史精度/档位和流动性UNKNOWN。全局ledger此刻129434bytes SHA175577aa8424b0c9b0d477e5b5925528b4e0864ad0ae587d2c23d9ca31323003，无cohort预留；本工程不追加研究记录。

上一节阶段A资金QC已完成；其余授权仍未取得。本文件经root按字节冻结并验收工程后，才能另授权完整capture/Generation等后续步骤。完整S+D capture仅一次、预热funding不评分，H不采集；三阶段物理隔离、同Run/原资金合同和六表边界不变。人工序列之外未读市场值。

工程审阅PR102：https://github.com/He1met/freqtrade-lab/pull/102，固定head `42beabbd6ade2b7fc9639f236199c9bb8b7019e2`，仅lab/futures_costs.py与两个测试文件。尚未合并；未来执行必须先核监督验收merge及绑定实际运行lab SHA，不能把当前open PR称为已部署。
