# Issue 139 — 时序动量机制与可行性固定草案

本包冻结研究设计，尚未获得执行准入。没有新行情读取、采集、native、DB 写入或 API 请求。Issue 137 / PR 138 的 API 路线保持暂停。本轮不建平台、不提交实现 PR。基线 main 为 `4934e1a0c2fecdc563f564a05921a53d264f2bec`；机器可读合同见 `docs/protocols/issue139-tsmom-draft-v1.json`，它不是现有 runner 可直接消费的协议。

## 机制卡与证据边界

唯一候选为 `return-sign-84`：已收盘价格相对 84 个日历日前的价格上涨则做多、下跌则做空。假说是信息逐步进入价格、趋势延续可能超过交易成本。它属于旧趋势同族；与旧 42/63/84 日突破的触发公式不同，不构成独立新经济机制。84 日是本次设计选择，约三个月；不是论文给出的加密最优参数，也不是根据旧 A-trend 正收益挑选。只保留一个候选，拒绝或保留，不做每币参数优选。

[Moskowitz、Ooi、Pedersen (2012), Time series momentum](https://fairmodel.econ.yale.edu/ec439/mosk.pdf)，JFE 104:228–250，DOI 10.1016/j.jfineco.2011.11.003：已读原文引言、数据和 §2.4–3.2。传统 58 个期货/远期品种存在自身收益延续；§3.2 以过去收益正负定方向，并以事前波动调整规模。这支持研究动量假说及因果波动估计，不证明 BTC/ETH、永续 funding、1000 USDT、84 日或本文止损规则有效。原文跨品种共同成分也不支持把 BTC 和 ETH 当作两份独立样本。

加密专属实证仍为 UNKNOWN：[NBER w24877](https://www.nber.org/papers/w24877) 和其 PDF 均返回工具 Internal Error。搜索摘要仅用于定位，没有将其当作已读正文或结果证据。

[Binance 官方 Exchange Information 文档](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information) 跳转到综合市场数据页；未从该页面核实具体 filters。[Freqtrade minimum stake 文档](https://www.freqtrade.io/en/stable/configuration/#minimum-trade-stake) 说明最低 stake 受最小数量、名义金额、reserve 和 stoploss 影响，工具可能自动上调 stake。因此本协议额外禁止自动凑单，必须在实际 adapter 验证不足最低值时拒单。

研究成本审计：Issue 创建前冻结 4 queries / 6 页面尝试。本轮用了全部 4 queries；先做 5 个原始/官方来源尝试（3 成功、2 失败），随后又展开已打开 PDF 和 Freqtrade 页面各一段。严格逐次 open 共 7 次，超限 1 次；不能宣称完全遵守检索预算，已停止检索并提交监督复核。没有下载或提交论文全文，未保留响应字节，内容 SHA 为 UNKNOWN；URL、读取结果和支持边界是本轮文献记录。

## 小资金执行和成本

用户条件：Binance BTCUSDT/ETHUSDT USDT 永续，1x，初始 1000 USDT；每边 fee 6bp + slip 6bp，往返至少 24bp，压力为 48bp，再计真实 signed funding。已知适用 fee 若更高，必须评分前提高并重新冻结；本轮没有账户费率证据。没有资金费事件关联 mark，不能填零或借附近 mark 替代。

仓库 `docs/issue117-exchange-metadata.json` 是 2026-09-07 的脱敏官方快照：BTC 最小数量/步长均 0.001，最小名义 50 USDT；ETH 数量/步长均 0.001，名义 20 USDT。它不是历史 filters，也不是实时账户可交易性证明。应按实际价格 P、lot step、native reserve/stop 参数算 `q_min = ceil(max(minQty, native_min_notional/P)/step)*step`。真实 P、ATR、native 参数绑定未读取/完成，因此实际 q_min、拒单率和 stop-risk 占用均 UNKNOWN。

A 每次初始止损风险最多净值 1%；B 每币最多 0.5%，总名义最多 80%、每币最多 40%（后两项为沿用旧资金框架的本次设计）。数量向下取整，`quantity * stop_distance` 不得超 cell；资金不足不能加杠杆、加本金、向上凑最小单。名义最小额小于 400 USDT 并不足以判定可执行。计入手续费、funding、滑点和 reserve 后再检查共享可用现金。20% DD 为硬风险失败线，10%减半、15%停止新风险；缺口可能越过硬线，不能承诺不会突破。

止损为入场 3*ATR20，最长 84 天；止损/到期后须等方向改变才再入场，避免靠反复强制重开制造自然样本。UTC 日线 close 才可产生信号，最早下一小时执行；不使用同一收盘成交。完整公式、退出优先级和 risk latch 见 JSON。

## 窗口与样本可行性

训练候选固定为 `[2021-01-01, 2023-01-01)`，warmup `[2020-04-02, 2021-01-01)`，只可探索。旧 Issue119 已有此来源登记，但不等于新协议登记或完整数据。已检查的旧 terminal 是 `BLOCKED_DATA / MISSING_ASSOCIATED_MARK_FIRST_BTC_FUNDING_PAGE`；BTC 小时结构通过并不能替代 funding，ETH 当时未采集。不能用旧 candidate 的 `NOT_REGISTERED` 状态覆盖后来的旧登记，也不能把旧登记当本轮准入。实际完整训练长度仍 UNKNOWN，后续先核对控制/来源合同及所有 continuation 收据，不直接重跑旧请求。

已暴露 `[2023-11-01, 2024-11-01)` 只披露为历史学习，本协议不另加一折。旧 sealed `[2024-11-01, 2025-01-01)` 和 10 个槽保持封存。旧 scope snapshot SHA 与当前 ledger 不同，必须针对新协议重做身份/依赖判定，不能照搬 PASS。历史裁定的 OKX SPOT 2021/2023 保护不自动升级为 Binance perp 全禁，也不让换交易所变成独立证据。全局 2025 年及 `[2026-05-31, 2026-07-31)`，BTC 2026 年 2 月、8 月等保护照旧；详细旧边界在绑定 snapshot，当前 ledger 是准入依据。

730 日训练最多只有 8 个完整 84 日块，达不到本次建议的 12 块门槛。因此训练最多产生待确认候选，不能给合格结论。新门采用至少 30 个**联合自然 episode**、至少 12 个完整 84 日块，并要求基准/压力成本后平均日现金损益的单侧 95% 下界均不小于零；30 并非充分条件，旧 Issue131 的 UNDERPOWERED 不变。这是保守设计建议，不是经过数据校准的功效保证。BTC/ETH 持仓时间重叠的 episode 合并，不能把小时、native 子交易、部分减仓或两币同期事件当独立样本。

统计采用事先固定的 moving-block bootstrap（84 日、10000 次、seed 139），同时报告 168 日敏感性；若长期依赖不受 84 日覆盖或有效样本不足，结果为 INCONCLUSIVE / UNDERPOWERED，不通过改变 block 长度找显著性。完整判据和集中度约束在 JSON。

前向仅提出 `[2026-10-01, 2029-10-01)` 的固定三年候选日历，**未准入**。273 日 warmup 可能碰旧保护，当前不能直接采集；监督必须先裁定合法的充分状态初始化，或在看到任何前向价格前换版确定更晚日历。若开始日前未完成候选冻结和合法依赖，不追溯登记。结束时不够样本就终止 UNDERPOWERED；没有自动延期、调参、调用或调度授权。低频研究可能需要多年，不能用训练赢家缩短独立确认。

## A / B / C 对照和逐调用预算

本切片 B 是**同一新信号在两币上的固定组合**，不是将旧趋势/反转收益拼接，也不声称跨机制分散。A-BTC、A-ETH 各以独立 1000 USDT 账户评估新信号；两者不能相加冒充 1000 USDT 组合。B/C/half-B 各自只有一个共享 1000 USDT wallet。C 只用一个闭市可知的波动减风险因子，永不超过 B；half-B 的固定半风险用于区分动态控制与简单减仓。B 是唯一事先选定的主候选，不能看到 C 更好后改主候选。C 相对 B 及 half-B 的增量须独立报告配对块下界，未通过不宣称改进。

每折 native 矩阵（每个组合单次调用同时包含两币）：

| mode | 资产 | base | stress | 合计 |
| --- | --- | ---: | ---: | ---: |
| A-BTC | BTC | 1 | 1 | 2 |
| A-ETH | ETH | 1 | 1 | 2 |
| B | BTC+ETH，共享钱包 | 1 | 1 | 2 |
| C | BTC+ETH，共享钱包 | 1 | 1 | 2 |
| half-B | BTC+ETH，共享钱包 | 1 | 1 | 2 |

训练一折 10，前向一折 10，最多 20；JSON 列出全部 20 个 key、资产、fold、cost，当前均未授权。先做确定性单机制最小单/成本/样本容量检查，再最多执行 4 个 A 调用；任一资产执行失败、压力净亏或风险失败，停止固定两币实验，不花余下组合调用，也不事后丢掉亏损资产拼赢家。

当前账本：28 RESERVED（25 SUCCEEDED、3 FAILED，另有2条 AUDIT_RECOVERED 事件，不是额外调用），28 个唯一 key。全球 `28 已占用 + 10 旧 sealed + 20 本草案待分配 + 38 未分配 = 96`。新技术重试为 0，失败占槽，不通过新名字恢复预算。本轮实际新增占槽/调用为 0。采集目前授权 requests/bytes 都是 0；下一切片必须给出独立请求量、体积、时限、重试及来源合同，不能沿用旧剩余85次自动请求。

## 最小下一步与交付检查

监督复核此固定包，首先裁定来源合同/训练池绑定和检索超限记录；若允许下一切片，先解决元数据准入和冻结采集预算，仍不直接 native。已有 `lab/portfolio_causal.py` 是突破信号，并硬绑定旧协议；return-sign-84 尚未实现。通过单机制可行性后才值得增加小 signal adapter 与协议绑定，复用经验证的成本/共享现金流语义。没有新增表、服务或 API 前置。

本轮检查 JSON 解析、20 key 唯一性及预算算术、引用文件 SHA、精确 diff；未跑市场或数据库测试。经济结果、实际样本、资金容量均未计算，JSON 保留 null。控制文件哈希在 JSON，发布 commit 和协议 SHA 由 Issue 评论绑定；Issue 保持开放，等待监督裁定。
