# Issue149 单源路径终态

**BLOCKED_DATA_ADMISSION；无策略实验或收益否证。** 2026-09-08。本终态优先于原卡及v2的待办建议；两份原文保留，不再自动获取准入证据或选下一机制。

证据来源：[监督核查评论5584556633](https://github.com/He1met/freqtrade-lab/issues/149#issuecomment-5584556633)。以下为监督已读/已执行证据的归档，执行任务本轮没有重复外部页面读取或目录请求。

- **字段不匹配**：监督读取Coin Metrics署名[Dencun Upgrade Metric Changes PDF](https://5264302.fs1.hubspotusercontent-na1.net/hubfs/5264302/Coin%20Metrics%20Dencun%20Upgrade%20-%20Metric%20Changes.pdf)第5页，确认`SplyBurntNtv`除交易基础费外含blob-space fees，不能直接作为本卡execution-only量。这不否定升级前可能一致，也不授权改窗口或差分拼接。
- **免费覆盖未列出**：监督向 `https://community-api.coinmetrics.io/v4/catalog-v2/asset-metrics?assets=eth&metrics=SplyBurntNtv` 发起一次免认证目录元数据GET，20秒/1MiB上限、无重试，返回 `{"data":[]}`。仅表示本次公开目录未列出该组合覆盖，不证明Pro状态或全世界无免费源。此前web safe-open失败是工具错误，不是供应商响应。
- **导航不足为证**：监督读取[Supply目录](https://gitbook-docs.coinmetrics.io/network-data/network-data-overview/supply)，列出的Burnt Supply链接指向revived-supply，不能用导航名称证明指标定义或权限。

A开发探索准入在此单源路径未通过；B历史点时及真实可交易性仍UNKNOWN。允许已暴露域开发和明确标注RECONSTRUCTED_EX_POST的修订继续有效，不能补足字段口径与数据源缺口。没有alpha、成本覆盖或盈利结论，不能把本终态记为策略亏损。

## 分开记账

|切片|文档搜索|页面读取/尝试|目录元数据GET|市场/区块/链上时间序列GET|统计/native/global写|
|---|---:|---|---:|---:|---|
|执行任务discovery|2|6|0|0|0|
|执行任务单源审查|2|3|0|0|0|
|监督补充核查|2|3首次打开尝试+1 PDF定点展开|1|0|0|
|本轮归档|0|0外部来源页；只读GitHub及本地文档|0|0|0|

监督元数据GET独立列账，不并入原行情112GET；不能把全文档研究称为0网络请求。GitHub读写和文献网页访问不属于市场GET。原native32及市场112GET未由本Issue增加。

归档范围只含原卡、v2修订和本终态三个Markdown。无代码、schema、窗口、forward、grant或global变更；不自建节点、不付费、不巡搜供应商、不修改字段或数据域。当前唯一动作是PR归档验收，Issue关闭代表本次有界discovery/单源准入交付完成，不能表示市场实验成功。后续研究由监督另行安排，forward到期优先。
