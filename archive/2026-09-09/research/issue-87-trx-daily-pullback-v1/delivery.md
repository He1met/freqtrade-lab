# Issue 87 terminal delivery

**SEARCH_TERMINATED_NO_FINALIST。TRX日线反转这一固定假设停止；没有找到合格策略。** 2024 S仅一次，22笔完整交易，技术VALID。毛收益约−3.01%，基础费后−52.07760255 USDT（−5.21%），基准滑点后−63.06254869 USDT（−6.31%），高成本−85.03244098 USDT。基准PF0.76999；native DD11.195%、成本后close DD12.537%，均超10%门。覆盖四季但仅一季净正，所有AND门总体失败。没有调参、换币、重放或D。

- Console：http://127.0.0.1:58857/console
- 原ZIP：search-data/search-results-round-1/abe16b74-12e4-48bf-867a-20e0d290c115/raw/backtest-result-2026-09-06_01-38-57.zip；SHA256 432d36bb343e32d3a7829155abb0057187f83592415344b537eea7d6333136d2。
- 固定附加门：search-economic-audit.json；明细曲线search-daily-equity.json，无新增回测。low日内路径无法定位，诊断NULL且不是硬门。
- 终态：terminal-receipt.json；账本追加凭据ledger-terminal-append-receipt.json。所有本页相对路径基于 /Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-87-trx-daily-pullback-v1。
- 数据库lab.sqlite：research_profiles=1、generation_runs=2（真实CODEX与原生MANUAL Search终态投影）、candidates=1、research_runs=0、backtest_executions=0、releases=0。原生JSON精确投影保持不改；补充审计通过终态receipt及ledger关联原ZIP。
- 预算：一次采集、9 HTTP（8日线页）、零重试；唯一S1/1，剩余0。D仅producer QC，模型未读D市场值/结果、未运行D；H未采集，H/Stress/Release未运行。

当前服务正在运行。只有服务退出后才运行本目录restore-console.sh，保留原DB/root，禁止重新初始化或重新执行采集/Search。服务使用指定native venv Python和显式PYTHONPATH；服务入口仍为58857。CODEX Generation用gpt-6-astra，应用内reasoning/tier未知；执行任务medium由创建配置指定。

worktree /Users/shenjianpeng/.codex/worktrees/42b5/freqtrade-lab，分支codex/issue-87-trx-daily-pullback-v1，HEAD f3ada868f8ea737756b7a68227cfd1829086f600，业务代码无改动、无PR。监督验收后授权关闭Issue87；最新远端读取确认2026-09-06T01:55:33Z CLOSED，见issue-close-receipt.json。冻结终态receipt保留其验收前OPEN状态，不追改历史证据。

初期误读与截断记录、#30实际receipt/执行SHA缺失的合同级避让推断完整保留在 /Users/shenjianpeng/.codex/runs/freqtrade-lab/spot-proposal-42b5-20260906/。本次负结果不能抹除该残余不确定；也不否定所有反转族。本批已停止，不自动开启下一假设。
