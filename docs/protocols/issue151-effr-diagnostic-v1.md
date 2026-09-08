# Issue151 冻结开发协议v1

授权：[监督5584698800](https://github.com/He1met/freqtrade-lab/issues/151#issuecomment-5584698800)，继续原未消费的一次宏观GET与一次分析，不是新额度。原卡及入口终态作为历史保留，本协议为后续阶段的定义。

## 固定输入与日历

唯一URL：`https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json?startDate=2021-01-01&endDate=2022-10-31&type=rate`。官方OpenAPI静态正文已核对effr/json、start/end含边界及refRates字段。一次curl GET，20秒、1MiB、0重试、不跟随重定向/分页、不账户。响应状态必须200，身份EFFR、日期仅本域、非空refRates列表；外域/身份/结构冲突停止。采集失败消耗GET但不消耗分析。

`effectiveDate`作为所属交易日是结合官方方法与字段名的**有依据推断**，非已获逐字定义；`percent`为百分比年利率数值，不是现金收益。本研究使用最终历史交易日率RECONSTRUCTED_EX_POST，不按未知历史首次发布日期聚合，不把统一lag当历史可交易性证明。

独立预期日期见`docs/issue151-calendar-v1.json`，下载前冻结。RULE_RECONSTRUCTED：周末排除，元旦/独立日/退伍军人日/圣诞按固定月日，周日顺延周一、周六不前移；MLK/总统日第三周一、Memorial五月最后周一、Labor九月首周一、Columbus十月第二周一、Thanksgiving十一月第四周四。2022起Juneteenth，2022-06-20休假；2021-06-18/21营业、2021-12-24营业；不套用Good Friday交易所假日。

依据为监督已读NYFed[假日规则](https://www.newyorkfed.org/aboutthefed/holiday_schedule.html)、[Fed2021-06-17公告](https://www.federalreserve.gov/newsevents/pressreleases/other20210617b.htm)、[FINRA2021-10-15公告](https://www.finra.org/rules-guidance/notices/information-notice-101521)；后者交易所整表不照搬。完整历史例外仍UNKNOWN，不冒称官方原表。缺预期日/多出日/重复日/不能解释的修订或footnote使该交易日所属月份均值NULL；不据响应改期望、不补填。revisionIndicator Y作为已说明的最终历史修订保留；未知标签使月份UNKNOWN；非空非0footnote因未绑定含义保守UNKNOWN。季度滞后统计不替代此日序列。

## 一次21单元

2021-03至2022-11逐自然月，每月8日00UTC决定、01UTC买入，次月8日01UTC卖出。信号为前一个完整月有效营业日算术均值减再前一个完整月均值，>0 UP，否则NOT_UP；任一月UNKNOWN则信号UNKNOWN。交易收益只来自同一BTCUSDT源，不新增crypto行情GET，原39源绑定内仅BTC 1h具名源，解码价格限制2021-03-08 00至2022-12-08 01UTC含边界。

从入场至退出前一小时必须完整，旧未知/短小时整事件UNKNOWN，退出仅要求存在正开价；全域异常与旧inventory比对，漂移停止。每事件固定1quote假想往返，不钱包/再投资/DD。净值=(Pout/Pin)*(1-s)/(1+s)*(1-f)^2；base f=.001,s=.0006；stress .002,.0012。

全21月公开信号/组别、排除理由、两费滑毛净；每组报n、均值、中位数、正数、最大单月绝对/正贡献，组均值差UP−NOT_UP。有效组任一<5优先UNDERPOWERED；否则任一成本差>=0则STOP_RULE_NOT_SUPPORTED；方向均符合但任一NOT_UP均值<=0则NO_LONG_COST_SUPPORT；否则仅EXPOSED_DEVELOPMENT_ASSOCIATION。>=5也不是功效保证/独立政策冲击、因果或超价格识别。无翻向、改月8、阈值/窗搜索或补样本。

## 运行与防重复

固定Git外root `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue151-effr-v1`，acquisition和analysis分别mkdir独占，已有目录即拒绝；失败不换名。manifest绑定脚本、所用旧helper、calendar、协议、原manifest/inventory及保护文件，先push+评论再acquire。采集receipt记录精确URL/时间/HTTP/SHA/bytes与版本检查。下载通过后把响应SHA/checkSHA和manifestSHA写Git内小binding，推送后才execute。

唯一analysis一次worker180秒/21units/0retry，无网络/native/global写/新钱包。原BTC文件SHA前后校验；原112cryptoGET/native32不变，宏观新增最多1另计。检查/合成测试不消费市场分析，但不以实际市场数据重放测试。CLI check只读控制文件；acquire只宏观；execute才读授权BTC。

必要6测试已通过：金融服务日历边界、宏观异常传播、身份/外域拒绝、往返算术及21窗口、持有缺口与退出语义、已有采集槽拒绝网络。文档/代码检查不证明策略收益。
