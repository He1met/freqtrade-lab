# 资金费对照终止后的唯一补充发现

本批结论为 **`NO_DEFENSIBLE_HYPOTHESIS`**：没有找到可在现有限定数据与交易范围内忠实执行、且经济逻辑足以区别于失败家族的下一项实验。探索优先槽保持空；固定 `carry_nonpaying` 确认观察继续。这是一次已完成的发现终态，不是等待重跑 round-005，也不宣称 BTC/ETH 永远没有可行机制。

本批独占开始收据：2026-09-09T02:12:07.858974+00:00；本代理首次实际观察：2026-09-09T02:13:18+00:00；查证完成：2026-09-09T02:16:43.526692+00:00。使用 **3/4 query、5/6 独立页面**。同页面日期/摘要字段摘取另有记录，没有新增 URL；查询和页面执行前后均已追加到 `supplemental-v1.events.jsonl`。主动工作墙钟 205.5 秒，包含工具及审批等待；从独占开始至结论 275.7 秒，均小于 600 秒。CPU 与金额未知，保留 NULL。剩余查询/页面预算不用于强造第二轮发现。

## 实际检索

- `bitcoin ether perpetual futures pairs trading cointegration research paper`：原始论文域名限定，完成。
- `BTC ETH pairs trading basis mean reversion discussion`：GitHub/Reddit 近 7 日，完成；未获得日期已核且适用的新机制。
- `BTC ETH relative value pairs trading cointegration discussion`：扩展近 30 日，完成；多数结果为旧文或仅最近抓取的仓库。不能把抓取日期当发布日期，相关日期保留 UNKNOWN。

本次复用今天 DAILY 的资金费公式、历史可用时间和公开研究线索，新增查证范围转向相对价值、基差与日历活动。没有计算新收益，也没有读取确认窗口、实时行情或其他交易资产的数据。

## 原始依据与限制

| 来源 | 可核日期 | 本次读取及实际支持 |
| --- | --- | --- |
| [Fundamentals of Perpetual Futures](https://arxiv.org/abs/2212.06888) | 2022-12-13；修订 2024-08-21 | 摘要/版本页：资金费与有成本定价界；永续没有固定到期收敛保证。不能直接推出单腿方向收益。 |
| [BTC/ETH 跨相关原始研究](https://arxiv.org/abs/2208.01445) | 2022-08-02 | 摘要/版本页：存在同时及滞后跨相关，未观察到明确领先资产非对称。跨相关不是当前可交易价差均衡证明。 |
| [Periodicity in Cryptocurrency Volatility and Liquidity](https://arxiv.org/abs/2109.12142) | 2021-09-24；修订 2021-11-03 | 摘要/版本页：周内、小时及小时内的波动/成交量模式；未在本次读取范围提供独立方向入场依据。 |
| [Binance Index Price Kline 官方字段](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Index-Price-Kline-Candlestick-Data) | 发布/更新 UNKNOWN | 指数 OHLC 与时间；对应成交量槽标为 Ignore。参考指数不是可执行成交或对冲腿。 |
| [adaptive-regime-switch-pro](https://github.com/Risingtell/adaptive-regime-switch-pro) | 发布/更新 UNKNOWN | 公开开源项目线索，不同平台且未经复现。未采用其回报、参数或框架。 |

论文均为本次摘要级查证，没有宣称完整复现。论坛/开源只作发现线索；不把它们当机制已经验证或本项目盈利证据。搜索中的期权套利、其他资产篮子、宣传或实时价格观点均未采纳。

## 三张候选卡：均未选中

| 候选 | 与旧家族的区别 | 数据表达与不选理由 |
| --- | --- | --- |
| BTC/ETH 两永续腿相对价值 | 相对价格敞口，不是单币 funding 符号/变化或突破过滤 | 已准入双币小时 OHLCV、mark、funding 可供将来研究；本次原始资料未给出可冻结的均衡来源、对冲规则及收敛尺度。当前平稳性/净优势 UNKNOWN，未测量。相关性不足以直接冻结均值回复交易。`NO_DEFENSIBLE_HYPOTHESIS`。 |
| 永续对指数基差收敛 | 定价关系，而非费率单腿方向 | 原始 index/premium 数据确实已存；当前 development manifest 只准入 OHLCV、mark、funding、receipt、instrument rules，未准入 index/premium。指数亦非可执行腿；未引入用户未授权的现货、期权或其他平台对冲。单腿不能冒充基差套利。`BLOCKED_DATA_AND_EXECUTABLE_EXPRESSION`。 |
| 日历波动/流动性 | 时间结构，而非已结算费率方向 | 小时数据能表达粗粒度活动，但原始依据支持波动/成交量，不是有符号收益溢价。给失败 breakout/flow/funding 加小时门槛会重新打开结果驱动优化。`NO_DEFENSIBLE_DIRECTIONAL_HYPOTHESIS`。 |

只读元数据再次区分“文件存在”与“已准入”：`first-capture-v1` 的 BTC、ETH index 各 **13,104** 行；这些记录不在当前开发 admission 清单。没有读取指数价格数组或以其结果选型。来源及清单 SHA、文件范围见 JSON。

## 唯一下一条件

继续固定确认的真实采集与意图观察；短期探索保持空槽，等待下一次原定的每日有界发现提供**不同经济机制的原始依据，以及仅用允许交易腿和已准入数据的忠实表达条件**，之后才登记市场任务。今日补充发现已完成，不因还有 1 query/1 page 或市场预算就继续造任务。

不倒置 round-005 资金费符号、不调其 8h 持有期、不恢复已停止的 flow/breakout 分支，也不读取确认收益作选择。本批新增 native、行情 HTTP、市场任务及变体预算消耗全部为 **0**。根任务负责保存 runtime 终态 `supplemental-v1.json`；本代理没有修改 starter、daily、scheduler、冻结代码或市场状态。
