# #84 来源合同语义评审 · 2026-09-06

**结论：KEEP旧批次封存及不重试；不把3秒断言为坏数据，也不把2秒当交易所事实。当前仍NO_GO直接实施/重采。** 可提出新版本来源/记账合同，但不能伪称“保持旧2秒的bugfix”。本评审仅查官方文档与代码，未取归档、费率、OHLCV或调用行情API，未读D值、凭据、DB；未改源码、ledger、旧protocol或decision。

| 问题 | 可确认与UNKNOWN | 精确证据 |
|---|---|---|
| `1704326403000`是什么？ | 已知为旧失败CSV第三列`funding_time`，转换为2024-01-04 00:00:03 UTC；并非我们见过的独立publication字段。**该CSV列究竟是实际扣费处理时刻、结算记录生成时刻还是带延迟的结算标识，UNKNOWN。** 仅同名不能等同REST `fundingTime`。 | producer `scripts/fetch_okx_profile_data.py:61,850`；原终态QC已获准引用。本轮官方[历史下载介绍页](https://www.okx.com/en-sg/historical-data)仅说明有历史funding，未找到CSV三列的正式定义/与REST逐列映射；不引用第三方包推定官方语义。 |
| REST与发布时点如何区分？ | 官方历史REST把`fundingTime`描述为结算时间、`realizedRate`为实际费率、`fundingRate`为预测费率；未保证`fundingTime`是每一账户实际入账毫秒。WebSocket另有`ts`数据返回时间、`settState`处理中/已结算、`nextFundingTime`下一期预测结算时间。历史REST没有first-seen证明；今天可下载不等于当时可用于信号。 | [OKX API：Get funding rate history](https://app.okx.com/docs-v5/en/#public-data-rest-api-get-funding-rate-history)；[Funding rate channel](https://app.okx.com/docs-v5/en/#public-data-websocket-funding-rate-channel)。不能把`ts`、计划周期、实际评估时点混为一个字段。 |
| 2秒/8h是否官方事实？ | **2秒未找到官方依据，是项目已冻结的保守接纳/向下归格假设。** 8h是默认而非通用保证；官方允许其他周期及动态调整。2024年DOT整段是否8h、该CSV如何标记变更，本轮未取值验证，UNKNOWN。 | producer `:49–61,860–899,1147–1158`；[OKX资金费机制](https://www.okx.com/en-gb/help/perps-funding-fee-mechanism)说明持仓是否计费取决于评估时点，处理可能到一分钟。当前页面2026-08-27更新，不能直接证明2024该行正常。 |
| 3秒是否被错当坏数据？ | **3秒可能是正常处理/记录延迟，不能由本次证据确认；把它标“违反V1接纳合同”成立，标“交易所坏数据”不成立。** 官方结算规则与“必须≤2秒”并不等价；该未知也不能变成放宽3秒、60秒或任意吸附的许可。 | 当前官方规则允许非瞬时处理；[2019官方规则变更](https://www.okx.com/en-ae/help/adjustment-of-perpetual-swap-funding-rules)区分费率确定与结算、且历史机制曾变化，进一步说明不能从今天文档反推2024CSV列定义。 |

原生忠实性与误差（静态代码结论，无经济运行）：

- 已核原生HEAD=`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`，相关文件干净；本项目HEAD=`f3ada868f8ea737756b7a68227cfd1829086f600`、干净。项目producer先算`drift=raw_ms % 8h`，只接纳0–2000ms，再写`raw_ms-drift`，费率读取晚于时间/身份QC。这是防止无界时间移动和固定周期错配的有效拒绝机制，**不是保证真实现金流精确的充分条件**。
- 只取消上述归格仍不保留原始时刻：producer `:1195–1200`调用原生`ohlcv_to_dataframe(...,"1h")`；[converter.py](/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade/freqtrade/data/converter/converter.py:41)与[timeframe工具](/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade/freqtrade/exchange/exchange_utils_timeframe.py:32)实际向下取整到**分钟**，会把00:00:03变成00:00:00（代码注释“seconds”不能替代实现）。
- 若绕过converter直存原始时刻，原生[加载器](/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade/freqtrade/data/history/datahandlers/idatahandler.py:377)只将funding向下到秒；00:00:03仍在。然而[combine_funding_and_mark](/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade/freqtrade/exchange/exchange.py:3911)在无fallback时按`date`精确inner join，现整点1h mark不会匹配00:00:03，事件会被剔除。不能填0补成“已记账”。因此现原生通路不支持仅靠保留raw实际时间就忠实记账。
- [calculate_funding_fees](/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade/freqtrade/exchange/exchange.py:3955)使用开/平时刻双端包含区间，合并的`open_fund × open_mark × amount`求和，long取负、short取正；[backtesting.py](/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade/freqtrade/optimize/backtesting.py:1008)整点更新、离场强制结算。OKX继承的mark/funding频率均1h，未发现秒级或逐账户评估模型。
- 边界反例（仅逻辑示例）：假设实际事件T+3秒，仓位T时已平，真实事件不应归该仓；归格T且平仓端包含，会多计整笔资金费。若T+1秒开、T+3秒仍持仓，归格T反而漏计。哪怕只有1秒偏移也可改变一整笔现金流，误差不是“3秒占8h很小”；对long/short与正/负费率均须检查，不能统一称保守。mark还以计划时点小时开盘价近似实际评估价。这对#84恰在UTC边界进出的1d/48h规则尤其相关。

最小可提案范围（均未实施、仍需监督审批）：

1. **优先KEEP**：旧2秒合同及失败证据不追改，经济源码/仓位/窗口/全部研究门保持冻结，source授权仍0。旧失败是来源兼容性阻塞，不是经济否定。
2. 若拿到官方CSV语义/归档与结算事件的明确映射，可设计窄 **source contract V2**：在Git外既有JSON证据保留原始时间、明确事件键/映射依据及版本，拒绝未知周期/重复映射/缺事件；区分事件账务与信息可用时点，不能由费率值推断时间。继续原生只能明确接受“计划时点网格近似”，另做开平边界资金费归属的最不利完整事件敏感性核算，沿用原净正/风险门，不能据此宣布秒级忠实。先用合成时序覆盖整点前后、重复/缺失、周期变化及多空正负费率；如需改native、增加runner或新SQL结构，立即交回。条件满足后的文档/窄producer与同一artifact附加核算主动工程粗估1–2日，当前不能启动；需要事件时点mark/账户级精确记账则范围明显增加，工时UNKNOWN。
3. 官方REST `fundingTime + realizedRate`提供较明确结算记录语义，现producer已有该接线，但文档仅保留近三个月，**不能覆盖#84的2024/2025原窗口**；且未保证每个键严格落计划网格。它不是本批无代价替代。改成近期/前瞻窗口必须新数据资格和来源合同、保留旧暴露；达到原年度S/D样本目标需相应历史支持或日历等待。WebSocket的预测时间/返回时间可用于未来留first-seen，但需要新采集授权，不能补造2024发布时间，本次不建设采集服务。

目前未获得足以连接CSV列语义与精确事件键的官方依据，故 **NO_GO直接开发、NO_GO重采**。监督可单独决定是否接受有明确误差边界的新合同研究，或改变方向；不能只因为+3秒失败就上调容差。即使来源模型通过，成本后盈利仍须唯一真实S及之后独立D/H检验，经济规则/门不变。
