# 下一批有界可行性筛选 · 2026-09-07

> 纠偏：以下关于“等待 2027 年”和“156 周”的收敛建议已撤回；它们只是任意周频示例，不是研究硬门。同家族改进可行，跨资产同日也不自动禁止。以同目录 `correction.md` 的探索入口、协议粒度和下一步结论为准，原文保留用于审计。

**结论：NO_GO_IMMEDIATE_SEARCH；本轮入选 0 个。** 这不是所有机制无效的结论，而是本次三个方案均未同时满足机制依据、现有工程边界和合法验证窗。不要为维持研究频率再换币、反向或改参数。下一步应解决独立证据的时间来源，而不是增加 runner 或数据库附件。

**当前证据。** 本工作树 clean、detached HEAD `07ea2cf4742de3d2473302dc57bf0b2283a5fbf2`，只读 `git ls-remote` 验证与远端 main 相同；Issue #107 实时 OPEN。已 read_thread 上一任务并核对白名单 `s-final-delivery-receipt.json`（SHA `3262b22220c79f2763aadd021d9157a95f22f9b1cbe18c839d52851b9d402053`）及 `s-terminal-review.md`（SHA `b4b2af5bd167db80b05698044f0ebf869b1a31780f922b88e82f3056276ff0af`）：XRP S 为 NO_FINALIST，纯价 -280.607410、保守净 -299.394783 USDT，30 交易/27 完成 episode、四块全负；主 native 1，基准/D/H/Stress 0。D 已暴露，不作独立验证；H 未采集且仍保护。数据库状态仅引用回执，未直接读库。容量/外层附件缺口不改变经济终态。

| 比较的经济机制 | 依据、去重与成本判断 | 项目可行性与决策 |
|---|---|---|
| 低换手绝对趋势，long/现金；可讨论现货或 1x 合约 | 注意力与趋势延续有历史论文依据 [1]；台账已有 BTC absolute/dual momentum、weekly SMA+breadth、ETC weekly spot、XLM SMA90、BCH trend28、XRP weekly。去掉 short/funding 是暴露与成本改变，不能称新 alpha；只有先证明价格优势才有资格讨论成本后收益。 | OKX spot 与 Binance 1d 单仓入口现成；后者限 BCH/DOGE/ADA/BNB/XRP。无证据说明新增规则增量优于这些家族，合法新源 UNKNOWN。**NO_GO：不能仅换币/均线周期继续。** |
| 波动率管理，风险高时降低持仓 | 原论文研究逆波动风险配置 [2]；台账 BTC/ETH 2020、2022 批次已有此家族，后续技术核算终态不等于经济否定，也不允许重放。减少风险未必增加净利润，频繁调整增加成本。 | 当前 AST 只接受三个 populate 方法及固定字段，不接受 dynamic stake/position adjustment；Profile 固定 stake。二元波动过滤并非忠实复现论文动态配置，需另立假设。**NO_GO：本轮无工程扩展授权，亦无新验证窗。** |
| 现货多头＋合约空头 carry | 供需及套利资本约束提供非方向性收益来源 [3]；台账已有 BTC basis/funding 因果核算未证实的技术终态。必须同时计两腿费、滑点、资金和保证金风险；过去 funding 不保证未来收入。 | 当前 Profile 一标的一模式；不能拿单腿 short/funding 代替对冲，更不能拼两个 native 结果作投资组合证明。需要超出本轮的执行/核算支持。**NO_GO：经济机制有区别，当前最小入口不支持。** |

**窗口不是空白。** 全局台账 SHA 核为 `b29b11a8e01f43c00b742c994fde5df2d77a54df8f02f99ba8b96e3a03b20d73`；139 个非空 JSON 记录、2 个空行，按只读白名单投影解析，未修台账。BTC/ETH 的 2020–2024 已进入探索训练，2025 外层封存；2026 多段已消费/预留；现货 ETC 与合约多币也存在 D/H 保留。另有 XRP 2026-10-01 至 2027-04-01 的 H 预留及 2026-09-29 startup。未登记外部暴露仍 UNKNOWN。更早历史未完成可用性/暴露证明；不能把“台账没有命中”说成从未观察，更不能把另一币同一牛熊行情叫统计独立。本次三种机制的比较本身也增加选择偏差，未来即使单次过门仍需独立验证。

**最小真实替代：接受前瞻积累，停止即时重复 Search。** 本轮不选策略，故不伪造已冻结的唯一规则、收益门或可执行协议。若 root 愿意接受日历等待，可仅授权一次新的前瞻预注册；须有明确资产、非参数替换的规则增量、源码/成本/窗口和样本门，一份 Git 外文件即可，无新服务。为避免借用上述保护区，可从 2027-04-05 起开始新的观察与预热（仅规划，未占用/授权；不宣称是唯一合法起点），正式计分须再排除完整 lookback。未接受等待则维持本次 NO_GO，不再派同内容设计任务。

**日历代价和评价约束。** 52 个完整计分周只提供 52 次周决策；若 long/现金且仅周边界换仓、初始现金，完整自然往返至多 26 次，持续持有会更少；月频同年约 12–13 次决策、至多 6 个完整自然往返。更长持有期不能同时保证大量独立 episode。未来门须在选定规则后、读值前固定：交易与完整 episode 分开、持有期与窗口容量相容、固定时间块净利/MTM 回撤、全部费用与保守滑点、去最大盈利 episode、同成本风险匹配基准；不足样本为 UNDERPOWERED，不降低门。这里是容量算术，不是任何方案的统计功效或收益预测；S/D/H 若各需 52 周，顺序完成至少 156 周加预热，不能承诺几天内找到合格策略。

本次仅文献、代码、Issue、任务摘要和指定白名单读取；没有新增行情/信号/native/业务 DB 写入、工程改动或 GitHub mutation。研究源真实性与可用窗不明的状态保持 UNKNOWN；合格盈利策略仍未发现。

[1] Liu & Tsyvinski, Risks and Returns of Cryptocurrency, NBER WP24877（官方摘要支持历史 time-series momentum，不能外推本策略未来盈利）：https://www.nber.org/papers/w24877

[2] Moreira & Muir, Volatility Managed Portfolios, NBER WP22208（官方摘要；非加密资产本项目实证）：https://www.nber.org/papers/w22208

[3] Schmeling, Schrimpf & Todorov, Crypto carry, BIS WP1087：https://www.bis.org/publications/working-paper-1087-crypto-carry

工程依据：`lab/market_contract.py`、`lab/futures_costs.py:22`、`lab/bounded_strategy.py:34`、`lab/bounded_research.py:625`、`lab/research_console.py:3526`、两个现有 `fetch_*_profile_data.py`。官方引擎说明：https://www.freqtrade.io/en/stable/leverage/ 。NBER 正文抓取未成功，论据严格限官方搜索摘要，未声称完成论文复现。
