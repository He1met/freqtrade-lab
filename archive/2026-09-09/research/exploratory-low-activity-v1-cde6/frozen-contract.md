# 低成交活动条件反转 B：事前冻结合同 v1

状态：EXPLORATORY / NOT_INDEPENDENTLY_VALIDATED。唯一工程 Issue #69；A 是公共代码、测试与数据采集唯一写入者。B 只提交私有策略与准备证据。本合同在任何新行情与对方经济结果出现前冻结；不改旧 cohort，不生成 ResearchRun，不解封验证。

## 第 1 页：假设、数据与执行语义

依据：Bianchi / Babiak / Dickerson (2022), [Trading volume and liquidity provision in cryptocurrency markets](https://eprints.lancs.ac.uk/id/eprint/172093/)，作者接受稿 pp.4–9。论文主要是多币对、日频、横截面组合研究；相对历史量的 volume shock 与反转存在条件关系。本文将其外推到单个较高流动性 LINK perp 的 5m 时序过滤，既非复刻，也非净利润保证。OHLCV volume 仅称成交活动代理；它不识别订单方向、真实订单流或冲击。费用、逆向选择和持续趋势均可使假设失败。只用这一 primary 来源。

市场固定 OKX LINK/USDT:USDT，isolated linear futures，5m。探索窗口 **[2024-02-01T00:00Z, 2024-07-31T00:00Z)**；181 天、52,128 决策 K 线。采用 A 在获取新值前指出的资金费月档保护修正：不能为原 Aug1 截止下载 Aug raw 档。73 根 pre-roll 从 **2024-01-31T17:55Z** 起；完整 OHLCV 应为 52,201 行。共享原始资金费包可能含 Jan31 16Z–Jul31 16Z，其精确 envelope、保护性审计和 source SHA 由 A/监督验收，B 不自行下载。先前已公开终态的历史可降格为探索输入；仅物化不等于已见。未经确认或仍 sealed/reserved 的数据一律不读取。真实共享数据/source SHA 当前 UNKNOWN。

令 t 为刚关闭的 5m K 线（dataframe date 标记其开盘）。μ_t、s_t 为 close[t−71:t] 共 72 根，包含当前 closed bar，样本标准差 ddof=1；采用现有 qtpylib.bollinger_bands(close, window=72, stds=2)。完整 close 窗口须非缺失且正值，σ须大于0；库内 min_periods=1 不可绕过此完整窗口检查。成交量基准 vbar_t=mean(volume[t−72:t−1])，严格排除 t；历史72根和当前 volume 都须非缺失且大于0。最大静态 lookback/startup=73，价格统计窗口仍为6小时。

R1：close_t < μ_t−2s_t 做多；close_t > μ_t+2s_t 做空；不加低活动过滤。R2 唯一增量：两个入场各追加 volume_t < 0.5×vbar_t；等于0.5不入场。两份策略保留完全相同的指标、风险、退出与有效性检查。不能用 class literal 开关规避当前语义验证；请求 A 最小精确单因素验证 `entry_low_activity_filter_72_v1`。

退出：多单 close_t≥μ_t，空单 close_t≤μ_t；目标为同一72根方法在 t 重算的均值，并非入场时锁定价。退出要求完整正值价格窗口及当前正成交量。原生 Freqtrade 在下一根 open 执行入/退出信号；stop 可提前退出，期末仍持有由原生 force_exit 单列。持仓长度由信号/风险决定，不叫固定6小时；无固定持仓上限，无补单/加仓。ROI={} 关闭定时 ROI；stoploss=-0.02、默认 leverage=1、max_open_trades=1。不因前次止损禁掉后续有效信号，也不为了凑笔数强平。

## 第 2 页：成本、样本与终止

Profile 拟定 id=exploratory-low-activity-link-v1，family=low_activity_conditional_reversion。starting_balance=2000 USDT、fixed stake=400 USDT（20% 初始资金）、max_open_trades=1、taker_fee_rate=0.0005/side、max_drawdown_pct=15、min_profit_factor=1.10。2% stop 的价格风险约8 USDT=0.4%初始资金，另加成本；1x 不靠杠杆放大门槛。20%仓位保留结算余量，不声称该资金比例最优。Profile history_start_date=2024-01-31；窗口/pre-roll 由显式探索合同约束，不能以日级字段混淆精确 UTC。无独立 Development/holdout 日期；既有 min_development_trades 字段只承载本轮 Search 最小样本，不代表运行 Development。

最低成交笔数 **12/每个候选**。181天约724个非重叠6h块；仅作尺度估计，若正态双尾2σ约4.55%，约33次潜在偏离块，低活动假设保留1/4–1/2约8–16次。因此12是稀疏探索筛查门，非统计充分性证明；实际频率、聚集、持仓、有效独立样本均 UNKNOWN。该概率不是市场估计；bar信号不等于成交。两个候选统一门槛，低样本如实终止，不扩窗/换币/调参补数。

原生费用至少5bps/side，逐笔 funding 使用原生记录；缺失不得当0。实际滑点 UNKNOWN，原生 OHLCV 回测不能证明真实成交成本。冻结额外 **2bps/side** 的说明性成交冲击扣减（对实际 entry/exit notional 各扣0.0002），只做输出算术，不增加真实回测或修改原生指标，不当作滑点已证实。净门槛：native net>0且≥25USDT=初始wallet1.25%、PF≥1.10、peakDD≤15%；另报告扣减后净额是否仍≥25USDT。原生 PF/DD 不得冒称含该说明性扣减。

最低平均毛边际算术：N笔、每笔400USDT且出口名义金额近似相同时，为赚25USDT需平均净25/(400N)。N=12需52.08bps净，另约10bps双边费+4bps说明性冲击，即平均毛边际约66.08bps，尚需加实际平均 funding 成本；N=24约40.04bps。精确费用用原生fee_open/fee_close与实际notional核对，不能用此近似替代。funding可正可负；未知保持UNKNOWN。

R1 是必要旧均值回归对照，正面不意味着退役机制复活。R2 的新增净证据须同时满足：两者至少12笔；R2通过上述native门且扣减后净额≥25；R2原生净额及扣减后净额均严格高于R1。均笔收益、PF、DD、持仓及方向/月份分布并列呈现，不能只挑赢家；增量不足正常终止。即使通过也只构成探索候选，无独立验证或合格结论。

B 最多 R1/R2 共2次真实Search；A另2次，全批最多4次，同一探索池竞争假设，不是独立统计证据或已回测组合，PnL不能相加。两者规则事前独立冻结；禁止根据对方结果改方向。技术/数据失败保留，不经济重试。原生真实smoke并入R1，不额外试跑。工程门若因R1技术失败不允许R2，保留实际少于2次并报告；不能自制runner绕过。

本轮只做一次 T0纯AST+T1合成DataFrame检查，不跑真实行情backtest；source class与唯一过滤消融可供 A 精确匹配。执行前等待监督明确共享实现及数据验收，同步A已提交的精确commit，走真实Console/API Profile→Generation→Candidate→Search；独立SQLite/campaign/runtime/ledger。原生时序、费用/funding、页面尝试/终态及六表记录到执行时再验收；Search-only应有research_runs/backtest_executions/releases各0行。服务端实际Fast档位UNKNOWN，不改全局配置。
