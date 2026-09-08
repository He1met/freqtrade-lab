# Issue149 单源文档准入与设计门修订

2026-09-08，承接6fa387机制卡。原卡保留作为历史，本说明在冲突处优先。授权及20分钟预算：[149评论5584518170](https://github.com/He1met/freqtrade-lab/issues/149#issuecomment-5584518170)。仅选择Coin Metrics Community，未巡搜其他供应商。

## 两项设计门纠正

1. 开发探索不要求未消费域。已暴露价格/历史可用于新的事前冻结开发假说，必须标明暴露、来源和用途；不能充当独立确认、恢复旧资格或挪用旧grant。
2. 历史首次发布时间及完整vintage不作为一切开发探索的硬门。最终链重建允许标 **RECONSTRUCTED_EX_POST**，保留当时发布、最终确认、重组偏差UNKNOWN。统一lag不能证明当时可交易；未来首次获取版本及接收时间可独立留收据，但不会使历史重建自动成为独立证据。

Issue正文已收窄为“是否与随后一个月ETH单场所现货成本后收益存在预测关联”。当前月度无条件对照不能识别价格信息之外的增量，也不能识别销毁的因果效应。

## 单源结论

**A：有界开发探索数据准入尚未证实，BLOCKED_DATA（定义/免费指标覆盖未核实）。B：历史点时与未来真实可执行证据UNKNOWN。** B未知不是本次A未通过的理由；本次没有证明该源不存在合适数据或一定收费。

|项目|此次官方文档证据|准入判断|
|---|---|---|
|免费/账户|[API Conventions](https://docs.coinmetrics.io/api)及官方检索正文说明Community免API key，非商业用途免费、Creative Commons；具体条款全文未读|一般入口符合需求，不能替代单指标权限|
|候选指标|官方检索结果中2023小时指标清单/教程出现`SplyBurntNtv`，名称Total Base Fees Burnt，属Pro示例；仅发现线索，未访问教程时间序列|不能由旧名称推定当前execution-only或Community可用|
|精确数值口径|[Fees官方页](https://gitbook-docs.coinmetrics.io/network-data/network-data-overview/fees-and-revenue/fees)指出ETH `FeeTotNtv`含执行基础费、优先费和blob费；`FeePrioTotNtv`是优先费总额，`GasBaseBlkMean`是平均基础费|总费不能替代销毁；均价乘总gas通常也不等于逐块乘积总和。差分重建尚缺同口径blob项及全部字段免费覆盖，不实施|
|日频/历史覆盖|费用文档有1d定义，以区块时间划分；具体销毁日指标的当前最早/最晚可用日、缺失和Community资格未查到|UNKNOWN，不虚构24个月连续可下载|
|下载可行性|[官方API参考检索结果](https://docs.coinmetrics.io/api/v4/)显示Community有asset-metrics时间序列接口及限流；本轮未请求接口/目录|工具能够发HTTP不等于指标可下；下载请求数/字节预算仍0|
|延迟/修订|此次文档未核实本指标首次发布、回补、修订和最终确认规则|B UNKNOWN；允许以后仅作ex-post开发，不把lag当收据|
|维护|有日聚合服务线索，可免自建节点；确切字段组合/覆盖未核实|当前不引入依赖、节点、服务、凭据或全链扫描|

## 读取台账和停止原因

11:36 UTC开始，实际2/2次搜索、3/3页读取。查询为 `site.docs.coinmetrics.io FeeBurntNtv ETH blob community API` 和 `site.docs.coinmetrics.io "Fee" "burnt" Ethereum`；搜索引擎附带其他供应商结果未追踪或用作准入。第一查询使用的FeeBurntNtv只是搜索猜测，不是认定有效ID；后续线索是SplyBurntNtv。

读取：API Conventions；Free Float Supply；Fees。第二页由搜索摘要定位，但实际正文只讲`SplyFF`，没有预期的burn定义：**一次定位无效，照计预算**。未跟随网页内动态查询指令，未读索引或增加第四页。没有下载文档示例所链接的数据，没有对示例数字做统计。

本轮因精确execution-only定义及该指标免费覆盖缺证据而停，不因历史vintage未知而停止。不能以“有Community API”自动标A PASS，也不能以这三页没找到就声称市场不存在免费来源。

## 唯一最小下一动作

请监督决定是否取得**同一来源的一份字段准入证据**：同时明确ETH日指标（或同口径有限差分字段）的execution-only计算、blob排除及Community覆盖范围；可为已有官方文档/目录说明。此证据到位前维持BLOCKED_DATA，本执行切片结束，不再自动追加搜索、换供应商或请求数据。该动作不是要求历史vintage齐全，也不是开发实现工程。若监督不能取得这份证据，则停在该知识缺口；无需自建基础设施。

真实下载、具体历史域、请求/字节限额以及一次开发分析仍需后续冻结。允许已暴露域及RECONSTRUCTED_EX_POST的修订不等于当前授权采集。0链上/行情获取、0统计/实现/native/global写；forward保持原契约。
