# Issue157：B V3 官方展示重建 v1

用户要求补齐可视展示；监督批准独立base/stress各1次native冻结订单重建，每次180秒、0retry、0新行情GET。只用原2021–2022已暴露spot源和已完成B V3结果。不重算84日信号、仓位、因果决策、lot/dust风险或模型费用，不调用旧耗尽runner/root/预算，不改任何旧产物或B/USDC forward/global/grant。

旧结果缺完整LocalTrade/Order对象及标准export，不能直接包装。新适配器在独立root逐笔将已存36个精确gross数量/已含滑点价格交给同版本原生订单方法，核对gross、价格、order cost、native余额/realized/amount/open_rate/订单数；任何不一致立即失败，不改数字求通过。参考价格仅原SHA绑定OHLC，缺口不补。原生quote-fee库存与模型base-fee库存差别保留。

重建完成先保存原生未平仓对象及原模型terminal副本。随后调用官方`Backtesting.handle_left_open`、`generate_backtest_stats`、`store_backtest_results`，使用原源各币最后一条OHLC的实际open作为官方synthetic terminal force_exit。这是新增的展示终点假设，没有重复叠加最后滑点，不是原B成交或可执行dust清仓。报告单列终点前原生按该open估值、终点后余额和差额，不混用模型账。

策略显示名为`B_V3_DISPLAY_REPLAY_BASE_SYNTHETIC_FORCE_EXIT`/`...STRESS...`，notes显著写明DISPLAY ONLY、NOT signal backtest、synthetic terminal force_exit和原生费用/DD差别。没有伪造IStrategy等价。官方Trade可能仅为两个跨episode聚合持仓；旧36订单、18资产episode、11共同区段与官方Trade数分开。胜率、trade-close收益曲线/持仓时长/DD只是原生聚合记录与展示终点的统计；不得以100%胜率/0回撤取代原模型18episode或小时MTM风险，也不人为拆trade。

执行root `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue157-native-display-v1`，base/stress目录创建即一次性占位，attempt在执行前落盘；失败留failure、不换名重试。manifest绑定代码、协议、原源清单、原结果SHA和native实现；独立grant绑定manifest SHA和2次范围，先push再执行。总native展示重建2次，与历史研究native32分账，不追加global。

展示root `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue157-frequi-display-v1`：普通复制官方Freqtrade2026.7 package，不动原安装；官方FreqUI3.1.1 release ZIP SHA `ebe048922bdb446a1c581a60364c0a268c991348625d2f87fd64fcd9be7aed3e`。重建ZIP/meta普通copy入独立user_data/backtest_results，不软/硬链接canonical。仅webserver 127.0.0.1:8080，空交易所凭据；临时本地认证配置chmod600，不进Git/日志/截图，绝不读取旧secret。出网隔离保留localhost，不触8011/8012，不运行trade/dry-run交易。

测试使用纯合成BTC价格与两次买卖、残余native持仓，真实引擎重建/官方导出/官方加载、坏摘要拒绝、已占目录拒绝。真实执行不作为测试重跑。最终需官方历史列表与加载API可用、监督浏览器截图确认。UI交付不授予独立确认/20%风险/盈利或交易资格。旧模型base +4.959796% / stress +4.758604%以及模型残余继续由原报告另表解释，不改为UI口径。
