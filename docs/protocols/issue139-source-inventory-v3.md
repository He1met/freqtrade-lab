# SOURCE_INVENTORY_V3 — 唯一固定窗口结构普查

监督已授权基于afe06be终态的一次普查，非回测/缺口执行准入。v1/v2 BLOCKED_DATA和全部原terminal/budget保持原字节，钱包草稿暂停。时间缺口和本小时内提前close只标cause UNKNOWN并保留原始行，不填K线、不认定停机，不按逐日例外判市场可交易。其他schema/类型/重复乱序/非整小时open/越小时close/非法OHLC或volume/身份HTTP控制/无进展错误立即停。短页未到固定终点停止、不补请求；实际open推动游标，分页之间连续审计，不因缺口跳过未请求段。

唯一市场仍Binance SPOT BTCUSDT/ETHUSDT，warmup2020-04-02至2021-01-01、训练2021-01-01至2023-01-01。五个已有raw复用并在启动前核SHA；不重新请求。第五页最后open实核为1616662800000，BTC新cursor1616666400000（2021-03-25T10:00Z）；ETH初始1609459200000，endTime1672531199999，interval1h、limit1000。仅api.binance.com/api/v3/klines。BTC<=16、ETH<=18、共<=34GET；new<=16305102bytes/895活跃秒、单<=1MiB/20秒、>=1秒间隔、1worker、0retry/redirect。原78GET/15076043bytes/169.6002914905548秒保留，spot累计<=39GET/16MiB/900秒、global<=112/122GET。只创建同root唯一inventory-v3及关联累计budget，旧记录逐字段保留；先登记并绑定postSHA，失败不可换root重启。

输出是SOURCE_INVENTORY_COMPLETE_NOT_EXECUTION_ADMITTED，不能写完整数据PASS。每币报告原生行数、缺小时数/连续缺口跨度与最长、短K线、完整/不完整日及原始异常时间分布；未知原因统一UNKNOWN。对完整274日warmup与训练可用日，计算85/273连续完整日依赖下的结构可用日数，明确其为保守数据可用性设计，非84收益数学必要条件、策略交易数或独立资格。任何未完成源不报告完整窗口可用数为已知值。

启动清单绑定所有源/旧terminal/预算/保护SHA、准确cursor、追加登记前后SHA及冻结代码/解释器；运行前合成验证多页未知异常累计不填充、非法边界仍止、复用不重取及cursor绑定、预算超额先拒/失败计费/重启拒绝。成功后才由监督判断现有保守规则能否产生可执行样本；本切片市场native/PnL/实盘/付费API均0授权。
