# Issue101项目内预筛证据入口：最小实施提案，未授权实施

纠正：当前研究终态证据完整，数据库/页面预筛闭环未完成。此前“最小闭环完成”措辞不准确，外部JSON/ledger/Issue只完成外部收尾。Issue101必须保持OPEN。现DB仅Profile1、真实Generation COMPLETED1、Candidate APPROVED1；ResearchRun/Execution/Release0，UNDERPOWERED未入DB。Console显示生成及批准，以及早期startup冻结的Search BLOCKED_DATA/null campaign/0attempts；不能显示外部容量结论。

## 唯一JSON落点

选择现有 `candidates.metadata_json` 的一个可选对象 `prefilter_evidence`，不是通用备注列表。不能改 `generation_runs.response_json`：load_approved_candidate_snapshot约1432–1468行严格要求其等于原输出三字段并与response_raw_text一致。当前metadata顶层也严格等于generation/review/provenance（159、1174行），所以没有现成合法写入口可直接使用；必须窄扩展可选key并验证其确切结构，不能裸SQL塞字段。

建议对象具体字段（仅一次本地容量终态）:

- `contract: "FROZEN_SIGNAL_CAPACITY_EVIDENCE_V1"`，`stage: "PRE_SEARCH"`，`status: "UNDERPOWERED"`，`exposure: "S_SIGNAL_EXPOSED"`。
- `generation_id / candidate_id / profile_id / profile_snapshot_sha256 / code_sha256 / protocol_sha256`。
- `source_provenance_sha256 / source_receipt_sha256 / search_source_provenance_sha256 / search_ohlcv_sha256 / report_sha256 / entry_boundary_report_sha256`。
- `scoring_start_utc / scoring_end_exclusive_utc`，`event_upper_bound: {total:14,long:5,short:9}`，`required_natural_samples: {total:24,long:8,short:8}`，`entry_blocks: [{long:3,short:0},...]`。
- `native_search_runs:0 / pnl_computed:false / development_signal_runs:0 / holdout_opened:false`，`recorded_at_utc`。
- `experiment_name: "ADA_NORMALIZED_TREND_PULLBACK_3D_V1"`，`profile_display_name_note`仅如实说明旧显示名，不更新历史Profile/原generation request。

没有PnL字段或收益0，没有Search campaign/ResearchRun id。单对象严格字段/类型/长度；UNKNOWN仍null/明确标记，不扩成任意注释schema。

## 入口与原样显示

1. `lab/codex_generation.py`新增一个 `attach_prefilter_evidence(database, candidate_id, evidence_root)`，复用get_connection、_check_schema、canonical JSON、load_approved_candidate_snapshot。在同一BEGIN IMMEDIATE事务内验证真实CODEX COMPLETED/唯一APPROVED Candidate及当前Profile和原generation快照，再解析该净化根固定文件，而非运行策略。
2. 复核固定协议、源码、profile-snapshot、source-publication、source-aggregation-QC、signal-capacity、entry-boundary-audit和generation-approved的实际字节SHA/交叉引用；ID全部与事务快照相符；来源pair/window/S Feather摘要与来源manifest吻合，不读市场行值或D/H。容量报告必须声明S-only/no PnL/native0且确实达不到至少一个冻结样本门。以批准的协议SHA及唯一已绑定证据摘要验证门24/8/8，不能接受调用者随意改门或仅相信文件名。报告保留原件，DB只复制小型经验证对象与SHA。
3. `_generated_candidate_review`允许旧三key或三key+该唯一可选key，存在时调用同一个严格对象验证器；generation/review/provenance三子树一字不改。`load_generation`在candidate公开对象附加该经过验证的prefilter_evidence，不展示本地路径或原响应。
4. 薄CLI `scripts/attach_candidate_prefilter_evidence.py --database ... --candidate-id ... --evidence-root ...`只调用该函数并输出receipt；参数只接受本地固定研究根、常规文件与有限大小，拒绝symlink/越界/非有限或bool冒充数字。不支持目录扫描、网络、追加任意类型或自动研究。
5. 已有 `/console` 的Generation详情 `renderGeneration`（约4789行）已用 `textContent=JSON.stringify(safe,null,2)`显示完整public payload，只增加load_generation字段就能原样、安全看到UNDERPOWERED及原始计数/绑定SHA。无需专用组件/仪表盘/新状态机；当前页面若确有折叠导航问题，仅复用既有选择Generation动作。不将Generation COMPLETED或APPROVED改名为研究状态。

## 原子性、幂等与验证

同件按除recorded_at外的规范化证据内容比对：已有完全相同对象返回原对象/不写updated_at；不同report/source/protocol或任何已存不同字段均409冲突，禁止覆盖历史附件。首次匹配metadata旧值UPDATE一次并commit，任何读取/hash/身份/格式失败rollback；更新仅metadata_json/updated_at，无其他表写入。使用现有绑定验证函数，避免旁路其约束。

预计3文件（现有codex_generation.py、薄CLI、新定向测试文件），约180–280行增量、1–2主动小时；若现有文件读取工具不能复用，先报告具体增加范围，不扩大成通用导入器。

4个必要测试组，全部合成/临时六表DB，不native：
1. 成功附加→load_generation及既有HTTP详情能看到原始证据；前后Generation全部字段、Profile、源码、review/provenance不变，六表数不变，正确实验名仅在证据中。
2. 参数化错误candidate/generation/profile/code/protocol/source/report绑定或非UNDERPOWERED/声称已native/PnL的负例，在写前失败且DB/metadata完全不变。
3. 同件第二次零变更；不同件冲突拒绝，事务中任一异常无部分写入。
4. 恶意文件路径/symlink/超长或非有限/错误数值类型拒绝；含HTML实验名只通过现有textContent安全显示（沿现成HTTP检查，不新增前端框架）。

获root授权后才实现；实现/PR验收合并后才用一次合法CLI写入当前真实Candidate，并读实际API/页面验证。无该最后一步不能称项目闭环或关闭Issue101。本提案未改源码、数据库、行情或冻结协议。
