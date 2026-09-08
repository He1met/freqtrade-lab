# Issue151 入口门终态：BLOCKED_DATA

2026-09-08。按[完整切片授权5584649755](https://github.com/He1met/freqtrade-lab/issues/151#issuecomment-5584649755)检查入口，4/4次官方静态读取后停止。未请求宏观文件，未读取BTC行情，未实现或运行诊断。不是策略否证。

## 已核实与未落实

官方[Markets API HTML](https://markets.newyorkfed.org/static/docs/markets-api.html)静态引用`./markets-api.yml`；读取该[OpenAPI](https://markets.newyorkfed.org/static/docs/markets-api.yml)（未执行JS）确认：

- `/api/rates/unsecured/{ratetype}/search.{format}`支持effr及json；startDate/endDate为yyyy-MM-dd且两端包含，type可为rate。
- 据此可构造候选 `https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json?startDate=2021-01-01&endDate=2022-10-31&type=rate`。**此URL未调用，尚未冻结为获准发出的请求**，不能因路径可构造就跳过剩余门禁。
- 返回EFFR schema列有effectiveDate、percent、revisionIndicator、footnoteId；effectiveDate只有date类型与示例，没有明确交易日/发布日期说明。以名称结合发布政策推断交易日是合理线索，但本次没有把推断当已核实字段语义。

[官方假日页](https://www.newyorkfed.org/aboutthefed/holiday_schedule.html)描述周末休业及周日假日顺延星期一，但实际表仅2026–2029；未取得2021–2022目标营业日完整清单或历史例外证据。不能以文件返回行数定义期望日历，也没有根据现代日历自行填入历史规则。

[官方发布方法页](https://www.newyorkfed.org/markets/reference-rates/additional-information-about-reference-rates)明确一般09ET公布、假日顺延、通常同日14:30ET修订及特殊例外；它没有在所读内容中把API effectiveDate显式映射到发布日期/交易日，也不提供目标域历史营业日清单。因此**本切片要求的日期语义/独立日历门未落实**；这是预算内证据缺口，不证明日期语义无法确认、免费接口不可用或历史不存在。

A有界开发入口定义未全部落实；B历史首次发布时间仍UNKNOWN。EX_POST与已暴露开发的允许继续有效；此次停止不要求全vintage，更不因B UNKNOWN自动否决A。

## 请求与产物记账

|类别|本次新增|状态|
|---|---:|---|
|官方文档/静态资源HTTP|4|HTML、YAML、假日页、方法页，各一次成功；预算耗尽|
|宏观时间序列GET|0/1|未启动，不能自动移到后续切片使用|
|新增crypto行情GET|0|原112不变|
|分析invocation|0/1|未启动，21单元无统计结果|
|native/global写/钱包|0|原native32不变|

静态原文与收据保存在Git外`/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue151-doc-admission-v1/`，不是市场数据产物：

|文件|SHA-256|
|---|---|
|api.html|c1ab76a0e006e7f16c5ba4660716f2ade0f8a76e58dbbe7124d73a9fbf98cd2c|
|api.yml|5dbb331d86b91bfc115be9b5fe9c46735833a4f7280d33e4327e8acf7ad30d2b|
|holidays.html|d423aa463b3c0b7b5ca36cf687cabf0cb4adb56b6a47e09b7feffe143b5a8273|
|method.html|14b237aa9ee3f91e95541b8cedd19261741e5c3a111f286280d9151331503e21|

原发现卡作为历史保留，其试验草案没有冻结执行。此终态结束本次入口验证切片，不追加读取、换源、测试接口、构造日历或下单；提交PR供监督验收。forward/manifest/global/grant及旧产物不改。Issue若关闭只表示本切片有界交付完成，不表示策略被检验。
