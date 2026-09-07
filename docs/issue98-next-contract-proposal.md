# Issue 98：下一轮合约研究提案，等待监督冻结

2026-09-07。结论：建议只推进 **DOGE 日线双向冲击后确认回归** 的一次来源可行性门；不是 Search-ready，更不是合格策略。当前 Binance 业务链只允许 BCH，DOGE 需要三个现有模块的窄适配。先验证固定 S 的资金数据，失败即停止，避免先做工程。现货仅作为未来备选，未获本轮执行授权。

## 当前证据与三机制比较

本工作树 `/Users/shenjianpeng/.codex/worktrees/bb9d/freqtrade-lab` 从干净 detached `fa1d19e` fetch 后建 `codex/next-mechanism-feasibility-v1`，起点/实时远端 main `fcb52ff59013b3a49271a259293069b62907578e`。已读 AGENTS、Issue98、96、84、78、66、62、34；旧open Issue不当运行状态，不关闭或恢复它们。未修改原checkout。锁定原生checkout当前干净、HEAD `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`；本轮未启动native或重验整套依赖/367测试。

| 机制 | 旧证据解释、输入与费用容量 | 本轮选择 |
|---|---|---|
| 冲击后价格回归，增加一天方向确认 | DOT2h逆转有正价格毛利但成本后失败；XRP日线和DOT低活动因数据阻塞，不能当经济负例；LTC量能回归已有负例。等待一日反向收盘，尝试区分持续信息冲击与短暂压力；减少即时接刀，代价是错失反弹及少样本。只需OHLCV，固定72h持仓；每次费用/funding均核算。 | 唯一提案；既有回归家族的学习性改进和跨品种研究，非新独立alpha，确认增量没有被实验归因。 |
| 更长周期自有价格趋势 | BCH28/14价格毛利本身为负、自然仅7笔，且资金费支出明显；不是降费即可修复。OHLCV可表达，但更长持仓增加资金暴露，并在一年S内进一步压低自然样本；缩短参数又容易重演周转问题。 | 本轮不运行。论文多市场12个月趋势证据不等于单币日线有效；不以更快参数挽救BCH。 |
| 资金费/基差carry | 已有LINK滞后资金费负例及BTC会计/因果无效记录；正funding不保证空头价格净收益。真正对冲carry需要同期现货/合约两腿、基差及成本；当前单仓OHLCV AST无funding输入，单腿不能冒充carry。 | 模型表达不符，本轮不开发、不运行。 |

实际阅读：Lehmann [NBER原论文摘要](https://www.nber.org/papers/w2533)论及股票周度赢家/输家逆转；全文请求403，未声称阅读全文。Moskowitz/Ooi/Pedersen [作者机构摘要](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)是58个期货/远期的较长周期证据。两者仅支持研究问题，不支持本文阈值或DOGE收益。[Freqtrade官方回测假设](https://docs.freqtrade.io/en/stable/backtesting/#assumptions-made-by-backtesting)说明next-open/止损近似及费用双扣边，实际以锁定源码为准。

## 品种、隔离与真实数据门

仅选 `Binance DOGE/USDT:USDT / DOGEUSDT`，USDT线性永续、isolated 1x、1d、单仓。事前选择理由：非新上市合约，[官方公告](https://www.binance.com/zh-CN/support/announcement/detail/7777402b13574c41afe13b334d3e047e)确认2020-07-10上市；锁定native静态档位文件含该pair；台账未见DOGE具名消费/保留。优先成熟合约和完整年份，未下载报价、未按PnL或市场表现排名。历史/当前流动性、精度与档位适用性、资金日历完整性仍UNKNOWN；没有宣称其最优或高流动性已证实。

全局ledger仍112022 bytes，SHA256 `84e8c49eab8b40eb39559e0468a914ae80506dbf7b60cb93402e9ecb18891271`。逐行只摘机制/窗口/次数/状态等控制字段；具名DOGE无命中。早期 `HISTORICAL_DEVELOPMENT` 等不完整记录不能支持绝对全局无接触，外部未登记暴露为UNKNOWN。适用结论仅 `NO_NAMED_DOGE_OVERLAP_FOUND_IN_SCOPED_METADATA`，不是统计独立；其他币同日历已研究，市场共同冲击及选择学习无法消除。root应在任何QC前确认未登记DOGE接触或已知保留；有具体冲突即停，不换名绕过。

所有范围UTC半开，日界00:00:00Z：

| 阶段 | 固定评分范围 | 日数 | 35日价格/mark预热起点 |
|---|---|---:|---|
| S | [2023-11-06, 2024-11-04) | 364 | 2023-10-02 |
| D | [2024-11-04, 2025-11-03) | 364 | 2024-09-30 |
| H / H Stress | [2025-11-03, 2026-05-25) | 203 | 2025-09-29 |

S/D各52周，事前划4个连续13周块；H划7/7/7/8周。评分无交集，预热仅因果指标、各阶段空仓起步，不继承持仓。避开全资产未知暴露[2026-05-31,2026-07-31)。不挪BCH旧D/H，不把跨交易所同币当独立。H尚未采集；D只在另获机械QC授权后采集，不能用于选规则。日期依据为2023年11月之后的资金数据契约可行性假设及完整52周容量，**BCH的可用起点不证明DOGE也可用**。

早期BCH永续明确NO_GO：净化 `native-futures-01a0777f-20260907/full-s-qc.json` 有1134事件、361缺associated mark；同根 `stage-a-decision.md`记最后缺失2023-10-31T00:00:00.001Z。已有小时高低包络不能替代缺值。后段BCH S已消耗、D/H保留，不能救旧窗。BCH现货无需funding，现有OKX spot producer支持1Dutc，但它不属当前合约执行方向，未被选作下一实验。

**请求root的最小下一许可：只做DOGE S资金QC，不做Search或Candidate。** 在新Git外诊断根，用锁定ccxt/native公共接口及请求前identity/time护栏，最多3次实际HTTP GET（含失败）、10分钟、2MiB解码：exchangeInfo一次只输出DOGE身份/状态/USDT线性类别；fundingRate最多两页、每页最多1000，范围严格S，排他终点减1ms，零重试/重定向。不取D/H，不取价格K线，不输出funding/mark数值分布；保存原字节/SHA，报告身份、UTC序列、预计1092个8h事件、重复/缺失、associated mark是否全部正数。实际时间戳保留，按现有验证语义检查；非8h、缺mark或错误即NO_GO，不移动窗口。此诊断不能证明全来源就绪或流动性。

该3GET仅为数据诊断，不是新runner/source发布器。现有BCH捕获护栏会拒绝DOGE，不能冒用BCH Profile或关闭校验；若无法在该范围使用现有公共客户端做隔离诊断，停交最小差异，不暗改业务。QC通过后才另请root批准下一节窄适配和完整来源采集。H完整性此时仍UNKNOWN。

## 唯一规则与结构算术（供整体冻结）

建议family `closed_shock_confirmation_reversal_v1`，class `DogeConfirmedShockReversal3D`。令r[t]=C[t]/C[t-1]-1；流动性条件L[t]=前30个完整日的min(Low*base_volume)>=500000 USDT，且当日volume>0。L只是粗略历史交易额下限，250仓位/500000=0.05%，不是开盘深度或滑点证明。

- 原始多事件：r[t-1]<=-4%，r[t]>0，且C[t]<=0.98*C[t-2]，同时L[t]。原始空事件：r[t-1]>=4%，r[t]<0，且C[t]>=1.02*C[t-2]，同时L[t]。确认日仍保留相对冲击前收盘至少2%距离；不使用未来资金费或下一open作信号。
- E为任一原始事件且前3日都无原始事件。t收盘完成后，t+1 open按E方向入场；E.shift(3)在t+3收盘发双向退出信号，t+4 open正常退出，目标72h。去重对原始事件而非仅获准事件，防止重叠/退出冲突。资金费不参与信号。
- `minimal_roi={}`，`stoploss=-0.08`，startup35，can_short=True；仅三个populate方法和现有shift/rolling/min/算术/布尔形状。无trailing、自定义回调、加仓、资金调仓或参数网格。首评分前需要静态/纯合成因果检查，当前未生成源码或批准Candidate。

4%冲击排除日常微小波动、一天确认针对持续抛压/追涨、2%几何余量防止确认消耗全部回归空间、72h限制周转与funding；均为事前假设而非论文推荐或看值校准。下一open可能跳空吃掉余量，回归可完全不存在。相较即时逆转，确认会丢失快速反弹，也可能追进二次反向波动；固定退出不是保证持仓到期。

E0=1000，固定stake250，max_open_trades1，tradable_balance_ratio0.99；单次8%价损约初始钱包2%，跳空/费用另计。base每边0.001=手续费假设5bp+滑点/价差代理5bp，原生入/出各扣一次，不再重复外扣；H Stress倍率2（每边0.002）。无真实账户费率声明。funding用原生及 `BINANCE_ASSOCIATED_MARK_BOUNDARY_V1`较不利现金流/边界扣减，全进净额、PF、现金及小时close MTM DD；不改native原产物。

纯预算示例（非市场估计）：72h至多按10个边界付款事件做敏感性，若每事件1bp/5bp，则往返总成本约30bp/70bp名义仓位；base交易费20bp已含其中。18笔要赚钱包1%=10USDT，需要每笔平均净22.22bp，故所需平均价格毛利约52.22bp/92.22bp；2倍交易费并按5bp资金情景约112.22bp。资金率可能更高，实际按所有事件真实核算，不能把假设封顶。理论2%回归距离大于这些数，只证明值得证伪的空间，不证明alpha。

事件最短间距4日：S/D理论自然容量约91笔、H约50笔，考虑末端退出实际更低；达到18笔约需每20日一次、H10笔也约20日一次。自然信号、流动性通过率和方向数现在UNKNOWN；不足就是UNDERPOWERED，不增加高频变体救样本。

## 事前门、预算与现有链交付

核心Profile：S/D min_trades18，H/Stress10；PF>=1.10、原生DD及保守小时close MTM DD均<=10%，保守净收益率>=1%，现金全程可执行；average holding>=1440min、ROI退出0。额外自然有效样本S/D>=18且每方向>=6，H/Stress>=10且每方向>=3；每阶段至少3/4块有样本；去最大正保守净交易后剩余净额>0。正时长自然信号/止损成交才计样本，force_exit、liquidation和零分钟交易不计但盈亏全保留。PF缺失不能当零或自动通过。门是个人筛查的最低分散/风险缓冲，不是显著性证明。

三阶段各自同门过关才能继续，不能用S抵消D或H失败。每阶段额外报告价格毛利、fee拆分、native funding、附加扣减、方向/块/持仓、去最大赢家以及所有异常退出。原生小时extrema压力另列，不能冒充H Stress。没有自然样本或任一经济门失败即终结，无D/H；数据不完整为BLOCKED_DATA、技术失败为BLOCKED_TECHNICAL，不能混为经济负例。

**Search预算严格1基线、1轮、1次原生，R2=0，非两轮六次全额授权。** 不做增量消融或额外参数；因此只能检验整个确认回归假说，不能声称确认模块的因果收益已证实。无论正负都不在S重放。失败后先按价格毛利/费用/集中度/样本分类向root报告，本Issue不自动换币、换机制或换窗；以后改进需新独立窗口和新冻结。合法finalist后最多D1；D全门过后，同一Run授权H1+Stress1。全阶段实际原生上限4，后3次均需阶段授权。

最小业务差异仅 `lab/bounded_research.py`（BCH-only Profile校验）、`lab/binance_source.py`（请求/身份/路径/转换/档位与来源绑定）、`lab/futures_costs.py`（mark文件及symbol读取）。采用明确BCH/DOGE二项允许列表、从冻结Profile映射身份；保留1d/单仓/1x、原资金合同及所有失败前置。不增表/字段/索引/runner/native改动。相关定向合成测试需验证错误pair/混源/缺mark/非8h在副作用前失败、两币的source/audit一致；粗估3–6主动小时，超过上限或需要扩大合同即交回。当前只审阅未实施。

通过窄工程后再冻结source/Profile/代码和ledger：完整S+D来源预计763日价格/18312小时mark（含S35预热）、评分2184 funding；一次native capture，至多128 CCXT fetch、32MiB解码、30分钟、零自动重试，保存失败字节。不查市场PnL作QC。D只producer机械QC并物理分离，H不取；无法保留D隔离即停。后期H只有同Run资格及授权后才能采集，203日评分及35预热，funding609事件，沿现有H入口绑定。

现有新六表DB中：真实Profile→受控Generation→经静态/合成审阅批准Candidate→SINGLE_BASELINE Search，terminal/trials/artifact真实写 `generation_runs.response_json`，无finalist不造ResearchRun。额外门若没有正式字段就用现有JSON/审阅receipt绑定，在导入finalist前执行，不修改主字段冒充native；页面如实标原生/保守口径和UNKNOWN。S全门+root放行后才创建D ResearchRun；H/Stress使用同research_run_id，最后人工判定，Release/交易0。沿Console实际验证状态/禁用门，不新建UI或宣称FreqUI可用。

本轮实际新增市场请求0、Candidate0、Search0、D/H/Stress0；未写研究DB、未追加消费台账。交付一份提案，Issue98保持OPEN等待监督选择：先授权3GET数据QC，或拒绝该研究。文件完成不等于用户长期盈利目标完成。
