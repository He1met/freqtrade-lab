# 固定真实意图窗的原生验收入口

本入口只消费 `carry_nonpaying` 在 **2026-09-08 17:00 至 2026-09-09 00:00 UTC** 的真实、提前持久化意图。最早输入就绪时间是 **2026-09-09 00:10 UTC（北京时间 08:10）**，仍需实际完整价格、mark、资金费查询收据和有效意图。日历到点并不等于数据就绪。`kind=acceptance`，探索变体 0，正常原生调用最多 1 次、1,800 秒；已知技术失败才可按 V3 针对同一候选/契约申请一次技术重试。未知中断不能直接重跑。

默认 CLI 只读，提前执行返回 `WAITING_DATA`、`data_sha256=null` 和 `native_calls=0`。它不占探索预算，也不评分经济性。原生计时器从 14:00 UTC 开始，前三小时只能空仓预载，保证第一笔 17:00 意图所需 168 个历史收益已齐；不改变候选公式和正式消费窗口。尾部原生 `force_exit` 是 23:00 UTC，不能改称午夜成交。

## 一次性设置路径

在已核验的 worktree 运行。以下路径均为专用研究目录，没有账户或凭据。设置禁止覆盖 shell 重定向；已有收据应先核对其状态，不能再次覆盖运行。

```sh
set -e
set -C
FTR_REPO=/Users/shenjianpeng/Documents/freqtrade-lab/.worktrees/btc-eth-perp-v1
FTR_PY=/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python
FTR_RUNTIME=/Users/shenjianpeng/Documents/freqtrade-lab-local/perp-autonomous-v1
FTR_POLICY="$FTR_REPO/docs/protocols/perp-autonomous-policy-v3.json"
FTR_REG="$FTR_REPO/docs/research/perp-carry-nonpaying-registration-v1.json"
FTR_PROTOCOL="$FTR_REPO/docs/protocols/perp-independent-confirmation-v2.json"
FTR_SIGNAL="$FTR_RUNTIME/forward-signals"
FTR_BINDING="$FTR_SIGNAL/observer-binding.json"
FTR_ART="$FTR_RUNTIME/forward-acceptance-v1"
FTR_TASK=perp-forward-native-acceptance-v1
cd "$FTR_REPO"
accept_args=(
  --registration "$FTR_REG" --confirmation-protocol "$FTR_PROTOCOL"
  --observer-binding "$FTR_BINDING"
  --seed-root "$FTR_RUNTIME/data/forward-warmup-v1"
  --incremental-root "$FTR_RUNTIME/data/incremental"
  --signal-root "$FTR_SIGNAL" --bundle-root "$FTR_RUNTIME/acceptance-inputs-v1"
  --output-root "$FTR_ART" --policy "$FTR_POLICY"
)
```

## 等待真实输入，再冻结一次

现有 heartbeat 先执行现有数据更新，再 `perp_forward_signal.py tick` 留存真实意图。只沿实际时钟追加，缺失/迟到记录保留，不为验收倒填。不要为这七小时另建 daemon。

```sh
"$FTR_PY" scripts/perp_forward_native_acceptance.py "${accept_args[@]}" --check-only
"$FTR_PY" scripts/perp_schedule.py --root "$FTR_RUNTIME/scheduler" --policy "$FTR_POLICY" status
```

只有只读检查返回 `READY_TO_FREEZE_INPUTS` 才执行以下冻结。`WAITING_DATA`、输入缺口、没有完整及时双币小时、SHA 不一致均应停在数据状态；不调用 native。冻结时将每个实际输入文件、原始 intent/receipt、输入快照和 manifest 绑定。保存的 `ready-preflight.json` 必须是实际输出，不能手写 `READY` 或未来数据 SHA。

```sh
mkdir -p "$FTR_ART"
"$FTR_PY" scripts/perp_forward_native_acceptance.py "${accept_args[@]}" --freeze-bundle > "$FTR_ART/ready-preflight.json"
"$FTR_PY" -c 'import json,sys; p=json.load(open(sys.argv[1])); assert p["status"]=="READY_NATIVE_ACCEPTANCE" and p["data_sha256"] and p["native_calls"]==0' "$FTR_ART/ready-preflight.json"
"$FTR_PY" scripts/perp_schedule.py --root "$FTR_RUNTIME/scheduler" --policy "$FTR_POLICY" materialize --task-id "$FTR_TASK" --preflight "$FTR_ART/ready-preflight.json" > "$FTR_ART/materialized-task.json"
```

`materialize` 只接受原来未开始的 `WAITING_DATA/FUTURE_INPUT_CONTRACT_PENDING` 任务，真实核验所有代码/输入 SHA，将原准备绑定及指纹留档后转为 `QUEUED`。它不消费原生额度，不容许更换冻结候选、窗口、代码或政策。已经冻结的 bundle 不重复冻结；如果文件存在，使用默认只读入口核验，审阅现有状态后继续尚未完成的一步。

## 单一 claim 和一次实际 native

```sh
"$FTR_PY" scripts/perp_schedule.py --root "$FTR_RUNTIME/scheduler" --policy "$FTR_POLICY" claim --task-id "$FTR_TASK" > "$FTR_ART/claim.json"
"$FTR_PY" -c 'import json,sys; t=json.load(open(sys.argv[1])); assert t["status"]=="RUNNING" and t["kind"]=="acceptance" and t["variants"]==0 and t["native_calls"]==1' "$FTR_ART/claim.json"
"$FTR_PY" scripts/perp_forward_native_acceptance.py "${accept_args[@]}" --execute --claim-json "$FTR_ART/claim.json" > "$FTR_ART/execution.stdout.log" 2> "$FTR_ART/execution.stderr.log"
```

消费者先保存不可重复的 reservation，禁用联网，再进入原生 Freqtrade。原有撮合、共享钱包、精度、1x、每侧 6bp taker+2bp 滑点现金费用和精确资金费保留。及时意图逐项与原公式对照；未留存的入场/退出信号禁止补齐。实际 native 入场必须对应同一小时同一方向的提前持久化意图。源、代码、policy 或快照在运行中改变会失败，不产生通过收据。

输出在 `forward-acceptance-v1`：`summary.json`、`report.zh.md`、`acceptance.json`、原生 ZIP、实际订单/资金费结果及绑定收据。报告只作工程判断，经济结果保持 null。至少一个完整及时双币小时且所有对账通过才有 PASS/LIMITED_PASS；零交易或缺失小时为 LIMITED_PASS，不能声称完整成交路径或盈利已确认。准备时间、原生时间、总时间分别留存，实际货币成本未知仍为 null。

## 完成登记，再单独激活

```sh
"$FTR_PY" scripts/perp_schedule.py --root "$FTR_RUNTIME/scheduler" --policy "$FTR_POLICY" finish --task-id "$FTR_TASK" --summary "$FTR_ART/summary.json" --report "$FTR_ART/report.zh.md" > "$FTR_ART/finished-task.json"
FTR_ACCEPTANCE_SHA=$("$FTR_PY" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$FTR_ART/acceptance.json")
"$FTR_PY" scripts/perp_forward_signal.py activate --root "$FTR_SIGNAL" --registration "$FTR_REG" --protocol "$FTR_PROTOCOL" --binding "$FTR_BINDING" --seed-root "$FTR_RUNTIME/data/forward-warmup-v1" --incremental-root "$FTR_RUNTIME/data/incremental" --runtime-policy "$FTR_POLICY" --native-acceptance "$FTR_ART/acceptance.json" --native-acceptance-sha256 "$FTR_ACCEPTANCE_SHA" > "$FTR_ART/activation.json"
```

只有通过/受限通过的原生收据、实际完整及时的双币预检、全部绑定一致且 **2026-09-10 00:00 UTC 前**才允许激活。激活也只是正式研究意图记录，不是交易或盈利准入。不要把 native 收据写回原始 observer-binding；它通过独立参数绑定，避免改写已有信号身份。若已过正式开始或验收受阻，保持未激活，保留原预约；不得倒签、顺延窗口或更换候选。

## 更新唯一下一任务

成功后唯一方向是固定候选的 90 日真实未来观察与期末单次确认，不再搜索另一组参数。正式执行器已实现为 `scripts/perp_forward_confirmation.py`，其独立策略为 `PerpForwardConfirmation`；固定窗口、激活、原始意图/资金费来源、稳定候选与窗口的单次预约，以及真实 scheduler claim 均有硬门。

按 [90 日确认终点入口](perp-forward-confirmation-runbook-v1.md) 的“成功验收后生成唯一后继任务”执行精确命令：在本次验收真实 `finish` 并成功激活后，读取正式 CLI 的真实 `WAIT_FORWARD` 输出冻结新 code bundle，生成 `kind=confirmation / variants=0 / native_calls=1 / max_seconds=2400` 的 `next-task.json`。`code_binding_role=ACTUAL_FROZEN_CONFIRMATION_EXECUTOR`；`data_binding_role=FUTURE_INPUT_CONTRACT_PENDING`，准备阶段 data SHA 只绑定真实冻结协议，不冒充未来市场数据。

现有 OPEN 任务未结束时不能 enqueue 第二项。后继登记后保持 `WAITING_DATA`；最早 2026-12-09 00:10 UTC 仍需真实完整输入，再使用独立 90 日入口 freeze/materialize/claim/execute/finish。七小时消费者继续只负责工程验收，不能用于90日经济评分。代码存在、合成门测试与 `WAIT_FORWARD` 回执也不是已完成正式原生确认的证据。

## 失败与中断

- 输入检查或冻结前失败：native=0，任务保持未开始；记录具体缺口，继续不受阻的真实观察。没有未来数据时不轮询调用原生。
- 已领取但进入原生后失败：保留 reservation、错误日志、`BLOCKED_RUNTIME` 摘要和中文报告，先 `finish` 登记该次，再决定是否满足 V3 唯一具体技术重试。不得换名字重置预算，或因结果不好重试。
- 进程中断/结果未知：保留 `RUNNING/UNKNOWN_INTERRUPTED`，先核实际进程已停、是否已有 ZIP/结果，留下 `verified_process_stopped` 的真实依据再对账；不能直接重跑或补写成功。
- 预算或 single-writer 锁拒绝：不启动 native，保留现有排队和计数，不绕过锁。0 变体不代表无限工程调用。
- SHA 或候选身份不符：停止对应步骤，保留旧证据。不修改冻结原件去“修好”校验；必要的新工程版本必须显式记录前后绑定与真实原因。

本入口的运行证据与 scheduler 自动唤醒证据分开。人工/用户触发的通过不能声称已证明无人值守自动闭环。
