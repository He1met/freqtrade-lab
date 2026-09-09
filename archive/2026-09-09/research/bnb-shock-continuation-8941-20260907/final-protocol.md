# Issue104：BNB_DAILY_SHOCK_CONTINUATION_48H_V1

2026-09-07，待监督按字节批准；不是研究执行授权。唯一源码BnbDailyShockContinuation48H.py，class BnbDailyShockContinuation48H，SHA d250751eb5314acb622266a6033e603da2c137b96592d7a16c7bd7498ddc4ba6。当前只授权3文件映射工程、合成证明和PR；Generation、完整采集、业务DB及native研究尚未执行。

## 假说、对象与证据限制

唯一BNB/USDT:USDT / BNBUSDT、Binance USDT线性永续、UTC 1d、isolated 1x、单仓。成熟合约及链上gas/交易生态用途提供对象选择理由；大幅已闭日收益后注意力/信息扩散可能延续，是已知动量家族的单资产试验。不是独立alpha、不按收益排序、不是论文复现；不因换币调整±3%门。平台相关集中风险、自然频率、完整数据、历史流动性/档位/精度和未来毛利UNKNOWN。

有限QC六GET通过（corrected-receipt.json SHA e12969581cec216e4712e6da51a4f901542c58e67843d31b5d3ab26e454596cc）；1110282 decoded bytes，资金1867bytes，65.353秒。首件脚本错误使用精确毫秒整点，原件及correction保留；现有futures_costs.py原分钟桶合同本来允许毫秒偏移，原时间未改，未重复GET。身份及5代表日15事件关联mark均正有限，不证明全期覆盖。D/H仅有限资金元数据QC暴露，OHLCV和策略结果未读。ledger追加后138140bytes SHA62219c3f913e53d9ab2d9345cd0412728cb0c40c5259de39190bd212a547ed91，旧137019bytes前缀逐字节保留。

## 唯一规则与时序

日t收盘 r[t]=C[t]/C[t-1]-1；L[t]=min(Low[i]*base_volume[i],i=t-30..t-1)>=500000 USDT 且volume[t]>0。Q+[t]=L[t]且r[t]>=0.03，Q-[t]=L[t]且r[t]<=-0.03；Q为并集。E[t]=Q[t]且Q[t-1]、Q[t-2]均假，方向与r一致。前两日检查原始Q，不只查准入E。

t+1 open入场；E.shift(2)在t+2产生双向exit_signal，t+3 open正常退出，48h。源码将布尔条件内联以满足现有AST；退出引用同次ft_advise_signals先生成的enter_long/short，再正shift2。止损8%，minimal_roi={}，无trailing/加仓/callback；不另造runner。日内止损仍可能提前退出，短于24h不计自然样本但计全部损益。预热35根，AST max_lookback35。阶段开始空仓，预热信号不能携仓进入；阶段末force_exit计盈亏不计自然样本。所有经济结果依据实际native归档，合成时序不能当成交证据。

合成证明synthetic-proof.json：两方向独立逐日oracle与源码完全相等；16次prefix不变检查；原始Q41/43被抑制、E40/46准入；本日零量、过去30日低量、平价序列拒绝。直接调用锁定Freqtrade的_get_ohlcv_as_lists纯转换helper（无Backtesting构造/撮合/backtest/native命令），验证trim先于shift、预热第34日冲击不能第35日入场；评分第40/46日事件实际移至41/47日入场、43/49日退出=48h，尾部不完整事件不作自然完成。工程定向测试25 passed/59 deselected/0 skipped；无市场数据测试、无native smoke。

## 精确窗口与消费边界

全UTC左闭右开；S [2023-11-06,2024-11-04)，D [2024-11-04,2025-11-03)，H及Stress [2025-11-03,2026-05-25)。35日预热起点分别2023-10-02、2024-09-30、2025-09-29。S/D各364日评分，含预热399日线/9576小时mark/1092评分8h资金事件；H203日，含预热238日线/5712小时mark/609评分8h事件。

S四块端点2023-11-06/2024-02-05/05-06/08-05/11-04；D为2024-11-04/2025-02-03/05-05/08-04/11-03；H三块端点2025-11-03/2026-01-05/03-16/05-25（63/70/70日）。按实际入场归块，不在块界平仓/重置，不事后改块。

当前ledger无BNB具名占用（本probe除外），外部未登记暴露UNKNOWN。旧BCH/DOGE/ADA的S消费、D消费或QC保护、H封存均不触碰；全资产UNKNOWN[2026-05-31,2026-07-31)避开。跨资产同期的旧学习明确污染选择，不能称统计独立；本币评分窗时间分离和留出封存只是有限防护。D/H预热单向来自前阶段尾部，绝不把D/H评分行情给S开发。H有限元数据接触不等于策略开封，也不再称物理未采集。

## 冻结样本、成本和经济门

初始钱包1000 USDT、stake250固定、余额比例0.99；每边base fee0.001=手续费假设5bp+滑点价差代理5bp，原生双边扣一次；H Stress每边0.002。报价/流动性历史精度UNKNOWN，不声称真实费率已查。

严格BINANCE_ASSOCIATED_MARK_BOUNDARY_V1：完整8h评分事件、关联mark正有限、原timestamp保留/原生分钟桶唯一映射；内部资金现金流取native/exact较不利者、边界付款计入/收款不计，额外扣减进入净利/PF/现金/小时close MTM DD。缺mark不补价、不用小时收盘替代；实际资金费不封顶。输出价格毛利、手续费/滑点代理、资金、额外扣减各项，NULL不转0。

S/D各要求自然交易>=24、long>=8、short>=8；H/Stress各>=14、各向>=4。自然=持仓>=1440min且exit_reason仅exit_signal/stop_loss；force_exit/liquidation/其他退出不计自然，全部损益仍计。原生总笔数同样达门，平均持仓>=1440min、ROI退出0。各阶段价格毛利>0、保守净>=初始钱包1%、保守PF>=1.10、原生及保守小时close MTM DD<=10%、现金可执行且非负、去掉最佳单笔后净>0。S/D至少3/4块净正；H/Stress至少2/3块净正；每块有自然样本，最大正块盈利占全部正块盈利<=60%。DD为小时观测而非连续市场风险保证。

门的值前理由：一年约每月两笔并覆盖双向、半年略高于每月两笔，作为小项目的淘汰底线，不能证明统计显著。48h且原始Q抑制两日，正常完整交易纯结构上限S121、D121、H67；上限不是自然频率。IID模型p(1-p)^2<=4/27，全年p=0.1/0.2/0.4/0.6仅在假设下约29.5/46.6/52.4/34.9个E；真实聚集/止损/方向失衡可能更低，不能靠此模型通过样本门。203日H结构有67的空间，不保证达到14。

48h按8h资金含边界至多7次的固定名义敏感性：每次1/5bp，base往返20bp后毛盈亏平衡27/55bp，Stress47/75bp。24笔赚到钱包1%需平均每笔净16.67bp，毛43.67/71.67bp；H14笔需净28.57bp、毛55.57/83.57bp，Stress各加20bp。这只是成本算术，实际按名义和原资金事件扣费；过去3%绝非未来延续幅度，收益UNKNOWN。

## 唯一阶段预算与项目入口

先由监督审PR精确head、此协议/源码/合成SHA；合并代码后才能另授权真实Profile/Generation。一次真实Generation、唯一Candidate，源码须与批准字节一致，使用现有正式生成/审批入口，不伪造成功。所有研究复用六表DB/Console；本轮Profile.min_development_trades=24，H门14及原经济门冻结，source/protocol/strategy/Profile哈希交叉绑定。

完整采集一次：scripts/fetch_binance_profile_data.py，S+D源[2023-10-02,2025-11-03)，763日线/18312小时mark、2184评分资金，阶段独立发布，D只机器QC不跑信号；源指纹/连续性/资金原事件/身份/分钟映射/consumer全部通过才可S。捕获复用现有硬限2000 CCXT fetch、2GiB decoded、5GiB磁盘、2h，无自动重试/第二capture/拼接。预算是上限，不是预计负载；旧800日来源约64fetch仅为耗时参考。H未在此capture内。

S总事件预筛最多一次，不计算收益、不模拟成交；按实际next-open落S计总上界。total<24时复用PR103正式CLI把UNDERPOWERED及冻结绑定写Candidate.metadata_json，PnL NULL，验API/页面；此窄入口只支持总容量不足，不扩展单边/分块终态。total>=24则单边/分块和自然交易条件由唯一正式Search判门，不人工放行。任何信号接触都记S已消费。

Search单轮单次<=1h，零native smoke、参数网格、备选源码或自动重试；技术无效也占调用预算。S全门后监督另放D单次<=1h；D全门才另放H来源一次<=2h、H与Stress各一次native<=1h，三结果绑定同research_run_id。任何阶段失败就终止此候选/窗口，不降门、换窗或换币救援。数据失败=BLOCKED_DATA、经济UNKNOWN；经济/样本失败保留真实终态。无finalist不造ResearchRun，无Release/资金/实盘。

预筛或正式终态必须实际留DB，并核正式CLI/API/Console证据再讨论Issue验收；外部JSON不替代项目闭环。当前Issue104保持OPEN，小PR只交工程，不自行merge。预计剩余工程审阅0.5–1小时；获数据执行授权后采集/研究审计约2–4主动小时外加运行及分阶段监督，不展开平台工程。
