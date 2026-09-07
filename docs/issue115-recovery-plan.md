# synthetic/6无native恢复计划（先发布再执行）

仅修复ZIP解析：配置strategy:null不能做membership；只接受dict strategy中精确
PortfolioCausalProbe的dict payload，多个有效匹配/损坏JSON/ZIP均拒绝。
原调度器只保存error_type/reason，没有原始完整traceback；该栈为UNKNOWN。
已只读逐字复现原membership表达式，确切再次触发同一TypeError，不冒称保存了原栈。

先推送修复与本计划固定提交，再执行scripts/recover_portfolio_causal_audit.py一次。
它绑定已发布失败预约、输入、原生source、ZIP/trace/log/bindings/FAILED evidence原始SHA，
要求完整audit_causal及核心依赖仍是原执行字节；新parser/recovery代码另记commit及SHA。
通过相同完整审计后仅新增独立audit-evidence.json与AUDIT_RECOVERED附注，原FAILED保持。
AUDIT_RECOVERED表示审计证据已取回，不表示control通过；已知完整审计会遭遇减仓告警，
必须记录FAILED，不能删除断言。附注也会阻止对完成的原生调用再次native重放。

所有原始产物不可覆写；不导入或调用Backtesting构造/start，不占用技术retry。
原生新增0。若任何绑定/产物缺失或变化即拒绝，不补造或自动另跑。
