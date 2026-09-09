# Issue 85 最小交付与研究终态

结论：`SEARCH_TERMINATED_NO_FINALIST`。唯一真实 Search 已消费 1/1；毛收益 −186.58 USDT，基础费用后 −200.89，含正常滑点 −208.05，敏感性成本后 −229.52。毛收益已负，成本进一步放大亏损。原生 DD 27.20%、每日收盘 MTM DD 27.74%，超过冻结15%研究预算。29完整交易、10活跃月通过容量门，集中度及去最好交易门失败。没有可进入 D 的 finalist，不从结果反推参数。

入口：[Research Console](http://127.0.0.1:55363/console)。当前 Search 终态明确；Development 候选 `BLOCKED_SECURITY`，按钮不可用，D/H/Stress 未运行。D 数据仅producer QC；H/Stress未采集。FreqUI与交易webserver `UNAVAILABLE`，不影响此原生研究入口；没有启动交易服务。

恢复：当前服务已运行，不要并行启动。服务退出后运行 `'/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-85-personal-spot-v1/restore-console.sh'`；完整固定参数见该文件。必须保留此worktree、指定native及下列Git外根；不重新初始化DB或重跑source/Search。固定代码 `b61cd799eda4a3ff28b92af71d06fbbfd1a7118e`，native `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`；[PR86](https://github.com/He1met/freqtrade-lab/pull/86) 已按监督授权合并，merge SHA `f3ada868f8ea737756b7a68227cfd1829086f600`；Issue85已关闭。原执行代码SHA不变，远端核验见`remote-delivery-receipt.json`。

数据库：`/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-85-personal-spot-v1/lab-v2.sqlite`。六表持久化映射：

| 表 | 行数 | 本轮含义 |
|---|---:|---|
| research_profiles | 1 | 冻结ETC spot Profile |
| generation_runs | 2 | Codex候选生成 + MANUAL来源Search终态投影 |
| candidates | 1 | 已批准源码，批准不代表有效 |
| research_runs | 0 | 无finalist，没有伪造D研究运行 |
| backtest_executions | 0 | Search原生ZIP在Git外，不伪装阶段Execution |
| releases | 0 | 无发布/交易授权 |

一次行政替代仅为旧库全局源码SHA唯一约束与非法大写family冲突。旧`lab.sqlite`保留未改行，旧Candidate `7a76a509-e260-43cd-9e79-13bf52c8c521`不再绑定本轮。新Candidate `c9e0400f-e155-4e29-82ec-12307cc6e4bb`、Generation `bde1c7db-d619-4cde-8737-28fea97cbc73`，Profile全字段和源码保持一致；关系见`console-receipt.json`。不是通用恢复机制。

证据（均在 `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-85-personal-spot-v1`）：

- `terminal-receipt.json`：终态/账本绑定；账本95非空记录、96物理行，原前缀字节保持；`freeze-receipt.json`和`proposal.md`保留冻结协议。
- `terminal-console-receipt.json`：最新实际API状态、按钮不可用及六表计数。
- `search-protocol-review.json`、`evaluate-search.py`：同一原ZIP、S数据、固定费用/滑点/权益/季度/月覆盖/52周bootstrap诊断，未新增native运行。
- 原ZIP：`/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-85-personal-spot-v1/search-campaign/search-results-round-1/c9e0400f-e155-4e29-82ec-12307cc6e4bb/raw/backtest-result-2026-09-06_00-36-41.zip`，SHA `23da1cbbd774ab121a2ad85fc016b9fc51a6361d172fca1f03411e62f959caa7`。
- `data-qc-receipt.json`：source760/S395/D394逐日连续、9公开请求与SHA；source=`source`，S=`search-campaign`，D=`development-pilot`。只采一次，无重试。

验证：固定venv producer/adapter187 passed无skip；新增spot与Generation/HTTP74 passed；最终no-finalist投影及合法finalist路径2 passed，监督独立复核通过。其余受影响回归见PR。合成native1/2，真实Search1/1，不重复运行。原始合成探针末端parser错误保留日志，同ZIP后续Profile-bound解析通过；派生synthetic fixture full parser仅证明该fixture。实际S原ZIP经生产Search路径验证；无D finalist，因此本次没有声称实际Development/import完整链已执行。现有single-baseline D仍需绑定artifact的API协议审阅，未扩建UI。
