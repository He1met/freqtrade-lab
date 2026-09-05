# 单基线 Search 与 Development 交接

`SINGLE_BASELINE_V1` 是事前选择的一条 seed、一轮、一次 Search attempt、零 child 模式。默认两轮 Profile 主动预算 3、全局硬上限 6，以及 exploratory 语义保持原样。单轮实际预算由 `active_attempt_limit=1` 和冻结约束强制执行；公共 `maximum_attempts=6` 是全局协议上限，不是单轮追加执行授权。

本能力只支持新 cohort。不能给旧 source 或已经执行的 Round 1 补模式、改 receipt、复制 child 或重播。首次取值前仍须由监督任务完成协议登记；hash 可以证明内容绑定，不能独自证明从未观察数据或登记时间。

## 事前输入

在 Git 外冻结协议和唯一策略源码，另写 `single-baseline.json`。以下是结构示例，两个 hash 必须替换成实际文件 SHA-256，不能使用占位值：

```json
{
  "mode": "SINGLE_BASELINE_V1",
  "version": 1,
  "maximum_rounds": 1,
  "maximum_attempts": 1,
  "protocol_sha256": "<冻结协议的64位小写十六进制SHA256>",
  "strategy_sha256": "<唯一策略源码的64位小写十六进制SHA256>"
}
```

协议本身冻结 Profile、窗口/pre-roll、成本、核心和额外门、预算、停止规则及 D/H/Stress 授权边界。这个外部 JSON 引用协议 hash，避免让协议包含自身 hash。Profile 必须使用实际持久化快照；获取前不存在的 source hash 不能预造。

在既有调用的参数后加入同一个 `--single-baseline /absolute/path/single-baseline.json`：

- `scripts/fetch_okx_profile_data.py`：在任何网络取值前读取并验证约束，写入 source provenance 的 `contract.profile_acquisition`。
- `scripts/run_bounded_research_pilot.py prepare-search-data` 和 `prepare-development-data`：约束必须与原 source 精确相同；同时继续传原 Profile、窗口、经济门和真实 source receipt/provenance hash。

保留 source1 和不重播的外层登记约束；本功能不新增跨目录全局 ledger 或获取服务。失败不能通过创建另一个 source/root 来救结果。

启动既有 Research Console，仍以 `POST /api/search-campaigns` 提交 `{"profile_id":"…","candidate_ids":["…"]}`。模式来自冻结数据，HTTP 请求不能临时切换。Candidate 必须是已有批准的 root seed，源码 hash 必须与事前声明一致。无新增 generation 或 Candidate 表字段。

## Search 输出和人工审阅

同一 runner 执行原 Profile/economic gate，写原始 artifact、TRIAL、ROUND_RECEIPT 和真实单轮 terminal，再原子持久化到现有 `generation_runs` JSON。核心门通过才有 `SEARCH_FINALIST_FROZEN`；额外协议门还须人工审阅。技术 INVALID 保留 `search_metrics=null`，其 `SEARCH_TERMINATED_NO_FINALIST` 不代表有效经济负结果。有效但未通过门的结果也不得追加尝试。R2、第二次 Search 和旧模式改判均拒绝。

完成冻结协议中**全部**额外门的人工审阅，并取得单独 D 授权后，沿现有 `POST /api/research-runs` 提交：

```json
{
  "candidate_id": "<原Candidate ID>",
  "protocol_review": {
    "schema": "freqtrade-lab-single-baseline-review-v1",
    "protocol_sha256": "<原协议SHA256>",
    "data_provenance_sha256": "<Search acquisition/retained-data-provenance.json SHA256>",
    "candidate_id": "<原Candidate ID>",
    "source_sha256": "<原策略源码SHA256>",
    "attempt_number": 1,
    "raw_artifact_sha256": "<该attempt的原生archive SHA256>",
    "all_protocol_gates": "PASSED"
  }
}
```

使用现有本地 HTTP/CSRF 流程；不得把示例当作授权。以上值来自原 campaign/terminal projection，不能从另一结果拼接。`source_sha256` 指策略源码，`data_provenance_sha256` 指 Search 数据 provenance（其中绑定完整 source receipt/hash）。`raw_artifact_sha256` 是原 archive 的字节 hash，不是 result JSON 的 hash。

`all_protocol_gates` 是人工声明，不是软件重新计算方向分布、集中度、actual q、force_exit 或固定路径成本敏感性。任何门未审完或无法核实都保持 `UNKNOWN`，失败保持 `FAILED`；两者以及缺失/篡改绑定都不能创建 ResearchRun。页面显示这一要求，普通 D 按钮不替用户填写审阅声明。

通过的审阅存入现有 `research_runs.input_snapshot_json.protocol_review`，与原 finalist、source、Profile/经济门、窗口和同一 ResearchRun 绑定。重复交接（包括先前 D 技术失败）拒绝，不自动重试 D。D/H/Stress 同 Run；真实 H/Stress、资格、Release、交易仍需各自授权。没有新增 SQL 表、字段、索引、服务或审批平台。

## 验收范围

`tests/test_single_baseline.py` 包含非法形状/bool预算/源码和模式漂移、默认两轮语义、单轮技术失败与经济未过门的区别，以及一次真实 CLI/Feather/临时SQLite/loopback HTTP/runner terminal/projection/D prepare 隔离链。损坏/缺失 receipt、raw artifact、人工审阅、重复执行和事务失败均在合成数据上检查。网络/native 执行边界使用 stub，D worker 故意失败，不生成 D 市场结果；这些验收仅证明代码链路。
