## 已验收终态：UNDERPOWERED，项目内预筛已入库，未运行 Search

监督完成合并代码、真实数据库前后审计及实际 API 复核，并授权完成只读页面核验后关闭。本任务已完成实际 CUA 页面核验：Generation 规范化状态可见 prefilter_evidence，14/5/9、required_total 24、UTC [2023-11-06, 2024-11-04)、UNDERPOWERED、PnL null 及冻结 SHA 均正确。PR #103 merge `fa6e49e4a0d9b53345821bf5312bf3443e7b68a1` 的正式 CLI 已单次写入本轮 sanitized lab.sqlite，仅改变 Candidate metadata_json 和 updated_at。其余历史字段和六表计数 1/1/1/0/0/0 不变。

纠正旧表述：此前“外部 JSON + ledger + Issue 已闭环”不等于项目内闭环。现在经 PR #103、正式导入及实际 API/页面验收才完成本轮项目内预筛记录。关闭本 Issue 表示本轮容量不足终止，不代表找到合格策略、经济亏损或总体目标完成。

最终证据：Git 外同根 `prefilter-project-acceptance.md`、`prefilter-cli-import.json`、`prefilter-database-before.json`、`prefilter-database-after-console.json`、`prefilter-generation-http.json`、`prefilter-final-receipt.json`。定向工程验证 31 passed / 21 deselected / 0 skipped，监督独立复跑通过。

唯一ADA_NORMALIZED_TREND_PULLBACK_3D_V1按事前容量门终止：S仅14个准入事件，多5/空9，无法达到24个自然样本及多头>=8。PnL/毛利/PF/DD均UNKNOWN，未计算经济结果，不能记为经济亏损。不能调参数/门/换窗救援，D/H保持封存。

## 已完成的实际工作

- PR #102 已匹配head42beabbd6ade2b7fc9639f236199c9bb8b7019e2合并，merge/main3930287de83104ec93cad4f6a2c9b9248bf575e0；唯一ADA映射、两个测试文件，27定向测试通过。未重复测试/native smoke。
- 真正CODEX Generation1 ef5de524-0506-4bd6-9af5-eec9d9c59202；Candidate1 fbf47a7c-c892-45c0-80ce-03bee437e1d9，tool events0，源码SHA与冻结eb1f551464519f52b6f29469843dfe0acc880b53a6e86b778b94f09a88eda4b8完全一致。
- 一次原生download-data：64 CCXT fetch、5314665 decoded bytes，wire attempts UNKNOWN，零重试/拼接。完整S+D800日线/19200小时mark/2184评分资金；物理隔离S/D各436/10464/1092，UTC/资金日历/原响应及来源hash/consumer检查通过。H未采集，D不跑信号。
- 唯一冻结S信号容量上界14/5/9；非未来收益或成交模拟。首件按信号日分块，保留原件后补同源码入场日边界核对，所有14事件next-open仍在S，四块多/空仍3/0、2/2、0/5、0/2。结论不变。
- native Search0，ResearchRun/Execution/Release0；六表1/1/1/0/0/0。审批APPROVED仅代码审批，不等于研究通过。

## 证据及Console边界

Git外根 /Users/shenjianpeng/.codex/runs/freqtrade-lab/ada-normalized-pullback-b506-20260907，capacity-handoff.md、capacity-terminal-receipt.json、signal-capacity.json、capacity-entry-boundary-audit.json、closure-ledger-receipt.json及源/策略/协议原件全部保留。协议SHA66b18f5162e9020945562e31f1ad34a35305a8e1cac752d88aad084817ea8d57从冻结后未改。

原ledger锁追加真实S_SIGNAL_EXPOSED/UNDERPOWERED及绑定实际Generation/Candidate的外部JSON证据，终态135943bytes SHAb3775aaee9bfb7a0c8821f0db1f9c8343630018611e4f5b38adcdf0d28de5c63，旧前缀/空行完整。未伪造Search campaign或业务表研究结果。

Console 已按监督授权保持原参数重启载入合并代码。启动时静态能力重新校验已准备好的来源，因此 Search capability 为 READY / SEARCH_READY，campaign=null、attempts空、consumed0；本轮 SINGLE_BASELINE_V1 仍仅一轮一次，通用硬上限6不是本轮授权。READY仅工程能力，本 Candidate 已 UNDERPOWERED，未授权继续 Search。Development Candidate 为 BLOCKED_SECURITY（无 verified finalist），H/Stress SEALED_UNREAD，FreqUI UNAVAILABLE。预筛证据现在由正式 CLI 写入并在原有 Generation JSON 详情显示；Generation COMPLETED 和 APPROVED 历史保持不变。Profile继承旧模板的显示名未变，真实Issue101 id/pair/参数/源码/来源绑定准确。

## 交接

本 Issue 范围已终止，按监督最终授权关闭。后续任务由监督另建，不在本 ADA S 扫描挑参数、不机械换币，不重放已消费证据。总体发现合格策略目标未完成。

## 历史监督纠正与授权过程（已由顶端实际验收结果替代）

上述终态证据是外部收尾，不等于项目内预筛闭环。DB仅记录生成/批准；UNDERPOWERED尚未入DB且Console不展示。拟复用candidates.metadata_json的单一可选prefilter_evidence对象，在codex_generation增加严格附加函数/薄CLI并由load_generation投影到现有安全JSON详情，保持Generation COMPLETED/APPROVED历史不变。具体字段、绑定/幂等/事务和4项定向验证见Git外project-prefilter-entry-proposal.md。此最小工程待root决定，尚未实施；Issue必须保持OPEN。

监督现已授权上述最小入口实施、临时DB验证和一个审阅PR；不自行merge，不先写真实DB。参数门从已冻结Profile读取，严格绑定协议/来源/报告摘要，不把ADA或24写成项目通则。不变更历史Profile显示名、Generation原文/输入/输出及批准历史；项目闭环仍待验收合并后实际CLI/API验证。
