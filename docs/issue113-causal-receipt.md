# Issue #113 非原生因果核心回执

范围：因果指标、趋势/反转逻辑episode、日线冻结ATR数量、C逐资产恢复、A/B/C/half-risk-B
风险目标映射及显式成本。没有市场数据、原生Backtesting、虚构fill、PnL或自然样本。

- Base SHA256: `e664b6447879a350663fa7940036a2682d3970af65f7c218c540e2e62ff28e85`
- Semantics SHA256: `5fb7ee5d01920eaa91eafd936569c6c7a15fbdf5708c16162fd49537d8b7848a`
- 验证命令：`PYTHONDONTWRITEBYTECODE=1 uv run --with pytest python -m pytest -q -p no:cacheprovider tests/test_portfolio_causal.py tests/test_portfolio_execution.py tests/test_portfolio_budget.py tests/test_portfolio_preflight.py`
- 结果：78 passed。其中新核心23测试，覆盖手算指标、未来扰动、双SHA、warmup、净零保留、
  单方止损增净多、gap、同时止损、halt、现金、warning、half-B、C恢复/缺失、技术恢复、
  实际flat翻向、目标/时间退出、冷却、最小量dust及压力费用。
- 原生新增调用：0。calls.jsonl SHA256与#111回执相同：
  `986f164d19be4d4188ef59d8a052102f3a9c479469c8a7bc1703d214c1c97d7a`。
  原预算保留6个已占槽、5次实际原生调用；未消费synthetic/6–8及retry/2–4。

使用入口和失败行为见 `portfolio-causal-semantics-v1.md`；测试全部为纯内存合成数据，
未访问敏感数据库。没有新增schema、索引、服务或运行后台。

状态：`NON_NATIVE_CORE_IMPLEMENTED`；市场准入false，经济结论NULL。
原生单净仓adapter、合成固定输入SHA、双SHA预算事件接线、funding结算边界/精度
仍需后续验证。synthetic/6不是已授权调用；监督审查adapter/固定输入/断言后单独放行。
本PR仅供监督验收和合并，不自行关闭Issue或宣称完整训练已可运行。
