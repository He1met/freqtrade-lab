# Issue #93：一次源采集与S准备完成，Search未运行

**READY_FOR_SUPERVISOR_SEARCH_REVIEW_NOT_AUTHORIZED**。[Issue #93](https://github.com/He1met/freqtrade-lab/issues/93)保持OPEN；仅等待监督核证后放行一轮一次Search。[完整机器回执](/Users/shenjianpeng/.codex/runs/freqtrade-lab/ltc-volume-liquidity-rebound-v1/cohort-20260906-0454/source-ready.json) SHA `a3cbe5fa19515b866912afe5656ce67122396a56a32c1b4bc6262c33ed795a81`。

- 根目录：`/Users/shenjianpeng/.codex/runs/freqtrade-lab/ltc-volume-liquidity-rebound-v1/cohort-20260906-0454`。
- 一次采集：**15/24次实际HTTP**，无重试；1381行 `[2021-03-22,2025-01-01)`。S隔离1015行 `[2021-03-22,2024-01-01)`，含40根前史，真正S评分起点2021-05-01。
- QC：精确UTC日连续、confirm及基础币volume由producer验证，有限正OHLCV及OHLC关系、raw→Feather与SHA通过。模型未读取D经济值；H未采封存。[QC回执](/Users/shenjianpeng/.codex/runs/freqtrade-lab/ltc-volume-liquidity-rebound-v1/cohort-20260906-0454/source-consumer-qc.json)。
- 静态validator：37根依赖≤40前史；纯合成检查覆盖t+1入场/t+3退出、3日Q去重、liq门、前缀因果性和会计顺序。无native smoke。[合成检查](/Users/shenjianpeng/.codex/runs/freqtrade-lab/ltc-volume-liquidity-rebound-v1/cohort-20260906-0454/synthetic-checks.json)。
- 真实Profile `3df8a653-256e-4c3c-a436-bbfc68284a6b`；批准Candidate `5e9f5c5c-bc9e-4488-971d-800375b82504`；Generation `5becaa82-2acd-495f-9c1d-d224e2c9f38f`。六表计数 **1/1/1/0/0/0**；逻辑快照包含批准状态与策略字节，没有依赖WAL不完整的主DB SHA。
- 计划campaign `8d8fb912-cd54-42d2-8d89-70b2dea155c3`，actual campaign **NULL**。没有finalist或ResearchRun。全局账本只追加冻结预留及source/QC两个记录；均保留旧前缀，最新96819字节/SHA `17a731bd6278b3eb8386edb4fe91957422e892da3b9bcbbe78e81a963f0c75ee`，未记经济消费。
- [实际Research Console](http://127.0.0.1:52800/console)与两个GET preflight均200。Search `READY/SEARCH_READY`，active_attempt_limit=1、已用0、remaining=1；页面公共硬上限6不是追加授权。总体 `NOT_READY`：D为`Pilot spec unavailable`，FreqUI为`UNAVAILABLE/WEBSERVER_UNREACHABLE`，H/Stress仍封存。
- checkout仅3c7c切至已核`7ae2b6b6c45cfb57c40a13dccd697ce1c57d08a4`，项目业务代码/native/Schema无修改。原生commit `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`。

| 冻结／来源 | SHA-256 |
|---|---|
| 最终策略 | `b90e501888af817cf9f96c91399f3d9178f31ee5df4b33640c9c281d01e2c944` |
| 协议 | `b64d0193b252a5f94e361ea63465e8a276a2152a0221e3fce4307c32648d11d2` |
| 运行配置 | `4986b055bd5ab937a377293bdb9bc58a2597d2ab0e65f15d937a44a2db9529a8` |
| Profile快照 | `0a89ba30a3d35e02381992f204c59b28f5b851f60186b6b1981c03f89058d6ef` |
| 批准逻辑快照 | `777994244a384ab0f17f00ea57ee21f7fc2e8782b49994d66b6dd02e9180f90a` |
| freeze-receipt | `fc9e8987638d28007ee10d58a27f1b12d90e8ff7042dd465d75b2029d262c7cd` |
| 源provenance | `442fda19c928db8afd917b9475a2847f5accdef7dba95e66bd18f7a954ac4ae8` |
| 源retrieval receipt | `53c14711e22fe4c6cdb751e34804b2b9379b2196b94b976084f32237ec7c52d8` |

[最终协议](/Users/shenjianpeng/.codex/runs/freqtrade-lab/ltc-volume-liquidity-rebound-v1/cohort-20260906-0454/protocol.md)明确：原生已反映跳空不重复扣损，MTM清算准备只减未平仓估值，同bar新仓先买后卖；集中度块不是IID证据，CI仍用完整日序列。所有数值门与交易规则保持原提案。条件反转家族相关性与volume独立贡献未证明，工程与QC不证明盈利。

准备中两项本地执行修正已留痕：QC改为比较UTC时间点（Feather为ms、pandas为us，实际日期完全相同）；第一次prepare CLI缺少已有冻结D参数，在创建输出前拒绝，补全后成功，旧命令/日志保留。另一次Console启动在目录缺失时拒绝后补建隔离目录启动。**没有再次采集，没有native或Search重放。**

