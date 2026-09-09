# G：本轮不提交新的 Search（只读规划终态）

**NO_GO_WITHIN_CURRENT_SCOPE；提案 0、Search 0/2。** 比较下述两项机制后，没有一项同时满足经济增量、现有单币原生链路和短工程预算。结论仅限本轮两个候选，不是所有策略无效，也不完成“找到合格策略”的总目标。

当前 clean detached HEAD 与两次 `git ls-remote origin refs/heads/main` 均为 `a0a6229dd75724e5cbd2f892eac0b8ebcb8b6e14`；本任务无活动 Issue、无代码修改。F 的指定 summary/result-audit SHA 均匹配监督提供值。R1/R2 价格毛额分别 −10.8455/−22.1864 USDT，额外成本后净额 −36.75201682/−31.02043944；R2 是 R1 的19笔子集，省费没有创造正价格边际。本任务只读公开汇总，没有复算底层行情。F 已终止，不重跑、不改门。[F 汇总](/Users/shenjianpeng/.codex/runs/freqtrade-lab/lagged-funding-search-v1-f915-20260905T021839Z/summary.md)

| 本轮仅比较两项 | 机械机制及唯一增量 | 本轮判断 |
|---|---|---|
| 横截面相对强弱 | 每周用已闭合过去一周收益对当时可交易资产排序，做多最高组、做空最低组，固定总敞口和周再平衡。增量是资产间相对排名，不是单币上涨。 | 有研究价值；不能用换币后的单币 SMA 冒充。历史可交易池、退市和同步多币输入未证，当前单币 Profile/runner 不接收组合。超出本任务多腿边界，**不选**。 |
| 波动率管理 | 月末由当月日收益计算已实现方差，下一月把原有方向仓位乘以 `c / RV²`；c须仅由预先训练期确定，可另事前定义上限。增量是风险暴露时机，不额外预测方向。 | 不是 #65 双均线的同一机制，不能因旧趋势失败永久封禁。但论文的股票因子证据不能直接证明 LINK 单币资金费后净优势；当前不接收缩放/调仓回调，五个月池也无法可靠检验月级风险收益。**不选**。 |

实际阅读三份论文正文，未只读摘要（页码均 PDF 页，1起算）：

- [Liu、Tsyvinski、Wu，2019作者稿](https://cowles.yale.edu/sites/default/files/2022-10/LiuTsyvinskiWu2019%20COMMON%20RISK%20FACTORS.pdf)：pp.5–6 数据、11–12 动量、16–17 因子构造。2014–2018，Coinmarketcap共1707币，市值≥100万美元，含存续/失效币；周度市值加权分组，1–4周相对动量有支持，所测8/16/50/100周不显著。所读回报表未提供手续费、借币或永续 funding 扣减；不是OKX可执行净值。作者脚注明说选3周因样本价差最大，不能把它当无选择偏差的固定最优参数。本报告没有照抄该最优值。
- [Moreira、Muir，2016-04-06作者稿](https://conference.nber.org/confer/2016/LTAMs16/Moreira_Muir.pdf)：pp.6–9 构造，19–20及47成本。美国股票因子主要1926–2015，部分因子更晚；另含外汇carry。按前月日收益方差缩放次月仓位。表8对市场组合的权重变化计1/10/14bps成本，未研究原始因子全部交易成本，亦无加密 funding。全文尺度常数按全样本等波动选择；实际研究必须预先估计。成本优势是该样本证据，不能外推LINK盈利。
- [Cederburg等，2020作者提供刊稿](https://www.lehigh.edu/~xuy219/research/COWY.pdf)：pp.4–5 数据，12–14 实时组合与表5。103个美国股票策略，各自起点不同（最早1926），截至2016-12；初始120个月、扩展窗估计后检验。市场组合样本外Sharpe 0.42，对照0.46；MOM/ROE/BAB有正证据，故不是全盘否定波动率管理。所读表并未证明加密执行费用后回报；其120个月设计也不是本项目必须照搬的期限。

当前入口与成本核查：

`lab/bounded_research.py:177,563,618`、`bounded_strategy.py:22–68`、`codex_generation.py:510–558`共同限定 **5m/1d、单币、固定 Profile stake、3个populate**；4h不支持。静态lookback≤512，允许正shift和rolling mean/min/max；方差可用乘法和均值构造，缺口不是简单加一个std函数。资产排名需要别的资产输入；动态仓位需要新增受限契约。`search_campaign.py:1482–1505`仅有几个明确单因素分支与字面值变化，不能把任意新filter当合法R2。`lagged_funding.py:1–95`为完整AST匹配模板，不是通用DataProvider授权。

[Freqtrade 2026.7 官方原生接口](https://raw.githubusercontent.com/freqtrade/freqtrade/2026.7/freqtrade/strategy/interface.py)确有 `custom_stake_amount` 和 `adjust_trade_position`；[同版本 backtesting](https://raw.githubusercontent.com/freqtrade/freqtrade/2026.7/freqtrade/optimize/backtesting.py)确会调用仓位回调、按上一根信号执行并核算持仓funding。项目 `scripts/run_freqtrade_backtest.py:37–44,842–865`固定2026.7/commit/dependencies及单币配置。**是项目入口未接线，不是原生引擎没有能力。** 最小波动率方案仍需固定回调模板、Generation绑定、R2唯一仓位变化校验，以及月界/最小仓位/费用/funding合成原生检查；本轮没有证据承诺全部1–3h完成，不建议为此立工程。只修改指标或增加止盈不保留原机制。

每个买卖腿成交额为Q，费5bps＋额外2bps，则总扣减 `0.0007 × Σ|Q_leg|`；真实signed funding另记，实际滑点UNKNOWN。近似每笔双边400 USDT，每个完整往返先需0.56 USDT，即**14bps价格毛额减去funding净收入**才能打平。若另事前要求全窗净25 USDT，N笔所需均笔毛额是 `14 + 625/N − 平均funding收入bps`：N=5需139bps，N=20需45.25bps。25只是沿用F门的算术示例，**不是本轮冻结判据**。低换手减少总费用，不能凭空提高每次方向判断；月持仓还累积更多funding。动态规模必须用实际notional，不许拿400固定近似作最终账。

若以后独立提出可执行版本，R1须是相同调仓时钟、相同可交易池/方向、固定事前资本分配的基线，R2只改排名或仓位中的一个；现金净收益按0建模，另报告买入持有方向暴露及其真实funding。闭合后next-open，两轮共同计边界费用；现金/被动比较用同一输入会计诊断，不另藏第三次Search。波动率管理须在相同风险预算下检验净收益/效用增量并报告敞口；不能只以DD下降通过。横截面须有匹配资产池的被动篮子，单币上涨不能代替排名贡献。源码、成本、机会定义、经济/样本门和两次上限均应在取新值前定；本轮不填写虚构交易数、功效或合格概率。

数据与停止：LINK `[2024-02-01,2024-07-31)`仍是已见探索池；A/B/F已公布至少6次原生尝试，外部累计次数未完整审计。新family/cohort不恢复独立性。[E窗口审计](</Users/shenjianpeng/Documents/freqtrade-lab-local/window-independence-audit-20260905T015929Z/window-decision.md>)的LINK `[2024-08-01,2024-10-31)`仍仅B级候选；funding实物完整性/as-of UNKNOWN。已见预热只作因果输入；已暴露funding raw截至Jul31 16Z以及未来月包尾部必须保留接触记录。SOL备选未选择，BTC/XRP封存不泛化。91日不是月级风险管理充分验证，也没有通用180日/40笔要求。真正后续Dev须先核明确接触史、独立窗口及预注册样本单位；失败/不足/数据阻塞结束版本，不扩窗补考，Holdout继续单独封存。

**下一步：向监督交回本轮 NO_GO，保留0/2使用记录；不启动工程、取数或回测。** 两候选在当前范围止步。重新考虑需新的具体可执行机制/证据或用户明确改变研究范围，不能只把上表标题再换币/周期提交。本轮未改repo、DB、global ledger、模型设置、网络设置或GitHub；未读Dev/H/新行情，未生成Candidate。完整输入SHA与阅读范围见同目录metadata。
