# Issue151 最终采集检查报告

**BLOCKED_DATA_RESPONSE_SCHEMA_MISMATCH；0分析、无收益结论。** 本报告为最新阶段终态，原入口停止记录保留历史。监督允许规则重建后，协议/代码在cfa4f32590b88540e0457b32560b26f3c2414a8e冻结并[先行评论](https://github.com/He1met/freqtrade-lab/issues/151#issuecomment-5584752772)，随后执行原额度唯一宏观请求。

## 实际发生的事情

2026-09-08T11:56:58UTC，官方EFFR接口返回HTTP200、118956bytes、refRates列表461条，响应SHA `74422c92303df4cacc40823129306ebc8a90b6c53f289c238d6f4674c5f03d61`。请求免账户、未重定向、无重试，20秒/1MiB预算内。它是**1次新增宏观时间序列获取**，不是0数据获取，也没有增加原112次crypto行情GET。

已读取且冻结的官方OpenAPI把利率列写作`percent`，实际首条响应列名为`percentRate`。冻结解析器读取`percent`得到None，Decimal转换产生`decimal.InvalidOperation / ConversionSyntax`，记录BLOCKED_DATA。HTTP获取本身成功；失败在响应数值字段与冻结定义不一致。461条只作响应体大小/结构说明，**不证明日期完整或语义一致**，校验没有完成。

检查失败后仅查看收据、顶层/首条字段名及条数以定位错误，没有把percentRate自动改名、修改冻结脚本或重跑检查，未请求第二文件。不能从这项工程/接口口径问题断言策略亏损，亦未确认percentRate经济语义。没有发生市场统计、BTC源读取、native、global写或钱包模拟。

## 结果与预算

|项目|最终状态|
|---|---|
|原宏观GET额度|1/1已消耗；不重置、不变名重取|
|原分析额度|0/1；未启动，不自动延续|
|21预定月|2021-03至2022-11全部NOT_RUN_NOT_SCORED，不是21个零收益或21个信号UNKNOWN|
|UP/NOT_UP有效组数、收益、均值差|未计算，NULL/未运行|
|新增cryptoGET/native/global写|0/0/0|
|原历史cryptoGET/native|112/32不变|
|验证|6个合成测试通过，CLI控制check通过；不证明实际接口契约符合或市场分析通过|

Git外`/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue151-effr-v1/acquisition/`保留attempt、headers、原response、receipt、failure；未创建analysis槽。Git内`docs/issue151-acquisition-result-v1.json`只保存公开响应结构与收据/SHA、全部未运行单元，不含时间序列值。原静态HTML/YAML收据仍在issue151-doc-admission-v1，便于审查已读规范与响应差异。

本PR交付发现卡、两阶段历史记录、规则重建日历/协议/冻结最小CLI、必要测试与实际失败报告。所有未完成状态公开，Issue保持OPEN供监督判定后续。执行端停止，不自动选择下一机制或扩展数据/分析额度；forward五文件/manifest/global/grant及旧产物保持原值。
