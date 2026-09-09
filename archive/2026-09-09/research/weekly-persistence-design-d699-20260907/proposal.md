# 周尺度持续动量：第一阶段研究设计提案

状态：`DESIGN_ONLY / CONDITIONAL_RESEARCH_PROPOSAL`。2026-09-07，执行任务 d699；监督任务 `01a05dcc-17fd-7972-9177-9fed95e4b07a` 决定下一门。本文不是数据就绪、Candidate、Search 授权或收益证据。建议只推进下面一条已知家族改进；不承诺找到盈利策略。

## 1. 已核事实及为什么这样选

本 worktree `/Users/shenjianpeng/.codex/worktrees/d699/freqtrade-lab` 无用户改动，处于 detached HEAD；HEAD 与 `git ls-remote origin refs/heads/main` 均为 `97b5e5dd45605655e25574e0d6948acee20aacd5`。Issue #104 实时 CLOSED（2026-09-07T07:00:58Z），不重开、不另建 Issue。

全局台账 `/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl` 当前 SHA-256 为 `8b6fb2c4141411da5f3d114ecb68800e27f868c9a0d2a3d0e2fe462da1cee2da`；133 物理行，其中历史空行保持原样。只读，无追加。

已消费 Search 的学习披露：BNB 现成 `final-delivery-receipt.json` / `search-protocol-review.json` 说明保守净 +44.5715 USDT、44 自然样本，但仅 2/4 正块、最大正块份额 72.1991%，完整协议 REJECTED。不能据此挑选其获利月份、延长那几笔交易或调回门槛。本次没有重新撮合。ADA 复合条件只留下 14 个容量样本，DOGE S 正而 D 负（交接与台账终态），说明条件叠加会牺牲样本，单期顺利也不会自动跨期成立。

旧家族去重（台账第 55–77 行及仓库 `docs/issue96-bch-trend28-negative.md`）：

- BTC/ETH 2024 absolute/relative momentum 当时报告回撤超过 20%，ETH 相对强弱增量增加周转并恶化收益/回撤；该 cohort 后续又被标记 `RETIRED_TECHNICAL_DRAWDOWN_INVALID`，经济结论不能继续当有效证据。2022 波动管理因切换和最终清仓覆盖已有现金而作废；2020 版本因回撤分母错误作废。技术作废不证明机制有负收益。
- 2020–2024 exploratory weekly SMA + ETH breadth 家族有效终态为回撤超过冻结 20% 门，breadth 虽减少部分回撤仍不合格；其参数、所有经济细节未从其他 runtime 追读，不能声称逐参数新颖。
- BCH 28/14 日线通道已自然持仓、并非固定 48h：只有 7 个有效自然交易，价格毛利 -13.25044 USDT，保守净 -42.21679 USDT，小时 MTM DD 25.2999%。因此“持有更久”已经出现过，不能当新优势。

最多三个设计比较，无市场试算：

| 方案 | 可证伪的依据与本项目问题 | 决定 |
|---|---|---|
| 周尺度持续时间序列动量 | 检验慢速信息扩散；固定每周判断上一周方向，方向不变继续持有。与旧通道的突破稀疏、与日冲击固定退出不同，但仍是动量家族。能否减少费用及适配风险必须本地验证 | 推荐一个版本 |
| 跨截面周动量 | 多币相对排序可减少单币特有冲击依赖；论文研究组合，不能用单币代替。目前 Profile/consumer/native handoff 强制单标的，忠实实现需要组合资金、来源和多仓合同，不是小补丁 | 本批不选 |
| 4h 冲击延续/回归 | 日内反应可能更快，但先前短持仓毛利被成本吞噬的教训仍在；没有证据证明四小时优于一天。更多决策不等于更多独立事件 | 不因想增加笔数而选 |

推荐版本具体改变：周频方向决策、取消固定持仓期限、允许负方向持有空仓位、以固定 25% 钱包名义仓位限制风险，并用小时 MTM 日历块评价。既不扫描周期，也不加 ETH breadth、波动筛选或幅度阈值。25% 是事前个人账户风险预算：8% 合约止损约对应 2% 钱包损失（未含跳空/费用），不是观察 XRP 后缩仓使 DD 过门；同时要求收益和基准比较，不能只缩仓过风险门。

## 2. 四个主要原始来源与适用差异

1. [Liu & Tsyvinski, Risks and Returns of Cryptocurrency](https://www.nber.org/papers/w24877)：作者原论文摘要确认 cryptocurrency time-series momentum。论文讨论 BTC、Ripple、ETH 的较早市场；这只支持方向假设，不能证明近年 Binance 永续、short 或每周 sign 规则有优势。全文访问遇到 403，仅使用能核实的摘要，不引用具体收益或声称复制了论文策略。
2. [Liu, Tsyvinski & Wu, Common Risk Factors in Cryptocurrency，作者机构原文](https://economics.yale.edu/sites/default/files/2022-10/LiuTsyvinskiWu2019%20COMMON%20RISK%20FACTORS.pdf)：2014–2018 多币、交易所聚合价格与周排序组合，研究市场/规模/动量共同因子。它也提醒换币未必提供独立 alpha。本项目单币、单交易所、真实双边成本和资金核算与其组合不同。
3. [Freqtrade backtesting 官方文档](https://docs.freqtrade.io/en/stable/backtesting/)：fee 双边应用，默认 candle 成交缺少真实滑点，exit signal 在下一根开盘执行。现有 2026.7 原生依赖仍须按冻结版本做无市场合成时序验证；当前 stable 网页不是该版本执行证明。
4. [Binance Funding Rate History 官方文档](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History)：fundingTime、fundingRate 及 associated mark 是实际资金成本合同所需字段，start/end 都为 inclusive。文档存在不证明某历史窗口完整，更不能用普通 mark 补缺失 associated mark。

## 3. 唯一版本、因果时序及现金

暂定研究名 `XRP_WEEKLY_PERSISTENT_DIRECTION_V1`，诚实标签 `KNOWN_MOMENTUM_FAMILY_IMPROVEMENT / CROSS_ASSET_LEARNING_DISCLOSED`。

代表标的建议 XRP/USDT:USDT：它在原论文的币种范围内，台账已有 XRP 合约研究身份，不按近期收益或波动选币。2022 原 XRP 窗口曾在数据 timestamp QC 阶段阻塞；这是数据失败，不是信号优劣。本案 2023 后的 Binance 合约身份、8h 完整资金日历、associated mark、历史精度/档位适用性仍 UNKNOWN，需下一阶段有限 metadata QC。选择 XRP 不表示目前已确认流动性或完整数据；失败不自动改成另一个币。

日线 UTC，周日那根 candle 完全收盘后，计算 `m = close / close.shift(7) - 1`。m>0 目标多，m<0 目标空，m=0 目标现金；只用该周日前已闭合数据。预热 14 根日线，日历固定 UTC 周，不用周中未来价格。1x isolated、起始 1000 USDT、固定 stake=250、max_open_trades=1，禁止复利加仓，stoploss=-0.08，minimal_roi={}。

周一开盘执行目标：空仓则开目标方向；方向相同则继续持有，不平仓/重开凑样本；方向相反则先平旧仓再开新方向；目标现金只平。周内仅允许保护止损，止损后等待下一个周决策，不周中追补。最后一日预定禁止新入场并按冻结评分边界清仓，boundary force_exit 计入经济值但不计自然完成样本。

**切换的合成前置门**：策略可用已支持的 `date.dt.tz_convert('UTC').dt.dayofweek` 与 shift 表达周信号；但已安装 native 2026.7 对同一根 candle“exit_long + enter_short”的真实顺序本阶段未执行验证。下一步先用纯合成 fixture 证明周日闭合→周一执行、旧仓 exit fee/funding 及现金释放→新仓 entry fee、同向无换手、止损不周中再入。如果原生同根反向不支持，不悄悄改为下周/次日再入或谎称等价：回报 root 这一模型保真缺口，重新决定设计，仍在新市场数据前。

现金复用 `BINANCE_ASSOCIATED_MARK_BOUNDARY_V1`：实际数量、进出价和双边费用对账，资金付款及边界不确定性按原保守合同处理，资金收款不提前抵扣尚未支付的保证金/手续费。逐时 cash>=0，无资金不足、liquidation、无限借款或丢掉旧现金；遇一项不成立即拒绝。

## 4. 窗口、暴露和资格口径

所有窗口 UTC、左闭右开，提案未认领：

| 阶段 | 建议窗口 | 已知暴露 |
|---|---|---|
| S | [2023-11-06,2024-11-04)，52周，startup 自2023-10-23 | 未见 XRP 本段直接 signal/PNL 台账；其它币同周期大量 Search 已消费，属于有跨资产学习的探索 |
| D | [2024-11-04,2025-11-03)，52周 | XRP 直接策略值未读；其它币 QC/保护及 DOGE D 消费、历史 BTC/ETH 信息均需披露。不能称全球行情未见 |
| H/Stress | [2025-11-03,2026-05-25)，29周，203日 | XRP 直接值未读，禁止现在采集/读取；本段别币已有 Search/D 经济暴露，不是完全无共同因子预知的验证 |

台账未发现 XRP 直接同窗记录不是统计独立的证明；未登记外部暴露 UNKNOWN。S/D/H 在 XRP 评分时间上互不重叠，指标预热可使用紧邻前期已知 candle，但不计入后期收益；跨边界仓位不带入，后期从现金开始。不得反向查看已存在别币 D/H 的值。全资产 UNKNOWN [2026-05-31,2026-07-31) 避开。XRP 旧 [2022-01-03,2022-07-01) S、2022 D，以及未来保护 H [2026-10-01,2027-04-01)、startup 2026-09-29 均不借用。

**关键资格限制**：推荐以上窗口只用于“新 XRP 资产级外样本检验”，保留 `NOT_INDEPENDENTLY_VALIDATED` 的跨资产研究标签。即使通过，不能用它证明完全独立的全球市场复制。若 root 的“真正合格”要求彻底无行情环境预知，这个历史方案不能完成该要求，需另冻结前瞻 cohort 和自然等待；不把旧 XRP 未来保护窗重新分配。现有入口 `H_start = D_end`，不能无说明把任意未来 H 拼接到旧 D。没有授权就不为绕过此约束写新 runner 或开缝隙接口。

## 5. 成本覆盖与样本预算

fee 配置每边 0.001，其中5bp手续费假设+5bp滑点/价差代理；一次往返约20bp名义本金，不声称是账户实收费率，不另外重复扣同一滑点。native actual funding 加既有保守边界扣减，原ZIP不修改。主价格毛利必须单列，不能用含funding的 `gross_profit_before_fees` 混称价差优势。

若价格变化不大，250 USDT一笔往返约0.50 USDT；持有7天有约21个8h事件。仅作算术情景：若每次支付1bp，则资金约0.525 USDT，毛价格需超过0.41%才到盈亏平衡；14天约0.62%。实际正负资金、数量与价格全部按事件算，不把1bp当观测值。要在12次这种周持仓上赚钱包1%（10 USDT），均笔约需0.743%毛优势；这是所需空间，不是预期收益。持续持仓节省重入费，同时累积资金成本，净效应 UNKNOWN。Stress 双边fee翻倍至0.002，资金源和边界合同不变。

1轮、1个交易策略版本、1次正式 native S，0自适应增量/child；本批不是最多6次的自动支出承诺。另预留1次同窗、同native入口的固定 250 USDT buy-and-hold long 诊断基准，非可晋级 Candidate，不得因基准赢了就切换策略；现金基准为0、无未授权利息。总S market-facing native预算2次（策略1+基准1），Generation只产生研究策略1个。D/H/Stress 每阶段只在对应门及root授权后各运行研究策略1次；同成本基准如需该阶段真实native结果也必须计数并事前列出，不能免费藏在“审计”里。本阶段均未执行。

每次采集/QC/信号容量、native、基准以及手工报告读取都按 exposure 写新receipt和将来授权后的原锁台账追加。全部代码、协议、来源/窗口/gate/hash 必须在首次新值前冻结。若策略先失败，基准诊断可以不花预算；不改币、阈值、方向、费率、窗口或样本门补救。

52周只有52次决策，最多约52次周期开仓（边界和信号零值会减少），H最多29次；实际自然交易数量 UNKNOWN。相邻周不是独立样本，同方向跨周继续持有只算一个方向 episode；止损后在同一连续目标方向内再入也合并为同一 episode，经济损失不删。均笔数、周块数、有效市场状态数分开报告。不因数据有364根日K而称有364次实验。

## 6. 待root采用后冻结的门

这些是此次设计提出的标准，不适用于追改旧批。S通过仅表示有理由开D；D通过才考虑一次性H/Stress。没有基于新XRP数据调整。

| 门 | S / D（各52周） | H / H Stress（各29周，同一窗口） |
|---|---|---|
| 保守净钱包收益 | >=1.0%，纯价格毛利>0 | H>=0.5%；Stress>0，纯价格毛利>0 |
| 保守PF / 原生及保守小时MTM DD | PF>=1.10；两DD均<=10% | 同左（Stress PF>1.0） |
| 自然完成 episode | >=12，正/负目标各>=4 | >=8，正/负各>=3；Stress不得把额外止损当独立新样本 |
| 持仓与活跃度 | 平均自然持有>=3天；有敞口周>=26 | 平均自然持有>=3天；有敞口周>=14 |
| 时间稳定性 | 4个固定13周块，>=3净MTM正，最大正块份额<=60% | 预先分14/15周两块，均为正 |
| 个别趋势依赖 | 去掉净利润最大完整方向episode后总净仍>0 | 同左 |
| 基础安全 | ROI退出0、cash可执行、无liquidation、全来源/成本/因果合同有效 | 同左 |

周块利润用含资金/费用的可清算小时MTM边界差，跨块持仓不重置，不用入场日期把几个月盈亏归到一个块。4块仍只有4个粗状态观测；episode是分群计数，不声称严格独立。报告所有自然episode持续时间、每方向次数、最长连续方向期、4块敞口，以及由相同冻结序列计算的4周块重采样90%均值区间（不拿bootstrap生成的新路径冒充新native证据，不据区间再调策略）。若区间跨0，必须把统计不确定性写在资格结论中。

基准按相同钱包/250初始名义金额、相同fee、funding和MTM口径比较，禁止拿全仓无成本持有与小仓策略直接排名。买入持有不重平衡，长期数量会随价格漂移；差异如实报告。事前附加价值门：策略 `net / max(MTM_DD,1%)` 必须不低于同成本buy-and-hold该比值；现金门已由净正覆盖。这是风险收益比较，不保证机制alpha。若native基准未跑则标UNKNOWN，不能越过完整评审。不要要求“52个独立周”取代上述episode与跨期证据。

## 7. 最小工程、真实入库与时间

可复用：六业务表、CODEX Generation/Candidate、Profile参数化门、SINGLE_BASELINE_V1、官方 Binance capture/source/audit、Search和拒绝附件、matched PASSED review 的D handoff、H同run封存/Stress与Console。Search结果仍归 generation_runs，未通过不造ResearchRun；全部后期结果同一个research_run_id。实际页面必须显示原生结果和完整协议判决、失败门、D/H状态；基准作为明确诊断报告展示，不冒充已导入的ResearchRun或FreqUI。

已证明的唯一产品代码缺口是 XRP pair identity allowlist：`lab/futures_costs.py:22` 目前只列 BCH/DOGE/ADA/BNB。沿用前次pair绑定模式增加XRP，合成 wrong-pair/receipt拒绝测试；不加表字段索引、不建服务/runner。预计30–60分钟主动实现和重点验证。周信号AST、同根反向、方向episode/周MTM报告与基准调用还需要30–60分钟无市场合成证明和runtime文稿/脚本准备；这是研究实现与核算准备，不宣称产品代码已支持全部特殊规则。若同根反向不成立或真实基准无法沿用官方入口，先回root，不能“只需一个pair补丁”带病上线。

4h若以后另选：需要同时核改 `bounded_strategy` timeframe白名单、`bounded_research`步长/1d限制、`research_candidate`源与timeframe合同、`binance_source`URL interval/下载/保留响应/Feather元数据，以及相应页面/consumer binding；sql timeframe是TEXT，未发现必须改schema。保守估计2–4小时主动实现/合成核验，来源6倍日K但小时mark成本仍在。这里只列最小改动范围，无代码变更，无证据保证经济收益。

下一门建议：root先决定是否接受“有跨资产学习的历史S/D/H”资格边界及这一个周动量版本；若接受，授权一次纯合成时序/基准调用验证及最多5个单日资金metadata检查（S起点、D起点、H起点、H中点、H末日，只输出结构/日历/associated-mark完整性，H费率值不展示）。完整OHLCV、Generation、DB写、正式Search分别等root放行；若任何源失败，`BLOCKED_DATA`，不放宽合同或自动再采。以历史成功为前提的完整策略资格仍UNKNOWN。

预计后续主动研究准备约1–2小时，有限metadata约数分钟至30分钟；完整采集/计算等待依交易所限流约10–120分钟，遇418/429保存失败证据。历史D/H无需自然时间等待，但全局无预知的前瞻证明有不可压缩的日历等待，不能给“今天必找到真正合格策略”的期限。

本阶段仅新增此Git外设计文稿；未采集/probe/读取新候选信号或保护窗市场值，未Generation、Candidate审批、native、DB写、代码修改、Issue创建或子agent。
