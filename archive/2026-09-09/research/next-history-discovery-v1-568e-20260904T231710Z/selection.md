# 下一项历史研究：有界发现结论

**NO_VIABLE_HYPOTHESIS_WITHIN_SCOPE。** 本轮三项比较均未达到可冻结执行的标准，不推荐创建新研究 Issue，也不推荐新增技术 Gate。交付状态为研究方案 **BLOCKED**；这不是三个机制普遍无效的证明，更不是全市场无策略。目标仍是 Search → 独立 Development → 用户另行授权的同一 research_run_id Holdout/Stress 合格策略。

当前 clean detached worktree 与实时 remote main 均为 `dc82c61fe8a27a654977344755c088412518d858`；native 2026.7 为 clean `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`。原 checkout 的未跟踪 `docs/product-requirements-v1.md` 保留。#67/#68 已实时核实 CLOSED；小收据中旧“OPEN，待验收”只是写作当时状态。#68 在原生 orderflow 完成前超过冻结 4 GiB，不能证明所有真实月档必失败，也不值得为弱一bar经济假设继续资源优化。本轮不恢复它。

| 机制及可能的付费后收入来源 | 新增信息、竞争解释与不利证据 | 本轮判定 |
|---|---|---|
| **慢速自身动量**：信息扩散迟缓、投资者追涨使趋势延续；较长持有减少单位时间费用。[Liu–Tsyvinski 2018/2021](https://www.nber.org/papers/w24877)确实报告 BTC/XRP/ETH 自身日/周收益预测。 | #49 已是 `close > high.rolling(20).max().shift(1)` 入、10日低点出；#52 已是 `sign(close/close.shift(28)-1)` 双向、R2仅SMA84同向过滤。新的均线/期限/币种不产生新的经济信息。论文的 attention 信息另需可因果获得的历史外部数据，不能用OHLCV换名。竞争解释为市场beta、单段泡沫或尾部补偿；论文不是当代单个OKX perp的净收益证明。 | **不选**：没有发现独立于这些研究的新预测条件。保留简单双均线明确退役边界；不把#49/#52负面外推为所有动量被证伪。 |
| **成交量条件的短期反转**：非信息性卖压迫使价格暂时让步，承接者赚取库存风险补偿；预期须超过费、滑点及逆向选择。[Bianchi等2022](https://eprints.lancs.ac.uk/id/eprint/172093/)研究2017-03至2022-03的美元交易对。 | 其强证据是横截面组合、低活跃/小/较不流动币种；低异常交易量条件不是“同一高流动性币发生大成交量冲击”。旧XRP已做阴线做多/阳线做空，R2要求 `volume > volume.rolling(20).max().shift(1)`，滞后一bar退出；#55已做5日反向符号及收紧stop。AVAX则是范围扩张、收在极端四分位的下一bar**顺势**，R2再加volume上升。把高量改低量是不同条件，但不能据横截面结果证明单资产净边际；竞争解释是信息性重估继续下跌。旧XRP已引用的[2026预印本](https://arxiv.org/html/2608.21888v1)本就报告短线毛优势低于其现货成本带，且承认选择/机制识别限制。 | **不选**：低量条件有可反驳差异，却不足以支持当前单个高流动性perp；不改投小币、延长几根bar或借旧文献重开退役XRP。OHLCV量只作活动代理，不称真实订单流/流动性。 |
| **固定交易时段内的动量**：区域交易者结束交易时减少库存，早段方向可能预示末段再平衡方向；拟检验每天至多一次、末半小时持有，信息来自时段关系。此持有法是研究构想，尚非核实后的论文完整复制。[Shen等2022](https://onlinelibrary.wiley.com/doi/10.1111/fire.12290)。 | 与全时段28日符号、AVAX一bar以及旧月初日历不同，具有可分辨的时段条件。但[作者稿§3.7](https://centaur.reading.ac.uk/100181/3/21Sep2021Bitcoin%20Intraday%20Time-Series%20Momentum.R2.pdf)的成本口径仍缺证，见下段。竞争解释为事后选高量开市时段、24小时市场没有真正收盘。[Wen等2022](https://www.sciencedirect.com/science/article/pii/S1062940822000833)的2013-03至2020-05单BTC时序结果也随跳跃、流动性、FOMC/COVID变化，且只展示筛选后的有效IS/OOS预测对。 | **不选：证据不足，不是已证明项目5bps/side下净亏损。** 时区/DST及AST另有缺口；不借杠杆救结果，不扫描时段。 |

共使用五项研究作品；派发的 `S1057521921002349` 页面本轮无法读取，未用其传闻结论排名。2018论文、2022论文和2026预印本的年代、现货/组合/单资产范围不互换；可预测性不是净利润，IS/OOS标签也不是本项目未消费验证。NBER与Shen精确完整原样本边界本轮未完整读取，保持 UNKNOWN。

**Shen成本补核（监督要求，追加2次定向检索+1次出版页取文，额度用尽）。** 可读§3.7索引正文把 `η(r_ONFH)`、`η(r_SLH)`、`η(r_ONFH,r_SLH)` 的全样本1x break-even依次写为3/7/10bps，并称在其Bitstamp 25bps例子下不盈利；但Table 8完整表注、费用函数、按单边/往返/portfolio扣费的分母均 **UNKNOWN**，25bps是否每边也 **UNKNOWN**。出版页full入口重定向到abstract，未取得全文，未绕过访问限制。已读时段说明选17:00 EST为末端；“最后半小时”算术对应16:30–17:00，但三个η各自的实际入退场、持有/空仓、换仓与成本函数没有核实，不能冒称与这个拟持有法相同；EST是否全年固定或随DST变化仍UNKNOWN。文中10x对应29/64/96bps的叙述不能证明其同步按notional扣费，相关处理 **UNKNOWN**。一般按名义金额收费时，杠杆L使毛收益与费用同时放大，简化净值贡献为 `L*(r-c_entry-c_exit)-融资负担`；这只是会计恒等式，不能指控或替论文补写公式。**25bps例子不证明本项目5bps/side亏损，3/7/10也不证明该费率盈利；本轮NO_VIABLE是支持证据不足。** 不再取文，不改机制/门槛/日历。

**执行边界已由代码确认。** `lab/bounded_research.py:541` 只构造单一linear futures pair；`validate_profile_runtime_contract` 限 `5m/1d`、无detail timeframe。`lab/research_candidate.py:109,493` 的config与exchange keys严格白名单，现有JSON不是任意功能开关。`lab/bounded_strategy.py:34,59,525` 限三个populate、固定OHLCV输入、有限rolling/shift；`.dt.hour`、`.dt.minute`、时区转换无合法表达式类型。时段从EST解释到America/New_York、是否DST、末根close及next-open需事前定义，不能用固定UTC偷换。5m闭合bar可表达小时lookback，不能因此改成1h标签。`lab/search_campaign.py:1243,1458` 的R2仅literal因素（含限定startup/rolling例外）及精确SMA84 entry-filter；任意volume/session增量尚不支持。native会把信号shift(1)，默认leverage=1，按实际持仓计算funding，但撮合不模拟滑点。

**未制造候选资格。** 没有推荐项，因此 R1/R2 source、三populate SHA、Profile、stop/ROI、窗口/pre-roll均为 `null / NOT_PROPOSED`，没有用未通过经济选择的草案凑两个源码。本轮AST/合成验证0次，代码修正0次；纯静态源码核对不是执行PASS。不需要业务改动或全量回归。若以后时段机制先取得可信的1x成本证据，其最小缺口是 `_expression_kind/_expression_lookback` 的限定时钟语义、对应生成模板和精确R2差异校验，另需DST/闭合信号合成验收；粗估1–2工程日含T0/T1及一项隔离原生合成T2，未bench、未授权、当前不推荐实施。实际Search耗时另外计算，不能再以G2代替研究。

**风险/容量门槛不能靠仓位包装。** 保留 net>0且≥1.25%初始wallet、PF≥1.10、峰值DD≤15%、leverage=1。固定名义stake占初始wallet比例为f、N笔完整Trade时，一阶门槛为平均仓位毛收益 ≥ `0.0125/(f*N) + 2*每边fee + 滑点 + 净资金费负担`。仅作算术：f=.25、N=180、每边5bps，需平均毛约12.78bps再加滑点/净funding；N=30则约26.67bps。这不是预期收益或冻结Profile，也不是当前实际费率查询。若stop为2%，f=.25的一次名义止损约占wallet .5%，但跳空不保证此上界；因此不能只增f以过PnL。持30分钟每天一次即使满180天，最多180个日事件，180×288根5m不是独立样本；time-in-market仅约2.08%，平均资金占用约f/48。原生Trade是一次完整仓位生命周期，止损/强平/重入不能人为制造独立重复。真实交易容量、有效样本、实际funding和滑点仍UNKNOWN。

**窗口结论：未找到可证明独立且完整的一套，未冻结/占用任何日期。** 已核对77行ledger SHA及三个小索引SHA，合并114条路径元数据；未重新打开底层行情。2020–2024有BTC/ETH训练及已消费/退役研究，2025有outer sealed；2019是旧v3 Dev提案/覆盖材料，不能擅自重标签，2018曾因覆盖失败。2023–2026另有#49/#52/#55/#61/#63–65跨币暴露及预留；2026-03不是可直接借用的空档（#45 H预留、旧coverage读取），4–6月有BTC→ETH，7月carry消费、8月Dev预留，XRP/AVAX7–8月已有曝光。跨资产同日历≠全球未见；索引外/更早历史为UNKNOWN，不能断言所有历史用尽。

LINK #66整包实际[2023-12-31 16:00:00.152Z,2024-01-31 15:59:59.729Z]已获取，非时间字段选中解释Jan30一天；#67整包实际[2026-06-07 16:00:00.985Z,June8 15:59:59.079Z]已获取，语义100行在June8 07:59:21.126–07:59:56.548Z。原Mar2024 Search/Apr Dev/May H与June15–July1 2026 Search/July Dev/Aug H都只是旧未授权提案，本轮未继承/占用；且它们存在跨币同日历曝光。Search/Dev/H/Stress/pre-roll均不指定；具体缺口是合法独立历史源范围、完整pre-roll与已批准新机制，不能靠挪窗解决。历史Search与未来validation应分开安排，但本轮没有合格机制，既不要求无故等未来，也不创造尚未闭合数据。

唯一交付建议是接受本次有界 **NO_VIABLE** 并终止本轮发现，等待监督的新派发。KEEP：成本、因果隔离、旧终态和六表边界；SIMPLIFY：在经济选择失败处结束，免去技术试验；DELETE：无实际删除；UNKNOWN：新机制净边际、可用独立窗口和真实容量。后续若另有具体获批方案，预算最多R1一次+唯一单因素R2一次；技术有效则完成事前R2，无合格finalist终止，唯一合法finalist最多一次独立Dev，H/Stress始终须用户另行授权。本文件不提供任何未来执行授权。

本轮始于2026-09-04 23:17:10Z，硬截止2026-09-05 00:02:10Z。输出仅本文件与小元数据；市场API0、新市场值读取0、真实backtest0、业务DB读写0、Issue/PR/业务代码修改0。模型/推理由监督确认gpt-6-astra/high；未选择Fast/priority或改全局设置，底层service tier未自查。核验证据与限制见 [selection-metadata.json](selection-metadata.json)。
