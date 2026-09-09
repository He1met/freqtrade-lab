# Q：期现价差的可交易预测含义

本轮结论：**NO_GO_CURRENT_NATIVE**。这是本研究自定义的提案状态，意思是当前不提交 native 实验，不是“basis 无效”或“单腿必亏”的经济判决。保留的缺口名为 **DIRECTIONAL_EDGE_SPECIFICATION_GAP**：原始定价正文已读，但“哪一种价差、预测哪条腿、哪个期限的真实净收益”还未获得足够清楚的原始证据。没有新策略参数、源码或 Search 资格。

## 当前状态与范围

- 工作树 `/Users/shenjianpeng/.codex/worktrees/a9c2/freqtrade-lab`，detached HEAD `0ace04b7c10ea35fb8ce6f25e043ac78be87c19e`；开始时 `git status --short` 为空，`git ls-remote origin refs/heads/main` 返回同一 SHA。无 active Issue，未写 GitHub。
- 指定 native 静态源码 HEAD 已核 `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`。2026.7 为委托指定版本；本轮以 commit 为绑定依据，没有执行 native。
- 全局 fast 设置沿用监督提供的已核信息；本 session 实际服务档位未回传，标为 `NOT_RETURNED`，没有另造 wrapper 或修改模型配置。
- 无新市场数值获取，无本地行情、mark、funding、spot 源文件或 DB 读取，无 Generation、Candidate、native 回测、ledger/GitHub/业务代码写入。旧诊断的意外暴露单独记录于下文，不能据此声称“未见任何旧结果”。

## 旧合同究竟声称什么

已读全部旧合同定义：`/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/basis-funding-search-202607-v1/contract.json`，SHA-256 `7b45f7bcb7f7f120219697a5c953c6f4b31a736014ed9da0472aa9aeac3e5328`。

旧合同是等量 spot long + perp short，不借现货、永续 1 倍杠杆。基线要求正 basis 大于预设完整往返成本；唯一增量是上次已结算 funding 为正。最少跨一次结算，之后基差收敛退出，最长 24 小时。它的收益目标是价差变化与持有期间的实际 funding 现金流扣成本，不是“高价差预测 BTC 下跌”。因此更换为单腿空头会更换经济合同，不能称旧策略等价简化。

ledger 84 行 SHA-256 `96aa9ce415690f8e8efd97caeab4ce9dadf75ecb1b5fe5a52dfe9b479b331edd` 已核。行 44–47 标示从 accounting gate 到旧 cohort，最终状态为 `RETIRED_TECHNICAL_CAUSALITY_UNPROVEN`。精确 correction 文件 `/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/basis-funding-search-202607-v1-correction/correction-receipt.json` SHA-256 `15baa15db67e8cf5a455efd00403a54e555470991288f28d6bbb1e3178a1ad2e` 已核，仅投影授权字段：

1. 历史 settled funding 被赋予 `settled_at + 1 second` 可得时间，源证据并未证明这个历史公开时间。
2. 运行准入资金检查使用整个 Search 月的最高现货/永续开盘价。

`economic_claim_valid=false`，`root_replay_allowed=false`。这两个技术缺陷不能反证 carry 的经济原理；也不允许修补旧 root 后重放已消费窗口。

## 两篇原始来源：读到了什么

| 来源 | 本轮阅读程度 | 可支持的判断与限制 |
|---|---|---|
| Ackerer、Hugonnier、Jermann，*Perpetual Futures Pricing*，arXiv v2，2024-09-04，https://arxiv.org/html/2310.11771v2 | 实际读到 HTML 正文 §1–3、§9，以及 Appendix B 相关段落；核对 §3 式 (8)–(10)、Theorem 1。未声称完整读完全部证明。 | 无套利现金流须同时含价格变化及 funding；其条件期望使用风险中性测度 Q。这不是实际测度 P 下的方向 alpha。永续没有固定到期约束，不能套用交割日必然收敛。 |
| Schmeling、Schrimpf、Todorov，*Crypto Carry*，BIS WP1087 / Management Science DOI 10.1287/mnsc.2024.05069 | BIS 官方摘要/介绍与搜索索引中的一段正文可见；PDF web 获取超时，直接下载返回 404。换到一次期刊官方来源，其 PDF 链接仍跳回摘要。没有可交付 PDF，没有读到预测章节、完整表或回归设定。 | 官方介绍给出杠杆需求、套利资本受限及 carry 与未来 crash risk 的线索。不能声称已核实单腿净收益预测、期限、回归控制、交易成本或样本外表现。正文片段只涉及 carry 交易空头腿的风险，不足以替代预测章节。 |

来源链接：[原作者定价正文](https://arxiv.org/html/2310.11771v2)、[BIS 官方介绍](https://www.bis.org/publ/work1087.htm)、[期刊官方摘要](https://pubsonline.informs.org/doi/10.1287/mnsc.2024.05069)。搜索中的其他论文未进入阅读证据，没有继续扩展综述。检索偶然呈现的论文历史汇总数值不用于本地选币、窗口或参数。

## 新收益主张与必要区分

真正不同于旧 carry 合同的可证伪主张应为：**在事前固定的持仓期限 h 内，同一资产/同类可比决策时点，高拥挤价差条件下，单腿永续空头的实际净期望收益为正，且高于去掉价差信息的基线。** 两个条件都需满足；只有较高 crash 概率、較低长期持有收益或較小亏损不足以达到目标。

相对 OHLC，价差提供的是杠杆需求/受限套利资本的信息。相对旧 carry 合同，basis 原始观测本身并非新增；新增的是它对未来单腿条件净收益的预测主张，本轮未证明这是可独立准入的合格 family。不能把旧 funding 数值改名当新增信息。原作者的交割期货 carry 与永续瞬时 premium 不能不经论证互换，年化交割 basis 必须保留到期日/期限。BIS 的主要资产不能直接换成某个未看过的 altcoin，以回避既有 BTC/ETH 窗口保护。

对等量线性仓位 q，设 B=F-S：

`hedged PnL = q*(B_entry-B_exit) + funding_received - spot/perp costs - financing/capital costs`

`short-perp PnL = q*(F_entry-F_exit) + funding_received - perp costs`

这两个式子不等价。若价差缩小完全由 spot 上涨实现，空头未必赚钱；spot 与 perp 一起上涨也可伴随价差收敛。风险溢价还可能使更高风险对应更高平均价格收益。已结算 funding 可以成为历史特征，但结算后才进入的仓位拿不到过去那笔钱；未来 funding 的符号与金额必须按持仓后的实际事件结算。

无行情的内存 Decimal 检查共四项通过（仅代数反例，不是研究收益）：(1) S/F 从 100/102 到 110/110，basis 收敛而空头价格损益为 -8、双腿为 +2；(2) 结算后进入无过去 funding 权利；(3) Q 下预期价格上涨 1 可以恰好抵消 funding 支出 1；(4) 95% 概率涨 2%、5% 概率跌 20% 的假想分布仍有正的多头平均收益。第四项只说明尾部概率不能确定均值，不估计任何市场概率。

## 因果时间、费用与最小对照

首次可成交必须在全部输入真实可得之后：`decision >= max(closed_at, published_at, received_at)`；执行选择严格晚于 decision 的 native candle open。按 5m 粒度，若收盘后才收到数据，不能假装成交在同一边界，最早是之后的 5m open。若采用额外一根 embargo，则再后移一根；必须事前固定，不用补造 `+1 second` 可得时间。

native 源码 `optimize/backtesting.py:555–564` 将信号后移一根；这只能解决引擎消费信号的排列，不能证明外部输入历史可得。`strategy/interface.py:1711–1727` 仍以收益是否超过 ROI 阈值决定 ROI 退出；普通正 ROI 不能保证亏损时到期平仓。需要明确、已获支持的持仓时钟/强制退出表达，不能以普通 ROI 伪造固定 h。

持仓尺度应由方向预测证据决定。旧 24h 是旧双腿合同边界，不能继承给新方向交易；5m 只能是执行粒度，不能作为经济预测尺度。当前未核得 BIS 的预测期限与腿别，因此 h 留空，不伪造 8h、1d 或月度参数。

费用是否允许有限实验有意义：**UNKNOWN，尚无幅度与期限足以计算 break-even**。旧合同的假设为现货每次 10bps、perp 每次 5bps、每次滑点 2bps，据此四次成交约 38bps/单腿名义本金；单腿 perp 往返约 14bps，均不含未来 funding 或融资。这只是旧合同假设的算术，不是当前账户费率或实测滑点。双腿总资本分母还含 spot 支出与 perp 保证金，不能把每腿名义收益误报为总资本收益。日到周级低换手方向效应在原理上可能覆盖交易成本，但本轮不据此声称够用。

存在正当的“基线 + 唯一增量”结构：同一预注册日历、资产、持仓 h 的周期性单腿空头为基线；增量只加事前可得的高价差条件，现金记为现金，保留完全相同的退出/成本。还须按全部日历区间评价组合净收益，区分筛选事件条件收益与少持仓造成的风险下降；不能只比较两个组的平均单笔收益。它是方向信息的研究对照，基线本身不是推荐策略。因价差定义、h、阈值、可用样本与输入可得性尚未闭合，本轮不提交具体 PROPOSED 两次方案，也没有保留或消费新尝试。

## 数据、接线与工作量

| 必需项 | 现状 | 最小缺口 |
|---|---|---|
| 价差两端的同步 spot 与目标 derivative，以及身份/报价币/合约类型 | 行情本轮禁读；历史覆盖 UNKNOWN | 同步、缺口、可得时间与 source binding；mark/index 不自动等于可成交价 |
| 若沿用交割 carry：期限、到期日、合约切换、同币 spot | 本轮未核得，现有单 perp 输入不足 | 期限一致的信号，不用 perp premium 冒充交割 basis |
| 目标 perp 价格、结算 mark、持仓期间 funding | 只核代码能力，数据 UNKNOWN | 真实事件会计；不把未来结算用于过去信号 |
| 历史输入发布/可得时间 | UNKNOWN | 历史可靠证据；否则只能另议前瞻冻结采集，不能用任意延迟假装已证 |
| 独立 Search/Development/Holdout 及参考输入窗口 | 本轮不授予资格 | 全部被依赖资产和来源一同审计；已有 BTC/ETH、N/K 等保护继续有效，外部未登记接触 UNKNOWN |
| 通用 informative 与固定持仓 | 未正式接通 | `lab/bounded_strategy.py` 仅 OHLCV 源列、三个 populate、5m/1d、lookback 512。`lab/lagged_funding.py` 是整棵 AST 匹配的专用旧 funding 模板，不能当作通用 spot/dated-future 接口 |

单腿信号若原始证据门通过，最小复用开发是 source-bound 外部输入与明确时间可得性检查、狭窄消费者接线、适合该 h 的退出表达，保持 native 与六表。静态估计 2–4 个工作日实现与针对性验证，前提是历史源/合法窗口已解决；数据可得证据若缺失，等待期不能估成开发工时。本轮不实施。

若选择修正原 carry 合同，应忠实保留 long spot + short perp 两腿，并逐时刻校验自有资本、双腿不同成交/费用、保证金和 funding。现有一个 futures 模式 run 不提供此组合的完整现金与成交模型。初步至少 5–10 个工作日的模型实现/核验，而且会需要超出当前约束的组合执行/会计能力；不是半天换模板。这里只是范围估计，不提议自制 runner、不开发平台，也不把“不借 spot”误写成“需要借币”；旧合同不借币，但仍有自有资金机会成本及两腿资本占用。

## 唯一下一门与停止条件

保留 Q 为具名资料缺口；下次只有在可读的原作者/机构相关正文已被提供时，核对 **predictor 的具体定义、目标腿、h、均值与尾部区别**，并写出为何对当前交易标的可检验的清楚推断。一般原理与合理推断可以支持试验，不要求论文证明同币盈利；但不能拿不可核的回归设定填参数。若只能得到双腿 carry 或尾部预警，就不提交当前单腿 native 协议。来源门通过后才值得用一个小 Issue 评估接线，并在任何数据接触前冻结最多两次方案和窗口；本轮不申请参数，不启动开发。

## 接触限制说明

读取 ledger 时一次自选投影包含 `limited_mechanism_diagnostic`，意外向本 session 暴露 `btc-basis-cost-band-a.trades`、`btc-basis-positive-settled-funding-b.trades`、`shared_basis_gate`。随后已向监督报告，未把该诊断写入交付数值、未据此选参数/机制或认定经济失败。旧合同中的成本/门槛定义另获明确授权读取，其 hash 匹配。后续 correction 严格仅读授权投影，未打开 `results`、trades、trials、market 源文件。这是旧终态结果接触边界偏差，不是新窗口或 Holdout 数值泄露；无新行情/保护窗数值读取，不重置任务、DB 或 ledger。metadata 保留此次意外暴露，不把整个 session 声称为完全结果盲。

记忆仅用于定位历史问题：`MEMORY.md:286–296`、`:382` 的 basis/accounting 提示；关键旧合同与终态均已实时复核。没有写记忆。
