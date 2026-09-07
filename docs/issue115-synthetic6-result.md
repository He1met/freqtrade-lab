# synthetic/6：实际失败回执

执行固定HEAD ac29b2fc7b2ceaaf6355707cae35c5602bedde0a；经监督明确单次放行。
构造1次，Backtesting.start 1次；8 trades /16 orders /120小时trace，无callback fatal error。
这是原生导出事实，整体审计尚未通过。原始完整哈希见issue115-synthetic6-observed.json。

原始终态FAILED：ZIP配置JSON包含strategy:null，旧解析分支做membership时触发TypeError。
不可变ZIP/trace/log/原FAILED evidence完整保留；未使用retry，未运行第二次native。
只读挑出合法dict payload后，调用原封不动audit_causal遇到第二个失败：
`unexecuted risk reduction requires explicit review`。两小时（2019-10-03 01:00、04:00 UTC）
存在最小订单约束下无法执行的减仓，原native actual quantity保持，不能抹掉该告警。

已核验halt子断言：2019-10-07 01:00 UTC两币各2.645实际库存，在该小时各成交-2.645；
残余0，下一小时实际库存0，无halt后新增entry。此子项事实不代表完整control PASS。

- 合成成本后净收益：-37.344204912447646160 USDT；fee+slip 5.821480999999979520 USDT。
- 最大mark DD：0.31978991274579857756；20%风险门失败。固定mark冲击非市场数据。
- 控制整体：NOT_PASS，无法执行减仓需审查；cash不足原生未覆盖；真实funding结算UNVERIFIED。
- 预算：累计7槽已占、6次实际原生；新增此次1次。剩余synthetic/7–8及retry/2–4，均未放行。
- 市场执行false，市场经济结果NULL；没有市场策略成功/失败结论。

监督允许先推无native后处理修复与恢复计划，再用原ZIP+trace跑相同完整审计。
恢复只新增独立audit-evidence及恢复记录，保留原FAILED及所有原始字节；不放宽任何断言。

## 已完成无native恢复

先推送49b1fb4b87019f7e31d6cc4737f3e60992e87191修复及计划，再执行恢复入口。
完整原审计仍FAILED：`unexecuted risk reduction requires explicit review`。
独立audit-evidence SHA256为
`4c57957fed82a0c6aa21facc0664cbfc32006608caf35933b32e3df2c11341c6`。
原ZIP/trace/log/bindings/FAILED evidence逐一复核SHA不变，恢复新增native为0。
预算仅附加AUDIT_RECOVERED（证据取回，不是通过），原FAILED保持，已完成调用禁止native重放。
最终ledger SHA及恢复代码SHA见issue115-recovery-final-receipt.json。

95项非原生测试通过，包括strategy:null、重复payload和损坏内容拒绝。没有放宽原控制断言。
当前应提交监督终审；无法执行减仓的策略/执行处理仍须另行明确，不能直接开放市场训练。
