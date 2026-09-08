# 首次真实自动 heartbeat 验证

2026-09-08 **17:43:52.484 UTC（北京时间9月9日01:43:52）**，Codex provider实际发出 `freqtrade-lab-2` heartbeat。当前任务API同时返回运行中的turn `01a0821e-81a6-7bf0-90db-2ae25450457f`，其首项为provider的 `automation_update` 输出事件。这次是已验证的自动来源，不是用户或监督任务发送消息，也不是按30分钟间隔推算。

只确认自动唤醒、实际入口执行和真实时间门检查。**自动领取→原生验收→报告→后继的完整流程尚未发生，候选未激活，也没有新增盈利证据。** 原V3交付报告中的UNKNOWN是交付当时的快照，本报告追加新的触发证据。

| 实际步骤 | 结果 | 新增GET | 原生调用 |
|---|---|---:|---:|
| `perp_tick.py` | 同小时NO_OP，必需字段完整，源数据截至17:00 UTC | 0 | 0 |
| `perp_forward_signal.py tick` | 仍为2小时/4pair-hours，17:00与18:00的原始收据SHA不变 | 0 | 0 |
| `perp_forward_native_acceptance.py --check-only` | `WAITING_DATA`，未来数据SHA仍null | 0 | 0 |

三个实际入口耗时分别为0.064秒、0.042秒、1.486秒。启动后的状态核对、报告和工具协调耗时与这些脚本计算时间分开记录；精确模型费用和CPU时间不可得，保持null。历史原生调用仍8次、市场重试0次，本次没有领取新名额，V1/V2/V3已使用预算保留。

唯一后继仍 `perp-forward-native-acceptance-v1`，0探索变体、1次原生调用上限，等待事前固定17:00–00:00 UTC真实意图窗，最早 **2026-09-09 00:10 UTC（北京时间08:10）**且实际输入齐备后执行。本次没有换窗、提早领取或回填意图。90日确认仍未激活，日期及判据不变。

来源链已保存在Git外 `migration/activation-observed.json` 和同turn的 `heartbeat-receipts`，每一步输出、时间和状态前后快照有SHA。实际turn id作为本地关联 `trigger_id`；provider没有另外提供trigger id或下一次执行时间，两者保持null，不能把本地关联ID冒充provider字段。

当前活动知识库已更新为 `AUTOMATIC_WAKE_AND_READINESS_CHECK_VERIFIED`，完整自动原生流程仍待验证；Issue #162保持OPEN。未新增调度、writer、账户操作或订单。后续普通重复检查保持安静，只在新结论或可行动失败时通知。
