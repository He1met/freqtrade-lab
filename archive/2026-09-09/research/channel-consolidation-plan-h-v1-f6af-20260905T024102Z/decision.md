# 盘整后的日线突破：条件性提案，未找到合格策略
**建议仅进入 1–3 小时窄接线验收；不进入真实 Search。** 当前 main/干净工作树均为 `a0a6229dd75724e5cbd2f892eac0b8ebcb8b6e14`。本轮无业务修改、DB/ledger 写入、Candidate、回测或新市场值读取。只写本私有目录；完整规则与门见 `metadata.json`，两份完整源与可重跑合成探针随附。

## 第 1 页：差异、固定规则、实际能力
**唯一假设：突破前的窄区间能提高突破后的价格边际。** 旧 AVAX 是当根振幅超过上一根、极端收盘及放量，BTC lagged pressure 是相对过去 48 小时的冲击与 signed range-volume；均非先有窄通道。#65 简单双均线退役继续有效。更近的 [#49](https://github.com/He1met/freqtrade-lab/issues/49) 已检验 BTC long-only high20/low10 突破、R2 只改止损；监督补充其唯一 Dev 失败。本次不把突破、改周期或改 stop 叫新发现，也不声称已全面排除所有未登记的同类试验。已有结果只作已见参考；不能跨窗口/方向/成本复用其 trades。新 R1 唯一用途是给 R2 提供同窗同规则消融，不额外重跑旧 20/10，更不借 R1 复活旧 cohort。

[Hudson/Urquhart](https://link.springer.com/article/10.1007/s10479-019-03357-1) 已实际读 §§2、3、6.5 与附录 CB：日线现货价格，最早 BTC 2010/2012、LTC 2013、XRP 2013、ETH 2015，样本截止 2017-12；14,919 条规则存在选择风险。CB 先要求窄区间，区别于普通支撑阻力突破。2018 上半年最优规则的两种 BTC 样本外结果为负，其余币并非全负。本文只提供可证伪动机；没有证明现代 OKX perp 扣 signed funding 后盈利，未抄最优参数。

| 冻结前提案 | 两轮共同规则 |
|---|---|
| 市场/风险 | BTC/USDT:USDT，OKX isolated perp，1d，long+short，1x，单仓；wallet 2000/stake 400 USDT；ROI={}；stop=-8%。双向是对称突破假设，非依据 F 做空结果挑方向。8% stop 名义风险约 32 USDT/1.6% 初始钱包，加费用及跳空风险。 |
| 通道/信号 | U/L 为此前 **28 根 close** 的 max/min，均 shift(1)；close>U 做多、close<L 做空，等于边界不触发。28 日是四周状态尺度；14 日对侧退出是半尺度失效判断，非参数搜索。 |
| R2 唯一增量 | 在每侧原 entry mask 末尾增加 **此前 28 根 close 的 max/min ≤1.10**。10% 是事前价格压缩定义，不表示当前突破已有 10% 可赚空间。当前突破 bar 绝不进入窄幅判断。 |
| 退出/有效性 | long 遇 close<此前14根close最低值退出；short 对称。止损可早退；无恒真 exit/固定持有承诺。两轮共同29根正 close/正 volume guard；producer 必须先验证全部 OHLCV 有限、正价、OHLC一致与 UTC 连续，缺失禁止填零。 |
| 时序 | 标记 D 00Z 的日线到 D+1 00Z 才闭合，信号在 D+1 next-open 成交。state signal 可在止损后下次有效信号重入；原生允许符合条件的反向退出/翻仓，不强行将两轮成交配成子集。 |

这是一项改编：close 边界、单次闭合确认与对侧退出不同于论文 c%-偏移边界、持续 d 日及固定 k 日规则，**不是论文复现**。[Freqtrade 官方假设](https://www.freqtrade.io/en/stable/backtesting/#assumptions-made-by-backtesting) 与本地 2026.7 源码确认信号 shift(1)、next-open；日线蜡烛内 stop/成交顺序仍是模型假定，真实滑点 UNKNOWN。

**实际入口结果：** 两源 bounded+生成输出解析 PASS，lookback/startup=29，AST 节点380/458；窄/宽区间双向、边界相等、NaN、零量、追加未来不改变既往信号等合成检查通过。正式 `_single_factor_change=False`；现有 `_single_entry_conjunct_change=True`，改 exit/stop/阈值/lookback/shift/只改一侧六个负例全拒绝。缺口仅新增命名分派，精确匹配两侧固定完整表达式、移除后全 AST 相等；配 unit/API 拒绝测试及源 SHA 绑定，勿扩大 AST/DataProvider/schema/runner。当前生成提示已支持逐字冻结源。正式 Search 已显式 allow_zero_trades；report_metrics 保留零交易 holding/direction=NULL，finalist 样本/经济门拒绝，**无需零交易修复**。尚未证明 native 合成成交或真实 consumer 通过。

## 第 2 页：窗口、经济门、唯一下一门
**metadata-only 选择 BTC 探索 [2022-04-01,2024-08-31)，883 日，原生裁掉首根信号移位后最多882个 next-open 决策槽。** 29 日 pre-roll 从 Mar3 2022；预计 futures912、mark21888、funding2649 行（不是实物验收）。旧训练 protocol/2022–2024 retrieval receipts 确认 BTC/ETH **spot** 已见；#49 Search/Dev 已执行，故全部降为 EXPLORATION，不称独立。spot 元数据不能证明 perp/mark 已可用。官方 BTC funding Apr2022–Aug2024 所需29月及March先导月目录全部 HTTP200/code0；一次429后节流复查成功，未下载ZIP。实际拟取29月原始包预期包络 [2022-03-31 16Z,2024-08-31 16Z)，边界/漂移/完整网格 UNKNOWN；按 timestamp-first 原生合同验证，禁止补零或改时间救援。终点留出尾部至 Sep1 之前，保留 #49 BTC Sep2024 H、#52 ETH Oct2024 H、2025 outer 及其他原封存；旧 spot 接触不撤销这些保护。BTC选择基于既有长历史与原生单市场可执行性，非论文最优收益。外部未登记暴露 UNKNOWN。LINK 91日独立候选不足以承载此月级检验，未采用。

**监督本轮值前收敛，旧研究合同不变。** R1/R2 自身共同硬门：total≥24，native与每腿额外2bps后净额均≥25 USDT（1.25% wallet），native PF≥1.10、DD≤15%、ROI exits=0，实际holding非NULL；Economic Gate最低平均持仓设0。24笔是约每37日一笔的有界探索样本底线，不是已知可达数量或统计功效保证。原草案的平均持仓≥7日、每侧≥6、12个28日格/6季度，均改为必报诊断：这些追加数字缺少功效依据，与成本/样本门重复，止损早退也不是自动失败。覆盖不足、单方向集中或单笔主导要明确标风险，不能冒充稳健。

R2 除自身硬门外，native与附加成本净額均须严格高于R1，且每单位入场notional的**价格毛收益**严格高于R1。价格毛收益剔除funding和费用；少交易省费不足以证明增量。现金0、400 USDT初始名义本金全窗被动多/空、等平均signed quantity-time被动永续仅作预注册归因诊断，使用同批数据、真实signed funding和逐腿费用，不新增基准框架或硬门。完整必报价格/funding/fee/净额、PF/DD、持仓、月份/方向/28日覆盖、最大单笔贡献、每日配对净差及过滤机会；额外成本诊断不新增回测。R2未过增量门不能说盘整成功；R1若自身通过，可保留基线候选，但不能翻案#49或跳过全新独立Dev。原生finalist投影也不等同附加增量门已通过。

每边fee≥5bps，signed funding由native实际持仓计入；每腿另扣0.0002×实际成交notional。若24笔、约400每笔，25净额需要约26.04bps/笔净边际，加基础10bps+额外4bps约40.04bps毛边际，再考虑实际funding；不是收益预测。额外PF/回撤须单列并说明重算口径，不能把原生值称为已加冲击。

**唯一下一安全门：监督在新任务验收窄分派补丁+本冻结合同及精确暴露绑定，1–3h上限。** 验收应含 native纯合成 next-open/stop/反向信号与两侧 AST 拒绝，不触碰市场值；任何超范围需求停止。通过后才另行授权原生 source/consumer 验货及最多2次探索（预计2–4活跃小时、数据下载约10–45分钟/两次回测约5–20分钟，均非承诺）。真实smoke算R1；R1技术有效即R2（零交易亦有效但不足），无第三次。数据/技术失败或总样本不足按合同停止；R2经济或增量失败结束盘整假设，不换币/扩窗/调参。合格R1或R2仅为已见历史候选：独立历史Dev窗仍UNKNOWN，须另做metadata验收并冻结一次足够长Dev；本轮不创建前向待跑。H/Stress继续单独授权，六表保持，累计选择风险不会因新family消失。
