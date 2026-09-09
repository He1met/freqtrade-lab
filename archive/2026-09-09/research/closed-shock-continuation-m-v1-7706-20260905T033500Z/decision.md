# M：已闭合冲击后的短时延续——唯一值前协议

**结论：CONDITIONAL_GO_FOR_BOUNDED_SEARCH_V1；NOT_EXECUTED，真实 native 0/2。** 机制值得一次有限证伪，现有 Search→同 Profile Development 接口原则上可承载，业务代码新增 scope 为零。不是盈利证据；不是数据或 Holdout 就绪。当前阶段完成后交监督审定，未授权采集、Generation、Candidate、Search 或后段执行。

## 已核现场与文献边界

- worktree `/Users/shenjianpeng/.codex/worktrees/7706/freqtrade-lab`，干净 detached HEAD `0ace04b7c10ea35fb8ce6f25e043ac78be87c19e`；本次 `git ls-remote` 证实远端 main 同 SHA，非仅查看旧 tracking ref。原用户 checkout 未改动。
- native Freqtrade `2026.7`，指定目录干净，HEAD `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`。本任务未创建 Issue；只读最新 Issue 列表、#74 与 #66 正文。#76 已关闭，只看状态，不读 K 的原始行情/回测结果。当前无 M Issue 是阶段边界，不冒用旧 Issue 执行。
- 已完整读项目 AGENTS、`freqtrade-research-audit/SKILL.md` 及两份引用。memory 只作入口线索，执行约束已从现代码重核。

核验的主文献为 [Caporale / Plastun, CESifo WP7917, October 2019](https://www.ifo.de/DocDL/cesifo1_wp7917.pdf)，读取正文方法、交易规则、结果表和结论（PDF 页 4–12）。其日收益使用 close/open；k 因样本数选取，日内时点从样本估计，CAR 的正常收益用全样本。完整日冲击标签到收盘才确定，因此其同日结果不能直接证明可提前交易。下一日时序较可信，但币种/方向异质，且未扣成本。摘要/结论写 2017 起，方法写 2015 起。它只提供弱动机，不提供本协议参数或预期收益。

最多补查的一篇是 [Shen / Urquhart / Wang, Bitcoin intraday time series momentum](https://onlinelibrary.wiley.com/doi/10.1111/fire.12290)。期刊全文入口回到摘要，作者机构 PDF 被拒绝访问；仅确认书目信息，不把摘要结论当作已经核实的机制或成本证据。到此停止文献扩展。

## 唯一机制与可推翻预测

推断：一次已闭合、方向明确的大幅小时价格变动，可能含尚未完成的同向订单拆分或分散参与者的迟缓反应，之后数小时仍有同向需求；若冲击结束后的半小时仍同向，需求可能更持久。OHLCV 不能识别真实订单拆分或信息到达，本协议检验的是其价格预测，不宣称已识别微观因果。

R1 检验冲击后等待半小时，再在最多 3 小时内持有同向仓位。R2 只检验等待期间的同向价格变化是否增加信息。反证包括：之后纯价格毛额不正、确认后的毛额/notional 不提高、费用或 funding 吃掉效果、增量只来自少交易省费用、效果仅集中在极少周、样本不足。任一相应失败结束本版本，不调阈值、换币、改持仓、去 funding 或延长窗口救援。

本机制是小时事件后的同向延续；K 是 28 日通道/盘整，L 是冲击后的反向回归且带均价偏离。这里没有通道、均价偏离、低量或 funding 信号。L 的两文件 SHA 已核；未打开它的交易/市场结果，也未将它的负结论外推到全部反转。

## 冻结源码与因果时序

| 项目 | 唯一冻结值 |
|---|---|
| Family / Profile ID | `closed_shock_continuation_m_v1` / `link-closed-shock-continuation-m-v1`；分别已过 MECHANISM_ID / SAFE_ID |
| 市场 | OKX `LINK-USDT-SWAP`，`LINK/USDT:USDT`，linear perpetual，isolated，5m，单币 |
| 冲击 | 每个整点结束的完整 1 小时 open→close 回报；>= +1% 做多，<= -1% 做空；不按确认后的价格重判冲击 |
| 等待 | R1、R2 均等待同样 30 分钟；每小时只在 :25 开始、:30 闭合的 5m 行判定入场 |
| R1 | 信号行 t：`close.shift(6) / open.shift(17) - 1`，并且该行 `volume > 0`；后者只是两者共有的数据有效性条件，不是流动性证明 |
| R2 唯一增量 | 多头追加 `(close / open.shift(5) - 1) > 0`，空头追加 `< 0`；零变化不通过。factor=`session_pre_entry_agreement_v1` |
| 仓位 | 初始虚拟余额 1000 USDT；固定 stake 100 USDT；max_open_trades=1；原生默认 leverage=1；不加仓、不复利调整 stake |
| 退出 | `minimal_roi = {"180": -1.0}`；从真实 entry 起算 180 分钟；stoploss=-0.02；无自定义方法、无普通正 ROI、无 exit_signal |
| 资源 | 三 populate；startup=18；静态最大 lookback=18；pre-roll=18 根5m。现有时钟仅 NY 链，取 minute 与 UTC minute 相同，不选美股时段/工作日 |

**具体例子（UTC，蜡烛用开盘时间标记）：** t=02:25，闭合时点 02:30。冲击使用 t−17=01:00 的 open 与 t−6=01:55 的 close，即 `[01:00,02:00)`；这个事件及方向在 02:00 已知。确认用 t−5=02:00 的 open 和 t=02:25 的 close，即 `[02:00,02:30)`；不与冲击重叠。两者最早在下一根 02:30 open 入场；正常到时退出是 05:30 open，绝非从 01:00 起算。R1 在 02:00 不进场。定义的是固定小时区间达到门槛的事件，不是事后寻找日内最佳首次穿越点；相邻小时可分别满足门槛，持仓中信号按 native 规则忽略，不增仓、不重置 180 分钟。

1% 是值前粗粒度的绝对冲击门槛，约为基准 14 bps 往返假设的七倍；并不推断冲击有任何固定比例会延续。1h/30m/3h 是对快速延迟反应的单一有限尺度假设，不是论文估计值、统计最优值或参数网格。30m 确认可能错过已完成的延续；这正是 R2 可失败的经济代价。

R1 SHA-256：`b247857ef2051b2542808703aa3bede8915853d2aec10227cf77aff50b948258`

R2 SHA-256：`32722442a9cbd73bb03874d5755e8621cb53aa36894c60477641c859b3298305`

两文件仅为 **PROPOSED**，不是 Generation/Candidate。全源码 AST 在剥去 R2 两处精确 conjunct 和类名差别后相同。实际 Generation 必须绑定并核对这两份全文 SHA；任何偏离在 native 前失败，不临场接受近似实现。

## 成本与成交证据

费率固定每边 0.0005，即 5 bps taker 假设；未来实际公开费率/合约语义不满足时停，不接触账户/VIP 凭据。基准附加成本每边 2 bps，压力每边 5 bps；另冻结 stress_fee_multiplier=2。费用不通过改源码/抬 ROI 实现。

从原生交易导出的**实际 base amount 和入/出场 notional**计算：`E=Σ(q*entry)`，`X=Σ(q*exit)`，`G=Σ(direction*q*(exit-entry))`，`F=Σ(native signed funding_fees)`（正数是收入），`N=G+F−0.0005*(E+X)`，`N2bps=N−0.0002*(E+X)`，`N5bps=N−0.0005*(E+X)`。先核 N 与 native profit_abs 在精度内一致；不一致/缺失 quantity、单位、funding 或费用时是技术/会计阻塞，不补零。实际 fill amount 可能受精度、最小下单额或余额影响，不用固定100乘笔数代替 E。

100 USDT 入场、100 USDT 出场、无价格变化且无 funding 的合成例：费用0.10，额外成本0.04，合计损失0.14 USDT；5 bps附加时合计0.20。若实际 funding 为 −0.03，则基准损失0.17。1%冲击本身不是这笔未来收入。盈亏平衡必须 `G > 0.0007*(E+X)−F`；不能假定零 funding 或拿 funding 收入伪称价格延续。

所有提前止损、跳空止损、窗口末 force_exit 照常保留交易和全部成本，不删除负交易。合成/native方法检查证明180分钟门和开盘价规则；不证明深度、排队、盘口、真实滑点或 stop 可按报价成交。2/5bps 是情景扣减，未观察真实滑点；历史 OHLCV 通过仍是 `EXECUTION_COST_ASSUMPTION_UNVERIFIED`。未来若有直接执行证据超出成本假设，应停止资格推进。

## 唯一窗口与接触资格

| 角色 | UTC 左闭右开 | 天数 | 5m pre-roll起点 / mark起点 |
|---|---|---:|---|
| Search | `[2024-08-01,2025-01-31)` | 183 | Jul31 2024 22:30 / 22:00 |
| sameProfile Development | `[2025-01-31,2025-07-31)` | 181 | Jan30 2025 22:30 / 22:00 |
| Holdout / Stress 候选 | `[2025-07-31,2026-01-31)` | 184 | Jul30 2025 22:30 / 22:00 |

选择约半年的理由是本机制按小时检测、预期事件率未知且可能成簇，需要多个日历月及约26个周块检验分布，91天只有约13周。不是为旧60d/30d界面过门，也不依据市场值选起止。这里没有预计成交数；小时决策槽或原生容量上界均不是样本数。窗口不滚动延长至通过。

E 的 `window-decision.md`/metadata 仅支持 LINK Aug–Oct2024 是 **B级候选**；本次更长三段的资格全部是 **B_CANDIDATE / external_contact UNKNOWN**，不能把其结论外推成 A。已按 whitelist 检查 global ledger 当前81行元信息，未打印其 metrics/results。LINK Feb–Jul2024探索已消费，#66保留的Mar–May2024窗口与本方案不重叠；#66 January2024整包诊断、#67 June7–8 2026不重叠。S pre-roll Jul31 22:30 晚于已报告 LINK funding 旧包暴露右界 Jul31 16Z，但这个判断依赖监督/E接触记录；尚未完成全部任务的接触对账。

保留原资产/协议保护：旧SOL Jan2024含pre-roll、K全部SOL S/D/H、BTC49 Sep2024 H、ETH52 Oct2024 H、BTC/ETH2025 outer、ADA61 Apr2026、XRP62与LINK66原保留均不释放。BTC/ETH同期曾作训练，不能称全加密市场盲测；也没有证据把其日期自动扩成所有其他币种禁区。未读取任何这些保护行情。

**接触四层（本 M 当前所有新窗口均未发生）：** (1) 原始父数据/压缩包物理获取，(2) producer自动时间/连续性/内容QC，(3) Agent语义读值或图表/结果，(4) 用于设计/择模。历史其他任务的(1)–(4)不完整，均保留 UNKNOWN；不以没有ledger记录当未见证明。

现有 acquisition 会一次取 S+D，D可由producer机械QC且保持Agent/择模 SEALED_UNREAD。计划 raw funding 月包为 Aug2024–Jul2025，包络预计 `[2024-07-31 16Z,2025-07-31 16Z)`，精确实物及毫秒漂移尚 UNKNOWN。D尾包可能物理含 H开始后费率字节；现解析器在解读 rate 前按 `[start,end)` 排除。必须留存物理字节接触/哈希和 skipped行时间元信息，明确不把它叫“从未获取”；H价格/费率数值、图表、指标和结果不能进入Agent或择模。若窗口外 rate 被语义解释或打印，保持污染并停止原 H独立性主张，不偷偷换窗。H pre-roll可复用D已见历史，仅热身不评分。

OHLCV/mark官方可用性与funding目录是E的历史证据，较长区间目录和实物未在本任务刷新。执行前核精确合约、费率假设、全部月份、来源序列、UTC闭合/连续性、8h funding网格及允许<=2000ms向下归网格；变频/缺数据/超漂移失败，不插值、不拼来源。

## 冻结样本门、经济门与退出决策

预算只含 R1 一次和 R2 一次，**真实 native 累计最多2次（包括真实smoke、失败调用和重跑）**；当前0。先R1，后唯一既定R2，不根据R1选参数。任何实质技术失败停止余下经济执行；无同窗补考。两次之后本协议终止；Development/H/Stress只是预先指定的后续验证路径，各自执行需监督另行放行和明确新阶段预算，绝不暗含在0/2内已经批准。

实际样本单位是 native成交事件，信息分布按**从各窗口起点每7个UTC日一个固定周块**记，尾部不足7日并入最后块。逐笔按 entry UTC 归周块，该笔全部G、funding、费用与附加成本都归同一entry周，不按exit周拆分。同一持仓内多信号不增样本；邻近小时/同日相关，不按5m行数或订单数计算有效独立样本。S/D/H均约26周。

固定最低覆盖门：每个被考虑的源码至少52笔实际完成交易、其中多/空各至少13笔、至少20个周块有成交。52是“约26周平均至少两事件”的覆盖底线，20周要求不只靠少数冲击簇；13/方向要求至少跨若干双周机会，均不是功效证明。实际事件率、收益方差、有效独立样本 UNKNOWN；若仅达计数仍不能声称统计显著或已知胜率。额外集中度门：删去该策略N2bps最高的一个完整周块，同分取最早周；删除后G与N2bps仍须严格正（只对导出交易做汇总，不新增回测）。这是预注册粗筛，不是统计功效或周间独立证明；后续相同策略D/H不能调门。

项目原生 Profile门固定：min_development_trades=52，min_holdout_trades=52，min_profit_factor=1.10，max_drawdown_pct=5.0，费后净收益严格正。不启用旧 `maximum_roi_exit_count=0` 限制：这里 ROI 是明确的180分钟到时退出。逐笔 duration 必须0..180分钟，0分钟仅可解释为原生入场bar止损；提前正ROI/持仓被反复信号续期等不符协议行为失败。

协议额外门是监督对原生结果的只读否决门，不篡改 engine terminal：

1. R1或R2自身需 G>0、N2bps>0、N5bps>0，且通过上述覆盖/集中度门与原生Profile门。所有不等式严格正，不四舍五入成通过。
2. 若要选R2，除自身通过，必须 `G2>G1`、`G2/E2>G1/E1`、`N2bps_2>N2bps_1`、`N2bps_2/E2>N2bps_1/E1`，并且R1/R2使用相同完整S与成本。共同周块按 `ΔN2bps=N2bps_2−N2bps_1` 排序，删去ΔN2bps最大的同一周，同分取最早周；删除后同时考察剩余 `G2−G1` 与 `N2bps_2−N2bps_1`仍严格正。该删除规则也是预注册粗筛，不是统计功效。E缺失/为零则增量不可判定。这样“少交易省手续费”不能单独支持确认机制。
3. R2的信号mask是R1子集，但max_open_trades=1会改变之后可成交机会，执行交易未必逐笔子集；按共同日历周/全窗配对，不能只挑两者共同盈利交易比较。
4. 原生排名保持现有净收益/回撤/PF/id顺序。只审该 native terminal选出的候选；若其协议额外门失败，记录 `PROTOCOL_REJECTED_NATIVE_FINALIST` 并停止，不改写原生finalist、不从其余候选手工递补、不自动创建D。若native无finalist保持真实 `SEARCH_TERMINATED_NO_FINALIST`。只有同一候选原生与协议均过才交监督批准D。
5. 计数或分布不足为 `UNDERPOWERED_NO_EVIDENCE`；有充分覆盖而价格/净额/增量失败为本机制经济否决。样本不足不宣称机制普遍无效。两者均不延窗/调参救援。

经济分解/周块只是现有原生交易 artifact 的只读评估，不能产生或替代数据库ResearchRun；无需新runner、schema或自动judge。S不是最终检验，D及一次性H/Stress仍是独立阶段，不承诺盈利概率或期望收益。

## 当前验证与唯一下一门

62项纯合成断言通过，含两方向确认通过/拒绝、全序列vs前缀、未来扰动不改历史、两个entry同一next-open原生移位、strict-R2拒绝漂移、ID正则、native Resolver的 `ignore_roi_if_entry_signal=False`、179分钟无ROI、180分钟亏损/零/盈利都到时、仍有entry信号不抑制ROI、原生到时使用open、14bps成本算术。没有运行 Backtesting.backtest，没有创建数据库、Source、Generation、Candidate、ResearchRun、ledger行或GitHub写入。该微型检查不覆盖完整资金费/订单生命周期/force_exit集成；不再追加全生命周期合成测试，后续若获授权，唯一真实R1同时承担集成证据，失败也计入2次累计上限并停止。

当前代码可验证 `5m + lookback18 + fixed stake + strict factor`；Profile窗口每段<=366日，所选S/D在界内。正式链使用现有生成/审批→`/api/search-campaigns`→合法finalist绑定→sameProfile Development；不是外部JSON冒充DB研究。精确源码生成、源绑定、会计字段和运行时默认必须在真实native前核验。

H/Stress仍有已核代码缺口：`lab/holdout_run.py`调用 `_validate_data_provenance`未传Profile且构建legacy字段；`lab/bounded_research.py::_validate_strict_window`仍有60d/30d路径。因此本任务**不声称全闭环现成**。只有真实候选和D通过后，再另行授权最小Profile后段接线；不为了旧入口将当前181d/184d缩短。

下一门只有：监督审定此唯一协议/双SHA，并对LINK三段完成已知任务的接触/保护元信息对账；若资格可接受，另行授权一项明确Issue与限定采集、临时私有研究DB、精确Generation和2次Search预算。目录/数据/长窗目录缺失按真实可用性停止，普通配置由任务处理，无需用户逐个提供。**当前不能跳过监督放行；阻塞是尚未确认的接触/数据资格及阶段授权，不是论文还不够多。**
