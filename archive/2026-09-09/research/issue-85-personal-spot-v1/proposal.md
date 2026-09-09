# 值前提案：WeeklySpotMomentum / 待监督核定

未冻结、未取得市场数值。唯一主假设：四周价格动量在下一周前四个持仓日具有可覆盖现货成本的延续性。UTC Monday 日K闭盘确认 close/close.shift(28)>1，下一根 Tuesday open 买入；Friday闭盘给退出，Saturday open卖出，正常96h；8%止损例外。固定周度评估和现金间隔限制换手，不要求所有周/月赚钱。

完整源码：同目录 strategies/WeeklySpotMomentum.py（29日pre-roll、ROI关闭、long-only）；取值前将绑定源码SHA、实际Generation/Candidate/Profile及本提案最终版本。

## 机制与选择

只比较两种机制，不增加备选参数扫描：
1. 价格延续。Moskowitz/Ooi/Pedersen 2012 的广泛期货长周期证据支持机制而不证明ETC四周/周度参数；Liu/Tsyvinski 2018 报告加密自身收益动量，资产仅BTC/XRP/ETH而非ETC。周度节奏和28天窗口是本轮事前假设，不声称论文验证本规则。选择它因为低换手可保留足够价格变动空间，并能用原生闭盘信号表达。
2. 短期反转。旧DOT小时机制的已知成本后负证据是设计线索，不能证明所有反转无效；本轮不再采用需高换手的短周期版本。没有第二个已预注册假设，主假设失败即本轮停止，剩余预算不自动启用。

来源：https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum 和 https://www.nber.org/papers/w24877 （官方摘要2026-09-06检索；前者12个月证据不是本轮28日参数证据）。

## 身份、窗口与预算

先前ADA提案被否决：Issue61明确ADA source[2024-02-01,2026-04-01)，真实S[2024-04-01,2025-04-01)已消费两次；D[2025-04-01,2026-04-01)已QC物化，H[2026-04-01,2026-05-01)封存。不能换spot重取。旧Issue元数据行筛选曾意外接触两个旧S费用聚合，仅披露一次，不据此调参，未读取D/H。

监督追加允许一次最多3资产资格筛选，事前顺序LTC→BCH→ETC。非收益理由：成熟原生PoW资产、无稳定币锚定、适配价格long/cash，资产选择无本轮行情或收益排名。LTC #63有2024-02-01至2025-02-01已消费S及后续D/H；BCH #64同S/D窗口且终态含DEVELOPMENT_REJECTED；均与拟用窗口相交，淘汰。ETC项目Issue搜索无命中，三个指定索引身份白名单（含literal flat data.instrument_id、data.pair、source及Profile pairs）无ETC命中，条件选择ETC/USDT / ETC-USDT SPOT。外部未登记暴露UNKNOWN，不能称全局未消费。ETC自2016存在的官方历史 https://www.ethereumclassic.org/knowledge/history/ 支持成熟资产理由；OKX具体listTime和完整日K覆盖仍UNKNOWN，获准后首个instrument/QC门验证，失败不换第四币。

ledger仍93行SHA5235fcc15cfab96cea6599993d8ba5a61b8f223e8c7f2d4e7e85409a71ae9240，另两索引SHA d69e27d426111083486fc3b771134380a9981f3f3a7b648fc2db837e5f4521f9、2e61cd2aec248aab2410584d603e073290b7293c5a3ee098de5ea74e0892994f。索引遗漏旧ADA/LTC/BCH已由旧Issue交叉核对补足，不回读旧经济结果。

S=[2024-01-01,2025-01-01)，D=[2025-01-01,2026-01-01)，H预留=[2026-01-01,2026-07-01)，Stress与H同窗，均SEALED_UNREAD且不采集。S pre-roll自2023-12-03，D只用此前29日作预热，不继承S仓位。D producer可QC但模型不读。每年约52周决策位，正常最多52次独立持仓区间；动量正方向实际覆盖未知。完整一年覆盖季节，最低18笔及9个有持仓月仅作为进入独立D的探索证据底线，不宣称统计充足；不足即UNDERPOWERED，不降门或复跑。

本轮主动真实S一次，SINGLE_BASELINE_V1；任何经济smoke计为该次。用户总上限3次，剩余2次不启用；不做参数变体。S核心失败终止。S通过全部外部证据门并获监督放行才D一次；D合格只称历史候选。H/Stress仍需用户另行授权。

## 成本与风险、预注册评价

E0=1000 USDT，固定每单250 USDT，一仓，原生spot、不借贷，仓位不是复利满仓。现金对照1000恒定；买入持有对照在评分段首bar open买入250 USDT并持到末端收盘卖出、剩750现金，同费/滑点。另报告100% B&H供上下文，不以跑赢上涨资产作为强制门。

原生taker每侧0.1%（研究假设，非用户账户费率或全历史保证）；依据OKX官方2026-09-03费用页常规示例0.08%/0.10%，其适用地区/账户条件有差异，不读取账户。https://www.okx.com/en-gb/help/what-are-the-new-trading-fees-for-eea-users 。正常滑点每侧5bps；固定成交路径扣除 open/close notional×0.0005。敏感性每侧fee0.2%+slip10bps。只重算同成交现金流，不另跑native；不能当真实执行影响上界。

S与D门：基础费用+滑点净收益严格>0；敏感性成本后净收益严格>0；原生账户DD及每日收盘现金+持仓市值的峰值相对DD均≤15%；完整非force_exit交易≥18且持仓月份≥9；异常成交（时序/越界/short/leverage/非有限费用/无来源）零容忍。15%是本轮研究风险预算：单仓25%资金×8%策略止损约2%E0名义单笔风险，允许连亏但拒绝严重资产路径风险，非用户实际风险偏好，跳空仍可能超预算。

集中度证据：最大盈利交易/正盈利交易合计≤35%，最大盈利季度/正盈利季度合计≤70%；移除最大盈利交易后基础成本净收益仍>0。报告每季结果和PF（Profile最低PF=1.0，仅辅助净收益门），不要求每季正。用52周账户收益、4周moving-block bootstrap、固定seed85/2000次报告95%区间与有效样本限制；S的CI只作诊断，其他硬门全过即可申请独立D，S不称统计合格。D必须CI下界严格>0才可称待H验证的历史候选，否则UNDERPOWERED终止，不因结果改变政策。

## 一次有限公开采集

现有CCXT下载接线，1次instrument请求；UTC日K760行左右，按现实现每页100行最多8页。每请求timeout30s，零自动重试，source总30min；无funding/mark/archive请求，失败分类NETWORK/DATA/CONTRACT并停止，不换币/根/窗口。必须先核raw UTC 1Dutc、confirm=1、分页精确序列、volume base单位、无重复/缺失/越界，来源raw与SHA保留Git外。首次身份不符或历史不足即BLOCKED_DATA；完整D只producerQC，无模型输出数值。

工程继续；请监督值前审阅策略、样本门/风险预算、条件身份与信息隔离。批准后才冻结及append ledger并启动真实采集。


## 修订后的固定计量细则

所有真实成交（包括force_exit）进入净收益、DD和集中度，18笔计数只排除force_exit；不删最后一单经济贡献。9活跃月按UTC持仓覆盖（当日任意时刻持仓，跨月各算），不按入场月份。最大盈利交易和季度分母分别为全部正交易利润和正季度利润和；无正分母即失败。去最大盈利交易只移除该交易完整含费用/滑点净贡献。

每日收盘权益=现金+未平仓数量×该UTC日close，已发生原生fees按成交收取，slippage在各entry/exit成交时按notional扣除；止损或force_exit同样记账。DD=max((此前含本日peak-equity)/peak)，另核原生账户DD；现金与B&H按同日网格对齐。周收益用相邻周末权益变化/固定E0=1000，非前周权益，统计量为平均每周E0收益。UTC周Monday00:00–nextMonday00:00；跨评分边界不完整周仍进入全部PnL/DD，但从bootstrap排除，只对完整日历周序列做重采样。2024与2025各完整周数由冻结日历算，不能机械称52。重采样连续4周移动块，有N-3个不环绕起点；固定numpy default_rng(85)，抽ceil(N/4)块并截N周，2000次均值，报告2.5/97.5分位（linear）。非独立周与有限样本限制照实保留，不把区间当保证。

周一/周五过滤是额外、未验证的执行节奏假设，不声称胜过连续28日long/cash。研究价值在于固定96h风险区间与周内现金边界，让一年有约52个清晰机会位，避免持续趋势只有少量长单的证据容量不足；代价是错过周末和额外进出成本。本轮不跑连续版本比较，不把这一工程方便性当经济优势，不试别的星期。

CCXT4.5.68本地源码已核：UTC默认将1D映射1Dutc，parse_ohlcv丢弃confirm，spot使用raw[5]base volume。producer已增加原始endpoint前后薄验证：精确instId/bar/before/after/limit，原始9字段confirm=1，恰好本页完整时间戳集合、parsed OHLCV等于raw数值、原raw响应保存在retrieval_receipt.requests[].raw_response并整体SHA绑定。最多8页（760条：29+366+365），每页最多100，不需额外哨兵；原始集合必须与期望集合完全相等，溢出或缺少都终止。只有通过spot标志和listTime≤2023-12-03的instrument才取K线；无身份历史保证即停止。

季度净利润固定按季度边界权益差计算，含未平仓市值及已收费用/滑点，与日/周权益一致。B&H的250 USDT为含entry费用/滑点的总现金支出预算：数量=250/(首bar open×(1+fee+slip))，末端按close扣exit费用/滑点，不另借手续费；100%对照也以1000总支出为上限。
