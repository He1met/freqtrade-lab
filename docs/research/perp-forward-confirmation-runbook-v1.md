# BTC/ETH 固定 90 日确认终点入口

正式确认入口是 `scripts/perp_forward_confirmation.py`，策略为 `PerpForwardConfirmation`。冻结窗口保持 **2026-09-10 00:00 至 2026-12-09 00:00 UTC**，最早检查实际输入为 **2026-12-09 00:10 UTC（北京时间 08:10）**。提前调用返回 `WAIT_FORWARD`、`data_sha256=null`、`economic_result=null`、`native_calls=0`，在此之前不读取实际行情、激活状态或未来信号文件，也不导入原生执行器。

本入口复用冻结公式、原生 Freqtrade 装配、共享钱包和费用对账，不提供撮合替代物。只有提前激活的固定候选可消费完整 2160 小时、4320 个双币时槽；缺失和迟到保留，未发生的机会不造交易。最后 72 小时先应用原协议禁新开仓规则，再与真实提前留存的 `NO_TRADE` 对照，正常退出仍有效。

## 路径与预算

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
FTR_CONFIRM_ART="$FTR_RUNTIME/forward-confirmation-v1"
FTR_CONFIRM_TASK=perp-forward-confirmation-v1
cd "$FTR_REPO"
confirm_args=(
  --registration "$FTR_REG" --confirmation-protocol "$FTR_PROTOCOL"
  --observer-binding "$FTR_BINDING"
  --seed-root "$FTR_RUNTIME/data/forward-warmup-v1"
  --incremental-root "$FTR_RUNTIME/data/incremental"
  --signal-root "$FTR_SIGNAL"
  --native-acceptance "$FTR_RUNTIME/forward-acceptance-v1/acceptance.json"
  --bundle-root "$FTR_RUNTIME/confirmation-inputs-v1"
  --output-root "$FTR_CONFIRM_ART" --policy "$FTR_POLICY"
)
"$FTR_PY" scripts/perp_forward_confirmation.py "${confirm_args[@]}" --check-only
```

`kind=confirmation`，`variants=0`，`native_calls=1`，独立上限 2400 秒；不消费探索变体，不容技术重试、改名或更换输出目录再跑。实际执行需当前 scheduler 中的 `RUNNING` 任务，而不仅是外部 claim JSON。持有同一 scheduler writer 锁，稳定经济候选与规范 UTC 窗口的 reservation 在调用原生之前持久化。进程或结果未知时保留原预约，先对账，不能重放。

## 成功验收后生成唯一后继任务

先按照 [7 小时验收入口](perp-forward-acceptance-runbook-v1.md) 完成原生消费者验收、真实 `finish` 和 **2026-09-10 00:00 UTC 前**的激活。现有任务未终结时不能 enqueue 第二个 `OPEN` 任务。这里生成的是已存在的正式执行器准备绑定，未来输入仍是明确的待取得契约。

```sh
mkdir -p "$FTR_CONFIRM_ART"
"$FTR_PY" scripts/perp_forward_confirmation.py "${confirm_args[@]}" --check-only > "$FTR_CONFIRM_ART/preparation-check.json"
"$FTR_PY" - "$FTR_REPO" "$FTR_RUNTIME" "$FTR_CONFIRM_ART" <<'PY'
import hashlib,json,sys
from pathlib import Path
from datetime import datetime,timezone
repo,runtime,out=map(Path,sys.argv[1:]);pre=json.loads((out/'preparation-check.json').read_bytes())
reg_path=repo/'docs/research/perp-carry-nonpaying-registration-v1.json'
protocol_path=repo/'docs/protocols/perp-independent-confirmation-v2.json'
reg=json.loads(reg_path.read_bytes());protocol=json.loads(protocol_path.read_bytes())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert pre['status']=='WAIT_FORWARD' and pre['execution_class']=='confirmation' and pre['data_sha256'] is None and pre['native_calls']==0
for name,value in pre['code_bindings'].items():assert sha(repo/name)==value
state=json.loads((runtime/'forward-signals/state.json').read_bytes())
assert state['active'] is True and state['identity']['registration_sha256']==sha(reg_path)
assert datetime.fromisoformat(state['activated_at'])<datetime.fromisoformat(protocol['window']['start_inclusive'].replace('Z','+00:00'))
task=dict(id='perp-forward-confirmation-v1',kind='confirmation',status='WAITING_DATA',
  mechanism='carry_nonpaying_fixed_90day_confirmation',hypothesis='固定候选的90日真实提前意图与原生终点确认；不在观察期重选或提前评分。',
  variants=0,native_calls=1,max_seconds=2400,fixed_candidate=True,economic_selection=False,changes_economic_rules=False,
  code_sha256=pre['code_sha256'],code_binding_role='ACTUAL_FROZEN_CONFIRMATION_EXECUTOR',
  executor='scripts/perp_forward_confirmation.py',code_bindings=pre['code_bindings'],
  policy_sha256=pre['policy_sha256'],candidate_sha256=sha(reg_path),
  frozen_contract_path=str(protocol_path),frozen_contract_sha256=sha(protocol_path),
  fixed_input_window=dict(start=protocol['window']['start_inclusive'],end_exclusive=protocol['window']['end_exclusive']),
  data_sha256=sha(protocol_path),data_binding_role='FUTURE_INPUT_CONTRACT_PENDING',
  future_data_note='data_sha256 only binds the real frozen future-input contract; no future market data SHA is claimed.',
  earliest_expected_input_ready_at=pre['earliest_ready_at'],prepared_at=datetime.now(timezone.utc).isoformat())
with (out/'next-task.json').open('x') as f:json.dump(task,f,ensure_ascii=False,indent=2);f.write('\n')
PY
"$FTR_PY" scripts/perp_schedule.py --root "$FTR_RUNTIME/scheduler" --policy "$FTR_POLICY" status
"$FTR_PY" scripts/perp_schedule.py --root "$FTR_RUNTIME/scheduler" --policy "$FTR_POLICY" enqueue --task-json "$FTR_CONFIRM_ART/next-task.json" > "$FTR_CONFIRM_ART/enqueued-task.json"
```

在冻结观察期间只继续已有数据与及时意图留存，不调用 native，也不以途中收益改变候选、样本门或窗口。第一次自动触发及真实下次触发须单独的 provider 元数据证明，以上命令与 `ACTIVE` 配置都不能证明它们。

## 终点形成真实输入，随后仅一次执行

时间门结束后仍需完整 OHLCV、mark、资金费查询覆盖和所有原始 intent/receipt 的身份与 SHA。无资金费事件的小时必须有成功的查询覆盖证据，不能把缺查询补为零。原始文件在快照中不得改写或选择性删去。

只读入口返回 `READY_TO_FREEZE_INPUTS` 后执行以下冻结。为兼容已有 scheduler，实际预检的 wire status 是 `READY_NATIVE_ACCEPTANCE`，但必须同时是 `execution_class=confirmation` 和 `readiness_label=READY_NATIVE_CONFIRMATION`；它明确绑定完整 90 日，不能拿 7 小时数据替代。

```sh
"$FTR_PY" scripts/perp_forward_confirmation.py "${confirm_args[@]}" --freeze-bundle > "$FTR_CONFIRM_ART/ready-preflight.json"
"$FTR_PY" -c 'import json,sys; p=json.load(open(sys.argv[1])); assert p["status"]=="READY_NATIVE_ACCEPTANCE" and p["readiness_label"]=="READY_NATIVE_CONFIRMATION" and p["execution_class"]=="confirmation" and p["data_sha256"] and p["native_calls"]==0' "$FTR_CONFIRM_ART/ready-preflight.json"
"$FTR_PY" scripts/perp_schedule.py --root "$FTR_RUNTIME/scheduler" --policy "$FTR_POLICY" materialize --task-id "$FTR_CONFIRM_TASK" --preflight "$FTR_CONFIRM_ART/ready-preflight.json" > "$FTR_CONFIRM_ART/materialized-task.json"
"$FTR_PY" scripts/perp_schedule.py --root "$FTR_RUNTIME/scheduler" --policy "$FTR_POLICY" claim --task-id "$FTR_CONFIRM_TASK" > "$FTR_CONFIRM_ART/claim.json"
"$FTR_PY" scripts/perp_forward_confirmation.py "${confirm_args[@]}" --execute --claim-json "$FTR_CONFIRM_ART/claim.json" > "$FTR_CONFIRM_ART/execution.stdout.log" 2> "$FTR_CONFIRM_ART/execution.stderr.log"
"$FTR_PY" scripts/perp_schedule.py --root "$FTR_RUNTIME/scheduler" --policy "$FTR_POLICY" finish --task-id "$FTR_CONFIRM_TASK" --summary "$FTR_CONFIRM_ART/summary.json" --report "$FTR_CONFIRM_ART/report.zh.md" > "$FTR_CONFIRM_ART/finished-task.json"
```

已有 bundle、preflight 或 reservation 不覆盖。输入不完整时保留 `WAITING_DATA/BLOCKED_DATA` 的真实理由；已经领取的失败或未知执行先保留摘要及预约并完成状态对账，不自动重试。成功发布前重新核验全部代码、源文件、政策、manifest、snapshot 和 native 产物 SHA。正常结束后本窗口终结，不自动追加日期等待转正。

## 报告与证据限制

产物包括中文报告、机器摘要、2161 个完整小时盯市点、逐日及 30 日阶段收益、真实原生 ZIP/订单/退出记录。费用保持每侧 6bp taker＋2bp 滑点现金预算和精确真实资金费；同成交压力场景额外每侧 4bp，仅算术敏感性。

及时覆盖分母固定 4320；不足 95% 或按窗口起点锚定的共同 72h 非空簇少于 12，优先为 `UNDERPOWERED`。随后按冻结优先级报告 `GROSS_NOT_SUPPORTED`、`COST_NOT_SUPPORTED` 或 `CONFIRMATION_POSITIVE_LIMITED`。20% 为独立风险目标，略超不机械淘汰；达到 30% 必须 `RISK_RECALIBRATION_REQUIRED`，无实盘风险扩张权限。

按原协议将 2160 个小时 log-return 分为 30 个同步 72h 块，保留零暴露块，Python MT19937 固定 seed=162、2000 次有放回重采样，报告条件路径 95% 区间。首小时相对初始空仓 1000 USDT，纳入开始时的入场成本。缺失、非有限或非正权益保留 `UNKNOWN`，不删块；该区间不表示未来盈利概率，也没有重跑账户。

原生最后可用 K 线为终点前一小时；每笔实际持仓严格核验不超过 72h，结合尾 72h 禁新入场，最后一小时应已空仓。若发生 `force_exit`，保留其真实时间，不改称午夜成交或拼接收益。实际价差冲击、真实小时内风险及需要额外原生对照的 same-availability comparator 保留 `UNKNOWN`。这些限制写入报告，本单窗口不给通用经济资格或实盘许可。当前仅验证实现与门禁，尚无 90 日市场/native 评分证据。
