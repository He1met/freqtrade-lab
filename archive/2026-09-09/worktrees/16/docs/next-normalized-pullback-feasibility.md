# 下一轮合约研究：归一化顺势回撤，待监督冻结

2026-09-07；执行任务 `01a07a3d-66af-7892-b3e4-983b7086b0b7`，监督 `01a05dcc-17fd-7972-9177-9fed95e4b07a`。初轮完成资料/元数据研究后，监督另授权并完成唯一ADA S资金QC；1092事件通过，未取OHLCV/D/H、生成Candidate、运行策略或写研究数据库。结论：**资金子合同通过，仍非 SOURCE_READY 或 SEARCH_READY；下一动作是监督授权唯一ADA窄适配及固定源码合成验证，经济协议待源码附件最终冻结。**

## 可冻结的一页协议

- **唯一假说/合约：** `ADA_NORMALIZED_TREND_PULLBACK_3D_V1`，Binance `ADA/USDT:USDT` / `ADAUSDT`、USDT线性永续、UTC 1d、isolated 1x、单仓。短期逆向流动性需求可能在既有趋势内回归；这是从 DOGE/DOT/LTC 负例学习的已知回归家族改进，不是独立新 alpha，不是论文复现。ADA选择依据为成熟上市及无具名本币台账冲突，不根据价格表现；流动性、历史精度/tiers、完整 funding/mark 覆盖均 UNKNOWN。
- **精确因果规则：** 日 t 收盘后令 `r[t]=C[t]/C[t-1]-1`，`v[t]=mean(r[i]*r[i], i=t-20..t-1)`（事前20日均方，不称去均值标准差），`m[t]=mean(C[i],i=t-59..t)`。事前上行状态 `U[t]=(C[t-1]>m[t-1] and m[t-1]>m[t-6])`，下行状态对称反向。流动性 `L[t]=min(Low[i]*base_volume[i],i=t-30..t-1)>=500000 USDT` 且本日 volume>0。原始多事件 `Q+[t]=U[t] and r[t]<=-0.0125 and r[t]*r[t]>=2.25*v[t] and v[t]>0 and L[t]`；空事件为下行状态、`r[t]>=0.0125`，其余相同。`Q=Q+ or Q-`；准入事件 `E[t]=Q[t] and Q[t-1:t-3]全部为假`，检查全部原始Q而非只查E。t+1 open按E方向入场；E.shift(3)在t+3生成双向退出，正常t+4 open退出，72h。无下一日确认、无每日强制开仓；止损8%，ROI空字典、无trailing/加仓/自定义callback。阶段空仓起步，预热不计收益/持仓。数值计算仅需乘除、rolling mean/min、正shift；现有AST允许，不增std/sqrt许可。预热72根：60日均线+6日滞后=66；Q的3日抑制=69；退出3日=72。实现前仅合成序列验证因果性、抑制和原生entry→exit顺序；源码/AST摘要作为冻结附件，不能在市场值上改写择优。
- **时间窗（UTC、左闭右开）：** S `[2023-11-06,2024-11-04)`，D `[2024-11-04,2025-11-03)`，各364日；H/Stress `[2025-11-03,2026-05-25)`，203日。各自72日预热起点 `2023-08-26 / 2024-08-24 / 2025-08-23`。S/D物理日线各436、小时mark各10464、评分8h事件各1092；H为275/6600/609。首次完整S+D捕获范围 `[2023-08-26,2025-11-03)`，800日线、19200小时mark、2184评分事件；H不在该捕获中。S块边界11-06/02-05/05-06/08-05/11-04；D为11-04/02-03/05-05/08-04/11-03，年份随上述窗口。H块边界2025-11-03/2026-01-05/03-16/05-25。不跨块重置仓位，按入场归块。
- **钱、成本与事前门：** E0=1000 USDT、固定stake250、余额比例0.99。base fee每边0.001=手续费假设5bp+滑点/价差代理5bp，原生双边扣一次；H Stress每边0.002。实际资金费无封顶，严格沿 `BINANCE_ASSOCIATED_MARK_BOUNDARY_V1`：完整8h事件、正associated mark、原timestamp及原生分钟映射、内部事件取native/exact较不利现金流、边界付款计入/收款不计，额外扣减进入净/PF/现金/小时close MTM DD；独立列价格毛利、费用、资金和额外扣减。S、D分别要求自然交易>=24、多空各>=8；H与Stress各>=14、多空各>=4。自然定义为持仓>=1440min且exit_reason仅exit_signal/stop_loss；force_exit、liquidation及其他退出一律不计自然样本，所有退出仍计全部盈亏/风险。各阶段原生总笔数至少相同门、平均持仓>=1440min、ROI退出0、价格毛利>0、保守净>=初始钱包1%、保守PF>=1.10、原生和保守小时close MTM DD均<=10%、现金可执行且>=0、去最佳单笔后净>0。S/D至少3/4块净>0，H/Stress至少2/3块净>0；全部块均有自然样本，最大正块盈利占全部正块盈利<=60%。这些是新的值前淘汰门，不是统计显著性证明，也不反向评定旧D。
- **唯一预算及停止：** 1次真实Generation/1 Candidate/1轮1次native Search；0参数网格、0第二币/第二窗、0native smoke、0自动重试。技术无效也占已调用native预算，不重播；S任一门失败即终止且D/H封存；S全门后监督另放D，D全门后才同一research_run_id一次H/Stress。D/H失败则本基线终止，不改阈值救援，不新增runner/表/服务/Release/交易。已观察收益不用于重新安排块或调整门。

## 两阶段省成本流程与最小下一授权

**阶段A：先排数据/容量明显不成立。** 本文冻结后，先在新Git外净化QC根做最多3次匿名HTTP GET、10分钟、2MiB解码、零重试/重定向：exchangeInfo一次只读取ADA身份/交易类别/状态，fundingRate两页覆盖上述S、每页<=1000。请求前约束symbol和start/end，endTime<=排他终点-1ms。只输出事件个数、UTC连续/重复/分钟映射、associated mark正值布尔及SHA；不输出价格或资金分布，不读D/H经济值。1092完整事件及全部mark有效方通过。失败即 `BLOCKED_DATA`，不缩窗、不修资金合同；这只能确认资金子合同。

QC通过后才批准窄pair映射和固定源码实现，再一次现有native capture/compile/prepare S+D，D机械QC与物理隔离；H不取。完整来源沿现有2000 CCXT fetch、7200秒、2GiB解码/5GiB目录阈值（后响应检查可超一个响应，wire attempts UNKNOWN），不另造更小硬预算接口。S廉价值前规则检查只计算冻结Q/E与方向/分块计数、流动性准入，不计算未来收益或模拟成交；这也算S信号暴露并登记，不能称纯机械QC或因此改参。若E总数/方向/分块已不可能达到自然门，直接 `UNDERPOWERED`，零native Search；实际自然样本仍由native决定。D/H永远不做该信号检查。

**阶段B：唯一native Search。** 阶段A通过且冻结源码/Profile/来源/窗口/经济门SHA后沿Console现有Generation→Candidate审批→prepare-search-data→单基线Search。不先跑另一个“便宜回测”窥探毛利。Search计算时间沿现有3600秒，失败证据保留；正常完成后对同一次产物分解价格毛利和完整成本，过门才有finalist。新净化六表DB与Git外证据使用现有JSON字段；无finalist不制造ResearchRun。D/H仍按上节各自门控。

**成本容量算术（非数据结论）：** 72h至多10次边界付款敏感性，每次1bp/5bp时，加20bp往返交易费用约30bp/70bp仓位成本；24笔达到钱包净1%需要每笔平均净16.67bp，即平均毛价格46.67bp/86.67bp；双倍交易费+5bp资金情景为106.67bp。1.25%入场冲击只是几何空间，回归比例未知，不能当预期盈利。E相隔至少4日，一年理论上限约91次、H约51次；24/14门有数学容量但自然到达率UNKNOWN。实际付款更大必须照扣，不以这些敏感性值封顶。

最小工程预计1–3主动小时：`lab/futures_costs.py::binance_identity`增加唯一ADA映射并纠正错误文案；现有Profile/producer/consumer已通过该helper传播，复核而非重写。补ADA身份、错币、funding/mark缺失、H绑定的合成定向回归；不改资金合同/validator/native。锁定native是否有ADA静态tiers必须只读确认，缺少则报告新的具体差异，不擅扩范围。固定策略合成验证/冻结约1小时；QC通常数分钟、硬限10分钟；后续来源与Search墙钟分别最多2小时/1小时，主动审计约1–2小时。没有历史窗口的自然等待，但H数据完整性直到获准QC仍UNKNOWN。PR100的38项测试不重做，本轮未运行测试。

## 机制选择及证据限度

| 排序 | 方向 | 价格毛利可能来源、成本与样本 | 数据/个人维护成本与决策 |
|---|---|---|---|
| 1 | 事前趋势内的波动归一化回撤，72h | 临时价格压力回归；归一化让事件尺度随事前波动变化，趋势条件尝试避开逆长期方向的信息冲击。无需等一天确认，可能保留更多回归空间，也可能更早接住持续下跌。周转较慢；过滤导致样本不足的风险真实存在。 | 只用现有1d OHLCV与会计mark/funding；一条规则、无外部因子服务。选择作有界学习性假说，收益UNKNOWN。 |
| 2 | 自身中期收益符号的趋势持仓 | 可能来自信息迟滞/持续需求；加密论文有time-series momentum证据。更长持仓减少往返费却增加资金占用；持续趋势少次退出，单币年窗自然样本风险更大。 | 原生OHLCV可跑、维护小，但与BCH28/14旧趋势负例靠近；不通过换币或更快均线当独立机制。此次不设候选/参数/经济预算。 |

旧DOGE证据只证明固定候选跨期未成立：S33笔保守+165.319130、PF1.975491、收益集中末块；D正式状态FAILED/NULL，幸存产物旁路价格毛利-50.691930、保守净-66.568424、PF0.759588、小时close DD15.545210%，五项冻结门失败。固定4%在不同波动环境对应不同标准化罕见度是数学事实；“该差异造成D失败”“确认太迟”“趋势过滤能改善”均未作归因检验，仍是假说。没有分割旧D找优胜子集，也不在DOGE调参重跑。

仅使用以下直接原始/官方来源支持研究问题，不宣称论文支持本文数字：

1. [Nagel, Evaporating Liquidity](https://www.nber.org/papers/w17653)：官方摘要讨论股票短期回归作为流动性供给收益代理及状态依赖。不能外推为ADA信号，本文没有VIX/订单流，不能识别真正流动性供给；只支持检验条件化而非无条件回归。全文请求失败，本轮阅读官方完整摘要。
2. [Liu & Tsyvinski, Risks and Returns of Cryptocurrency](https://www.nber.org/papers/w24877)：官方摘要对BTC/XRP/ETH报告自身时间序列动量和注意力预测。支持比较趋势方向，不能证明ADA或本文60日/3日组合；全文请求失败，不称复现。
3. [Binance ADA合约上市公告](https://www.binance.com/en-TR/support/announcement/detail/360039355391)：官方索引正文确认2020-01-31 08:00UTC上市。打开链接目前重定向公告列表，保留检索正文证据；不以此证明2023年以来连续交易、当前流动性或tiers。
4. [Binance USDⓈ-M市场数据官方合同](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)：fundingRate具有symbol/rate/time及对应费用的markPrice，最多1000条、时间升序。API字段定义不能保证每个历史事件有效；仍须逐个QC，不能用小时mark补缺associated mark。

## 当前仓库、窗口与证据核对

远端main/PR100 merge均为 `8079856520a961237079ba86cd1295485a03a20d`，Issue98 CLOSED。独立worktree初始clean、detached `df3dc41`；监督明确授权后fetch并ff-only到上述main，现在代码对齐；未动原checkout及其未跟踪需求文档。PR100只变worker路径与测试，未重复修复。新研究尚无任何运行记录。

全局ledger只读，127083字节、SHA256 `7f9e1ee2c871496085a13101873d8a0c78e12c69d6caaa7eec42fb9fafd9cf44`；保留原空行与每个旧前缀，本轮零追加。BCH S `[2023-11-13,2024-07-15)`已消耗（11-06至11-13技术暴露）；D `[2024-07-15,2025-07-14)`保护、H `[2025-07-14,2026-05-25)`封存。DOGE S/D分别为本提案同日历两年，均已消耗，H同日历封存。全资产 `[2026-05-31,2026-07-31)`避开。不得跨交易所洗掉这些本币暴露。

现有两币无**已验证满足当前资金合同的完整空闲S/D/H链**：BCH更早期缺associated mark在仓库已记录，最后缺失为2023-10-31；不借此声称DOGE早期也缺。早期DOGE是**UNKNOWN，非已证伪**；可在另一授权中做覆盖QC，但要把全部S/D/H排在2023-11-06前，距今较远、且同币学习仍存在。为减少老资金覆盖摸索，本次推荐成熟ADA的2023-11后链；这是在已验证能力限制下的实用优先级，不是证明原两币所有可能窗口不可用。2026-07-31后至今仅约38日，不能同时支持本文三个阶段，等待未来完整链为年级日历成本。

完整元数据未发现具名ADA/ADAUSDT消费或保留，结论仅 `NO_NAMED_ADA_OVERLAP_FOUND_IN_SCOPED_LEDGER`。早期未绑定pair的历史记录及外部接触UNKNOWN；其他币同日历已被研究，因此跨资产相关冲击与研究者学习存在，不称跨币统计独立或绝对未见数据。首次获准QC前在原ledger锁下复核新追加及监督已知具体冲突，真实冲突即停；不是要求证明全球无外部接触。本文件只是提案，未为ADA登记预留或消费。

旧任务仅取最近交接；精确授权根四文件已只读核SHA：`final-protocol.md=e0920ce3dfe27bdc7dff18828ed0676c6f3cbefa4eb160e33f5dcf5585ee9127`；`search-protocol-review.json=fac6b55610ccb8c9b642163131adfdf2cfb1f7ff2e99f9c8329058b67fe1ce69`；`development-posthoc-diagnostic.json=b9bae49ed10c0c34ad1f3e11f196e8c7759136441312ad53d2ab164ca1ce4a7e`；`development-recovery-assessment.md=8fd4b5dc9debeb30078232d885c57dd2d401e8f0fa94258dc84c5c046c951602`。未读取旧DB、H市场值或其他运行根。

总体策略发现目标未完成；完成的是本轮可行性筛选。推荐只先授权阶段A的3GET资金子合同QC；通过后再批准窄适配/固定实现和完整采集，确认全部冻结附件后才唯一Search。失败有真实数据/样本/经济终态，不承诺必然盈利。

## 后续单独授权阶段A实绩

监督修正自然样本为持仓>=1440min且仅exit_signal/stop_loss，本文已更正，其余数字不变。2026-09-07T05:09:12Z，实际3匿名GET、1,241,729 decoded bytes、0.463秒、零重试/重定向，ADAUSDT当前TRADING/PERPETUAL/USDT线性；1092/1092事件，首2023-11-06T00:00Z、末2024-11-03T16:00Z。重复/缺失/额外分钟桶、错symbol、非Regular、无效associated mark、非有限率均0；原timestamp保持不变。状态 FUNDING_CALENDAR_ASSOCIATED_MARK_QC_PASS_NOT_SOURCE_READY。预算实现为应用保留正文<=2MiB、解码迭代器触限最多多交付4096字节块随即停止、SIGALRM600s；不是wire上限，本次未触限。

QC根 `/Users/shenjianpeng/.codex/runs/freqtrade-lab/ada-funding-qc-b506-20260907` 保留复用脚本、授权、三响应与receipt、UTC序列及qc-report。qc-report SHA256 `3b63a74cdd4be4c6b7320e18ed99a24352565820b72bd2f53ef7ec1d2cedda0e`。按监督授权同一原sidecar锁追加预GET QC_ONLY控制与终态，不预留cohort、search_consumed=false；旧127083字节和2空行保留。终态ledger 129434 bytes，SHA `175577aa8424b0c9b0d477e5b5925528b4e0864ad0ae587d2c23d9ca31323003`。

只读锁定native的binance_leverage_tiers.json已具名ADA/USDT:USDT；历史档位适用性UNKNOWN。业务唯一映射仍只有BCH/DOGE；尚未改业务代码/生成源码或Candidate/完整capture/Search/D/H/Stress/数据库。此前“本轮零采集/ledger零追加”描述初轮可行性快照，由本节明确记录后续独立授权行动；其余旧资产封存不变。Issue101保持OPEN。

## 后续授权工程与冻结附件

唯一ADA映射与错误文案完成，PR102（https://github.com/He1met/freqtrade-lab/pull/102）head42beabbd6ade2b7fc9639f236199c9bb8b7019e2，尚未合并。仅业务helper+两个测试文件，定向27 passed/37 deselected/0skip，3.35秒，未native。Git外最终冻结包 `/Users/shenjianpeng/.codex/runs/freqtrade-lab/ada-normalized-pullback-b506-20260907`：final-protocol.md SHA66b18f5162e9020945562e31f1ad34a35305a8e1cac752d88aad084817ea8d57；AdaNormalizedTrendPullback3D.py SHAeb1f551464519f52b6f29469843dfe0acc880b53a6e86b778b94f09a88eda4b8；AST963节点/最大回看72，合成两组300日+120日平价及20前缀检查通过。完整内容以该冻结包为最终待审字节，本文保留先前可行性历史。未完整采集/Generation/Candidate/Search/D/H/Stress/业务DB写入，等待监督验收工程并冻结最终协议。
