# Issue139 现货执行绑定 v1

本包实现合成可测的84日long/flat参考状态机及严格源绑定，**原生撮合一致性未建立**，实际入口必须BLOCKED_NATIVE_RECONCILIATION。不能将参考账本叫作Freqtrade原生成交，不能据此执行市场PnL。原v1/v2数据失败不变；全部普查异常机械视为缺失，不再使用Feb11白名单，原因UNKNOWN。39源SHA/普查terminal/启动manifest/代码绑定在首批manifest中；任何改变先拒绝。

UTC日t的24完整小时直到t+1日00才成为完整日，最后闭市日号为`hour//24-1`；方向依赖该日到84日前全部85完整日，C依赖273完整日。依赖不足不增风险、未到期旧固定stop继续。首次正信号可入场，00冻结数量最早01成交；01缺open则取消待入场、不恢复补做。负信号下一小时退出；止损/84日到期后等非正再转正。缺口期间原有库存保留，以最后已知价标STALE/年龄；恢复先重估gap、10%/15%锁存、已排退出/止损，再考虑新信号，不提前读取将来异常。

共享1000USDT，无借贷/short。B/A/C/half-B按已冻结风险cell，所有同时买意图先按共用现金/80%上限同比缩放，再40%单币上限/lot向下量化；不凑最小单。base买费向上按baseCommissionPrecision模型扣收到的币，卖费向上按quoteCommissionPrecision模型扣现金，不双扣；实际历史精度/动态参考价UNKNOWN。名义风险调整不合法时保留dust/库存并阻止新风险。尾部只报告现金、市值、成本基础、未实现/已实现、估算平仓费和估值年龄，无force-exit。参考模型是真实结算的假设，不是实盘证明。

`lab/spot139_model.py`实现上述参考状态机，`lab/spot139_binding.py`实施篡改/网络/无源原生成交/库存差异拒绝。尚无市场循环接入它。已读固定Freqtrade2026.7代码：原生买单`cost=amount*propose_rate*(1+fee)`；旧observed callbacks用买卖amount差构建库存而非买入扣base fee；原生末尾调用handle_left_open。旧ObservedBacktesting还硬绑定funding视图。这些路径不能直接满足现货本合同。可复用的是离线单账户实例化、网络拒绝、调用预算/超时/收据骨架；不能声称只改trading_mode已实现一致。

首批只列B/base与B/stress，各预留1个全球96槽；当前没有占槽或市场授权。后续A4解释、C/half4条件不变，总10；失败/超时也占已预约槽，180秒上限，0额外重试。进入native前必须先验证spot原生订单扣费库存和期末保留映射，不允许通过改自定义账本让差异消失，也不静默把原生执行替成另一引擎。由于这项未完成，首批manifest标blocked、入口先拒绝，不进入预算预约。

实际入口：`python scripts/check_spot139_execution.py docs/issue139-spot-first-batch-v1.json --manifest-sha256 <固定SHA>`。只验哈希，不解码或计算市场价格/PnL；预期退出2且native0，非市场smoke。此次仅合成测试验证双币现金/fee/lot、缺失恢复/无先知、首入重入到期、尾库存和篡改网络拒绝。没有独立资格或策略有效性结论。
