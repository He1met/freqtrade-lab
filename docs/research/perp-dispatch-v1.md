# 双待办、单写入调度追加版本

本版本落实 Issue #162 的新增授权：长期固定确认的 `WAITING_DATA` 可与唯一优先的短期开发研究并存，最多两个活跃机制，仍只有一个市场研究 writer。没有新增服务或数据库表。

`lab/perp_schedule.py`、原 V3 budget policy、原观察器、7 小时验收及 90 日确认 consumer 保留原字节。新 `lab/perp_dispatch.py` 复用同一 `scheduler/writer.lock`、原终态报告核验和原状态文件；V3 的每日 8 / 每周 28 个经济变体预算、每三轮终态检查点、一次正式确认及其 2400 秒上限保持。原 `WAITING_DATA` task 的 ID、窗口、候选和 code/data/policy SHA 不被迁移或替换。

## 安装与活动入口

只在原 writer 已核清、无 `RUNNING` / `UNKNOWN_INTERRUPTED` 时执行一次：

```sh
python scripts/perp_dispatch.py \
  --root /Users/shenjianpeng/Documents/freqtrade-lab-local/perp-autonomous-v1/scheduler \
  --policy docs/protocols/perp-autonomous-policy-v3.json \
  --dispatch-policy docs/protocols/perp-dispatch-policy-v1.json install
```

安装写入不可变 `dispatch-bindings/<dispatch-policy-SHA>/before-state.json` 和 `binding.json`，状态中仅追加 `dispatch_binding` 引用。回执记录原任务数组 SHA；原报告、预算、任务和 policy 绑定不改写。已有相同安装幂等返回；代码漂移或快照冲突停止，不覆盖哈希。

同样三个路径参数下：`status` 核版本与状态；`enqueue --task-json <文件>` 登记唯一短期研究；`claim --task-id <ID>` 在同一写锁内核验并占用实际 writer。活动流程不再用旧 CLI 的 enqueue / claim。原 tick / 采集、observer、finish、未来 materialize 和正式 consumer 仍使用原 V3 policy 与共享写锁，不另建自动化。

每轮先执行必要采集和及时意图留存，再考虑 claim。启动前读取规范路径下已提交的 capture 与 observer 原件，核 SHA、候选身份、完整性和真实发布时间；这些信息仅作运行健康门。研究输入不接收确认期的信号方向、价格、交易或收益。预留声明的 `max_seconds` 加 300 秒安全余量，必须严格早于下次小时结束后 10 分钟的维护期限；不足时本轮延期。到期或将在该时段内到期的确认优先。`UNKNOWN_INTERRUPTED` 始终排他，不能自动重跑。

正式窗口结束后，如果没有仍 OPEN 的确认，不再要求已经停止的 observer 产生新小时槽；必要数据维护仍保留。确认未完成且已到期时，研究仍被优先级门阻止。

## 研究输入与实际执行复核

开发 manifest 的最小格式如下，所有路径均为绝对路径：

```json
{
  "schema": "perp-development-inputs-v1",
  "use": "EXPOSED_DEVELOPMENT_ONLY",
  "runtime_root": "/absolute/runtime",
  "window": {
    "start": "2025-01-01T00:00:00+00:00",
    "end_exclusive": "2026-07-01T00:00:00+00:00"
  },
  "files": [
    {"path": "/absolute/runtime/data/first-capture-v1/BTCUSDT-ohlcv.jsonl", "sha256": "ACTUAL_SHA", "role": "market", "time_field": "event_time"},
    {"path": "/absolute/runtime/data/first-capture-v1/receipt.json", "sha256": "ACTUAL_SHA", "role": "metadata"}
  ]
}
```

`data_sha256` 与 `development_manifest_sha256` 都是该 manifest 原始字节 SHA；task 还需 `development_manifest_path`、实际 `code_bindings` 与对应代码 bundle SHA。允许源根仅为当前 runtime 的 `data/first-capture-v1` / `data/cm-supplement-v1`；逐个实际 market 行解析 `event_time` / `time`，并同时检查存在的 `cost_time`，拒绝开发窗以外或与冻结确认窗相交的数据。JSONL 逐行解析；CM 原始对象可显式 `rows_key: "data", time_field: "time"`。没有可靠行结构则阻断。

元数据只允许这两个源根直接子文件 `receipt.json` / `instrument-rules.json`；合约规格必须只有 BTCUSDT / ETHUSDT 的 USDT 线性永续。当前 fetched 元数据不被误当历史经济时间，也不证明历史合约规格具有 PIT。协议和代码另用 code bindings 绑定，不能作为 manifest 元数据引入 docs 下未来报告。增量、forward-warmup、forward-signals、forward-confirmation 及 symlink 越界全部拒绝。

准备期调用 `validate_development_manifest(path, sha, dispatch_policy_path)` 不需要安装或写入状态。登记及 claim 重验全部实际输入；manifest 改名、增加描述或改变 JSON 排版不会重置相同源文件实验身份。

研究 runner 在已经持有原 `perp_schedule.locked` 后调用 `validate_running_admission(root, state, current_task, budget_policy_path, dispatch_policy_path, now)`。此接口不再次取锁；核真实唯一 RUNNING、版本、时间、全部实际开发输入和当前维护余量。runner 仍负责实际 native 次数和超时限制、不可重复的执行预约、结束前 code/data/policy 漂移复核，以及真实 summary/report；dispatch claim 本身不代表已经执行研究。

## 验证

2026-09-09：新 dispatch 16 项合成测试和原 scheduler / V3 / tick 回归合计 **56 passed**。覆盖双待办限制、旧新写锁、UNKNOWN 排他、确认优先、缺失/迟到意图、维护余量、实际未来时间与路径/元数据越界、claim→执行漂移、重复 manifest、累计预算及终态失败检查点、正式窗口结束后的观察器交接。测试没有 HTTP 或 native 市场执行。

真实只读维护校验于 `2026-09-09T00:41:45.983411+00:00` 成功：已提交数据结束于 `00:00Z`，当前及时意图计划 `01:00Z`，下一维护为 `01:10Z`；`max_seconds=900` 当时有足够余量。该观测不安装调度、不 claim、不运行研究。此文档不是之后时点的维护许可，实际启动必须重新核验。

## 实际承接与状态

活动 heartbeat `freqtrade-lab-2` 已于2026-09-09更新：必要 tick → 及时 observer → 新 dispatcher claim → 已冻结 runner → 原 finish → 中文报告 → 唯一有依据的后继审查。条件通过后在同次调用承接，不再等下一半小时心跳或日历排序。出现已有预约、RUNNING 或未知中断先核原产物，禁止重放。已通过的定向检查没有新改动或未决风险时不重复扩大。

只读入口 `scripts/perp_research_status.py` 使用相同 `--root`、`--policy`、`--dispatch-policy` 参数。它不采集、不 claim、不执行，也不输出确认信号方向或价格收益。确认预约、观察健康、实际计算与短期探索分别呈现；可传 `--next-review-json` 读取独立后继审查的状态和原因。六项合成检查通过；实际状态仍以当前原件为准。
