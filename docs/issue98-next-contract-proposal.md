# Issue 98：合约研究提案与BCH/DOGE窄适配

2026-09-07。当前结果：**DOGE S资金QC通过，BCH/DOGE窄适配完成并通过92项定向合成测试**，等待监督核固定提交。完整行情来源、流动性和策略有效性仍UNKNOWN，尚非Search-ready。下文保留值前的确认回归提案与数据门设计；整体经济实验还未冻结。现货仅作为未来备选，未获本轮执行授权。

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

最小业务差异仅 `lab/bounded_research.py`（Profile校验）、`lab/binance_source.py`（请求/身份/路径/转换/档位与来源绑定）、`lab/futures_costs.py`（mark文件及symbol读取）。采用明确BCH/DOGE二项允许列表、从冻结Profile映射身份；保留1d/单仓/1x、原资金合同及所有失败前置。不增表/字段/索引/runner/native改动。此窄切片随后经root单独授权实施，实绩见末节；原3–6主动小时上限未用满。

通过窄工程后再冻结source/Profile/代码和ledger：完整S+D来源预计763日价格/18312小时mark（含S35预热）、评分2184 funding；一次native capture，至多128 CCXT fetch、32MiB解码、30分钟、零自动重试，保存失败字节。不查市场PnL作QC。D只producer机械QC并物理分离，H不取；无法保留D隔离即停。后期H只有同Run资格及授权后才能采集，203日评分及35预热，funding609事件，沿现有H入口绑定。

现有新六表DB中：真实Profile→受控Generation→经静态/合成审阅批准Candidate→SINGLE_BASELINE Search，terminal/trials/artifact真实写 `generation_runs.response_json`，无finalist不造ResearchRun。额外门若没有正式字段就用现有JSON/审阅receipt绑定，在导入finalist前执行，不修改主字段冒充native；页面如实标原生/保守口径和UNKNOWN。S全门+root放行后才创建D ResearchRun；H/Stress使用同research_run_id，最后人工判定，Release/交易0。沿Console实际验证状态/禁用门，不新建UI或宣称FreqUI可用。

初次提案时新增市场请求0、Candidate0、Search0、D/H/Stress0；未写研究DB、未追加消费台账。文件完成不等于用户长期盈利目标完成。

## 后续获准QC实绩

root随后仅授权上述3GET资金QC，未冻结整体实验或授权业务适配。2026-09-07T04:01:23.292219Z至04:01:23.725974Z完成：实际3次HTTP GET、1,242,829解码bytes、0重试/0重定向。DOGEUSDT身份TRADING/PERPETUAL/USDT线性；实际1092事件，首2023-11-06T00:00Z、末2024-11-03T16:00Z，严格递增；重复时间/重复分钟桶/缺失8h桶/额外桶/错币/非Regular/无效associated mark/非有限funding均0。状态 `FUNDING_CALENDAR_ASSOCIATED_MARK_QC_PASS_NOT_SOURCE_READY`。仅机器校验事件/有限性，不输出资金率或mark分布；OHLCV、D/H、Candidate、Search均0。未改三个业务模块。

证据根 `/Users/shenjianpeng/.codex/runs/freqtrade-lab/doge-funding-qc-bb9d-20260907`：`authorization.json`绑定事前协议和脚本SHA；`qc.py`、三个response/receipt、`utc-sequence.json`和`qc-report.json`保留原响应及时间。已重核响应bytes/SHA与脚本SHA。QC报告SHA256 `3ba2b453c7c1bd8cb396f055c9d525a42937152483adabf8ff8cba72316eab90`。资金S现在是QC已接触、不是从未读取；行情完整性/流动性/D/H及经济有效性仍UNKNOWN。已即时通知root，Issue98保持OPEN等待窄适配与完整冻结裁决；没有再次采集或经济实验。

## 窄适配工程交付

root验收QC后授权同Issue实施。唯一身份映射在 `futures_costs.binance_identity`；Profile确定pair后，capture的配置/argv/请求护栏、retained response身份、原生转换文件名、market/tier选择、source及审计mark路径全部使用该pair。不能因为BCH/DOGE都支持就让单cohort混币。未知pair在请求或文件输出前失败；来源identity/family/结算币、资金symbol、重复market快照、解析market、tiers均核对。`bounded_url`和`retained_responses`现在必须显式传入冻结pair，不能默认为旧BCH。

源码审阅覆盖 `fetch_binance_profile_data.py`（普通及授权H来源）、`bounded_research.py`（S/D来源准备与Search审计）、`research_candidate.py`（D/H/Stress artifact审计）、`holdout_run.py`（同Run续跑数据门）；后两者已通过现有helper传递冻结来源，无额外业务改动。lab/scripts中BCH字面量仅剩二品种映射。H资金receipt封存逻辑保持原样。

定向T0/T1：`test_binance_market.py`、`test_binance_source.py`、`test_binance_pair_binding.py`、`test_futures_costs.py`、`test_profile_holdout.py`，最终 **92 passed / 0 skipped / 6.70s**，76条pandas/pyarrow弃用告警。91项通过后，最终审阅补入H授权内部Profile与capture/compile外部Profile一致性拒绝及一项测试；同一定向范围复验92项，没有扩大到全套。完整命令/工具stdout保存为QC根 `engineering-tests-command.sh`、`engineering-tests-output.txt`，先前91项stdout为 `engineering-tests-91-output.txt`。Python3.13.13/ccxt4.5.68/pandas3.0.3/pyarrow25.0.0/Freqtrade2026.7已现场读取；使用锁定native Python/源码、临时六表DB及纯合成序列。真实converter、来源消费者、双向资金审计、BCH兼容、DOGE S/D及同Run后期授权HTTP入口均经过检查。捕获/native执行为桩，不是native smoke或策略回测。未跑367全套。首次测试71过15失败，均来自新fixture两日窗口不满足旧Profile容量；改为四日、最少2笔的明确合成来源合同后通过，实际研究Profile和业务容量门未改变。`git diff --check`通过。

依root明确授权，沿既有 `.jsonl.lock` + `flock` 追加唯一 `FUNDING_QC_ONLY` 控制记录，Search_consumed=false、无future reservation，OHLCV/D/H未接触。ledger从112022到113454bytes，旧前缀/空行完全保留；新SHA `af0a1c3287e1162995e40636471d395016d2e1301df64f310bdabf987b1c2af0`，追加记录SHA `a3520e42e751c61080179a55d280cd24280d154aef1b7de3aa471fbe9bf94f08`；QC根 `ledger-record.json` / `ledger-receipt.json`绑定授权与三响应SHA。

尚未新增完整行情请求、批准真实Candidate或Search。下一门由监督审核固定代码提交及完整协议，再决定S+D机械采集；不能把测试或funding QC当经济通过。Issue98维持OPEN。

预算执行缺口明确保留：提案128fetch/32MiB/30min比capture_native内建2000fetch/2GiB/7200s小，当前代码尚不会自动执行提案小预算，不能直接采集。最小后续办法是在现有capture函数增加只能收紧的三项运行限制，调用前冻结，guard在请求前计数拒绝第129次，SIGALRM设1800s；解码字节硬限还必须在sync/async接收流累计检查/截断失败并保留部分响应，不能仅在整响应之后计数而宣称32MiB硬限。不新增runner或策略试跑；这项预算修改本次未授权实施，需root先裁决，当前不采集。
