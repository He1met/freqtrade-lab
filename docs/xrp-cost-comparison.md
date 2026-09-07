# XRP 同成本比较附件

这是 Issue #107 的限定证据入口，支持 Binance XRP/USDT:USDT、1d、isolated 1x、1000 USDT 钱包、固定 250 USDT stake、单仓位。它只往既有 Candidate 的 `metadata_json.cost_comparisons` 增加 S/D/H/STRESS 摘要，不执行回测、不生成基准 Candidate/ResearchRun/Execution、不改变审批、阶段门或 Release。

`PASSED` 只表示主策略的 `net_pct / max(mtm_dd_pct, 1.0)` 不低于同成本买入持有基准。两个数均为钱包百分比；净收益、正常小时 MTM 回撤由现有保守 funding auditor 从原生成交重算。它不是完整协议通过，更不是盈利证明。缺附件就是尚无比较证据，不补零。S 完整外层评审仍需核验所有冻结门；后期仍按原授权逐阶段执行。

## 用户入口

在独立研究预算与对应阶段已经授权并完成后，使用带 pandas / PyArrow 的研究 Python 环境：

```sh
python scripts/attach_research_comparison.py \
  --database /absolute/authorized-workspace/lab.sqlite \
  --manifest /absolute/evidence/comparison.json \
  --manifest-sha256 <comparison.json的SHA-256> \
  --search-root /absolute/authorized-workspace/search-campaign \
  --artifact-root /absolute/authorized-workspace/comparison-artifacts
```

退出 0 输出已验证摘要；退出 1 输出 `invalid_cost_comparison` JSON。同一阶段、同一输入字节重复导入不写库；任何差异冲突，不覆盖旧记录。只更新目标 Candidate 的 metadata 和 updated_at，其余键、Generation、六表结构与其它行保持不变。Console 的既有 Generation 详情返回并以文本展示摘要及资格限制。

该命令需真实、已批准、普通 single-baseline Candidate。S 必须绑定完整持久化 `SEARCH_FINALIST_FROZEN` campaign；D/H/STRESS 必须绑定该 campaign 的真实主 ResearchRun 及已成功完成的对应 Execution。已记录的后期比较必须使用同一个 Run。错误阶段 source、原生主 archive/provenance、窗口在读取该阶段 funding/mark 前拒绝。

`--search-root` 与 `--artifact-root` 是 S 必需的受信运行上下文，沿用本批实际目录，不能由 comparison.json 覆盖。CLI 将 Search root 的 terminal 字节 SHA 与数据库冻结 terminal 比对，按数据库记录的相对路径定位原始 S ZIP；S 来源固定为该 root 的 `acquisition/retained-data-provenance.json`。主 S sanitizer 派生副本放在独立 artifact-root 的 `S/` 子目录，不能放进已冻结的 Search root。D/H/STRESS 不需要这两个参数，其主 ZIP 路径必须逐字匹配已完成 Execution 的 result_archive_path。路径匹配先于 ZIP/provenance 读取，不使用 resolve 绕过链接检查。

## 事前冻结的协议

`protocol` 指向 JSON，其完整文件 SHA 必须就是 Search `single_baseline.protocol_sha256`。研究者需在经济数据前把完整设计、跨资产暴露限制、所有外层门和预算写入 `research_design`；本 CLI 仅验证下面的比较部分，不自动批准文本中的其它门。不得修改既有冻结协议来追认结果。

```json
{
  "schema": "xrp-weekly-cost-comparison-v1",
  "strategy_sha256": "<主Candidate源码SHA>",
  "benchmark_sha256": "<事前审阅的基准源码SHA>",
  "benchmark_class": "NativeBuyAndHoldDiagnostic",
  "research_design": "完整事前研究设计文本，包括资格限制与外层门",
  "stages": {
    "S": {"timerange": "20231106-20241104", "fee": 0.001},
    "D": {"timerange": "20241104-20251103", "fee": 0.001},
    "H": {"timerange": "20251103-20260525", "fee": 0.001},
    "STRESS": {"timerange": "20251103-20260525", "fee": 0.002}
  }
}
```

以上为字段示例，不是已执行的协议或费用事实。费用必须与该 Candidate 冻结 Profile 完全一致；Stress 用其 multiplier。S/D 与 campaign 冻结窗口相同，H 从 D_end 延伸 Profile.holdout_days，Stress 与 H 同窗。

## 输入文件与原始证据

所有 `receipt` 都是恰两个字段的 `{"path":"/absolute/file", "sha256":"<64位小写SHA>"}`。JSON/mark/ZIP 从现有 descriptor-relative、逐层 no-follow 读取器读取；不接受符号链接或 `..`。

`comparison.json` 恰包含：

| 字段 | 含义 |
| --- | --- |
| schema | `xrp-weekly-cost-comparison-v1` |
| candidate_id / campaign_id | 主 Candidate 和真实 Search campaign |
| stage | S、D、H、STRESS |
| research_run_id | S 为 null；其它为同一个真实主 Run |
| protocol | 上述冻结 JSON receipt |
| raw_source | 原始 `retrieval_receipt.json` receipt |
| stage_source | S 为 campaign 冻结来源；其它为已完成主 artifact 绑定的 retained-source receipt |
| marks | 该阶段 `XRP_USDT_USDT-1h-mark.feather` receipt |
| primary / benchmark | 下述两个独立 evidence 对象 |

每个 evidence 对象恰包含：`artifact_root`（绝对目录）、`archive`（相对 `backtest-result-*.zip`）、`strategy`、`provenance_sha256`、`retained_source` receipt、`attempt` receipt、`raw_archive` receipt。D/H/STRESS 的 primary 必须令 raw_archive=null，只读已完成 Execution 绑定的 sanitized archive 与 provenance，避免打开未经定位的另一个原始 ZIP；S 主结果及所有基准仍须保留原始 ZIP，并验证 sanitized report 字节与它一致。

每个 `attempt` JSON 恰包含 `schema`、`role`（primary/benchmark）、`stage`、`native_calls`（整数 1）、`return_code`（整数 0）、`archive_sha256`（原始 ZIP）、`strategy_sha256`、`source_sha256`（该 evidence 的 retained_source SHA）、`raw_source_sha256`（原始 retrieval receipt SHA）。它记录已授权执行的次数声明并绑定产物；不能单凭一个附件发现未登记的隐藏回测。预算监督及暴露台账继续由研究流程负责。

两边必须共享同一个 raw acquisition 父、相同 source、相同 data receipts（同时检查 `files` 和 `local_only_files`），但有各自的策略与 config SHA。H 的独立 `funding-events.json` 使用阶段 source 的 `funding_events_receipt` SHA，文件放在 stage_source 同目录。费用审计的 mark/event SHA 必须匹配实际读取数据。

## 复用已有原生入口

基准固定为首个评分 candle 发一次 long 信号；原生移位后在第二个评分 candle 入场，1x、250 初始名义 stake、不再入场、`minimal_roi={}`、`stoploss=-1.0` 对应零止损价，保留原生 liquidation；最后一根 candle 按原生 open force_exit。附件还检查真实单笔 long、零初始/当前止损价、首个原生 entry 和最终退出边界。提前 liquidation 必须如实保留。

基准不是 bounded Candidate。复用 `research_candidate._run_scenario` 所调用的 `scripts/run_freqtrade_backtest.py`；其 `_verify_strategy_input` 与 producer `_validate_strategy` 检查源文件/收据/class，不施加 Candidate 的 `-1 < stoploss < 0` 限制。不要放宽 Candidate validator。

为基准创建独立输入目录和派生 retained provenance：复制已授权阶段的相同数据/来源收据，更新 **副本** 的 `contract.strategy`、唯一 `files["strategies/<class>.py"]` bytes/SHA 及独立 config 收据；保留原始 source 与 acquisition 父收据。原主策略 provenance 不动。原生 runner 使用该派生 SHA。随后复用 `_sanitize_raw_artifact`，绑定同一派生 SHA 和 funding_data_dir，保留原报告/源码；S 的低层诊断 scenario 使用 DEVELOPMENT，D/H/STRESS 使用对应既有 scenario。S 主结果也只做既有 sanitizer 的字节保持转换，不重跑经济结果。

`tests/test_research_comparison.py` 用完全发明的 2030 marks、funding 和 ZIP 验证入口、派生来源、真实 sanitizer/parser/auditor，以及临时 SQLite、Console HTTP、幂等、冲突、错误阶段读取屏障。原生进程不在这些测试中执行；这不是完整市场数据可用或策略有效的证据。
