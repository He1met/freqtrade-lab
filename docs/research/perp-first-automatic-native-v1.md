# 首次真实自动原生验收与 90 日观察交接

2026-09-09 UTC，本项目首次由真实 Codex provider heartbeat 完成“唤醒 → 采集 → 意图记录 → 输入冻结 → claim → 单次原生验收 → 报告登记 → 激活 → 唯一后继入队”。结果为 **LIMITED_PASS**：固定 7 小时中的双币意图全部完整、及时，但没有入场信号与交易。因此只证明有限工程一致性，经济结果为 `null`，没有新增盈利证据。

现货和其他币研究仍归档；活动范围只含 BTC/ETH USDT 线性永续、1h、研究假设 1x。冻结代码、候选公式、经济协议和风险目标均未修改。约20%仍是研究风险目标，不因略超机械淘汰，也没有扩展账户、订单或实盘权限。

## 本轮真实证据

| 项目 | 结果 |
| --- | --- |
| 自动来源 | `freqtrade-lab-2`；provider 时间 `2026-09-09T00:07:23.801Z` |
| 当前实际 turn | `01a0837d-a19a-7a83-98ab-f9671be727c1` |
| 公开增量采集 | 17 GET；完整至 `2026-09-09T00:00Z`；必要字段齐备，无错误/延期 |
| 工程消费窗口 | `2026-09-08T17:00Z` 至 `2026-09-09T00:00Z`，7/7 双币小时，14 个及时 `NO_TRADE` |
| 原生执行 | 1 次，exit 0；入场 0、仓位周期 0、订单 0；技术重试 0 |
| 输入与产物 | 124 个来源文件、manifest、snapshot、全部冻结代码和原生 ZIP 的 SHA 均核验通过 |
| 核账 | 8 个小时边界钱包点均为 1,000 USDT、空仓；原生导出与独立只读解码一致 |
| 资金费 | 查询覆盖完整；窗口内实际结算事件为 0，未将缺失查询补零 |
| 经济证据 | `economic_validation=false`、`economic_result=null`；零交易不能证明非零成交与持仓费用路径 |

原生计时器包含 14:00–17:00 的空仓预载；正式消费窗口未扩展。最后实际原生 K 线是 23:00 UTC，没有虚构午夜成交。原始引擎表格中的零收益只表示本次空仓结果，不是有充分样本的策略收益结论。

外层临时编排脚本曾对包含 Freqtrade 表格和末尾 JSON 的整个 stdout 调用 `json.loads`，因此报 `JSONDecodeError`。原生子进程已 exit 0，现有 summary、acceptance、ZIP 均完整。保留错误与原始 stdout/stderr后，仅从磁盘核验结果并完成登记；没有重跑原生，也没有把它记作可用来补交易的技术失败。后续自动入口明确从已验证产物读取执行结果。

## 实际激活与唯一队列

验收在 `2026-09-09T00:18:25.718657Z` 登记为 `COMPLETED`；研究意图于 `2026-09-09T00:19:18.291814Z` 激活，早于正式开始。激活单独引用实际 acceptance SHA，未改写原始 observer binding。已有 9 个小时、18 个币种时槽仍属于准备期，正式覆盖率的已观察分子为 0。

唯一 OPEN 任务已是 `perp-forward-confirmation-v1 / WAITING_DATA`，预算为 0 探索变体、最多 1 次确认调用、2,400 秒；尚未 claim、没有确认 reservation，实际正式确认调用 **0**。队列中的 `native_calls=1` 是将来上限，不能统计成已经执行。

固定窗口为 **2026-09-10 00:00 至 2026-12-09 00:00 UTC**，最早输入检查为 12 月 9 日 00:10 UTC（北京时间08:10）。正式入口真实返回 `WAIT_FORWARD`，未来市场数据 SHA 和经济结果均为空。准备任务的 data SHA 仅绑定已经存在的冻结协议，角色明确为 `FUTURE_INPUT_CONTRACT_PENDING`。

唯一优先方向是继续记录同一 `carry_nonpaying` 候选的真实及时意图，期末只运行一次完整确认。覆盖率分母固定4320、最低95%；至少12个非空同步72小时簇；最后72小时禁止新开仓；每侧6bp taker、2bp滑点和真实资金费不变。日常检查不提前评分、不更换参数、不回放已曝光历史，也不因为每日额度恢复而新增候选。缺失和迟到留存，不能倒签、补为及时信号或延长窗口等结果转正。

## 调度、预算与验证

唯一 `freqtrade-lab-2` heartbeat 保持30分钟且实际 prompt 已更新到正式观察阶段，保存配置读回后与仓库文本精确匹配；旧 `freqtrade-lab` cron 与 `automation-2` heartbeat 均仍为 `PAUSED`。首次自动唤醒原件保持不变，本次自动 native 链单独留档。provider 自有 trigger ID 与下次触发时间不可见，保留 `null`；本地 `trigger_id` 使用实际 turn 作关联，不冒称 provider ID。应用退出、休眠、断网或额度不足后的恢复只追加真实观察，不能补造过去的及时信号。

独立调度审计确认旧3轮、8个已执行开发变体及两次政策迁移快照完整保留；2026-09-09 UTC探索使用0/8，本UTC周使用8/28。本次单列新增1次工程验收，累计真实开发调用8、工程验收1、正式确认0，市场重试0。未启动其他研究 writer，没有新增表、后台服务或原生执行代码。

本次对真实入口、失败恢复、不可变来源、原生产物、激活时序、唯一队列和实际自动配置完成核验，两名独立审阅者分别复核原生证据和调度交接。只修改状态资料、报告、README索引与自动提示词；未因文档更新重复已有回归测试或合成/native运行。

## 耗时与证据位置

排队与自然等待合计26,952.789秒，包含等待冻结真实窗口；原生输入准备1.953秒、原生计算0.277秒、消费者总耗时2.237秒、外层进程2.403秒。claim至finish为339.723秒，包含输出解析问题核对及报告登记，不能全部称为计算时间。独立审阅的精确耗时、模型token、CPU秒和货币费用不可得，保持 `null`。

- [机器摘要](perp-first-automatic-native-v1.summary.json) 保存全部命令回执路径、时间与SHA。
- 实际链证明：`/Users/shenjianpeng/Documents/freqtrade-lab-local/perp-autonomous-v1/migration/automatic-native-observed-v1.json`。
- 原生产物：`/Users/shenjianpeng/Documents/freqtrade-lab-local/perp-autonomous-v1/forward-acceptance-v1/`。
- 后继任务与真实等待回执：`/Users/shenjianpeng/Documents/freqtrade-lab-local/perp-autonomous-v1/forward-confirmation-v1/`。
- [90日执行入口](perp-forward-confirmation-runbook-v1.md)；[既有8个开发结果与成本限制](perp-optimization-v3.md)。

[Issue #162](https://github.com/He1met/freqtrade-lab/issues/162) 与 [PR #164](https://github.com/He1met/freqtrade-lab/pull/164) 保持 OPEN，未完成项是未来固定窗口及期末确认。本次工程通过没有改变既有候选“有限开发支持”的判断，也没有产生合格盈利策略。
