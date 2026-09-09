## 当前结论

DOGE confirmed shock reversal 单基线已停止，监督已决定不再执行 D/H/Stress，不调整本币参数救援。最小 worker 修复 PR100 已按固定head验收合并，merge/main `8079856520a961237079ba86cd1295485a03a20d`。本Issue按范围完成关闭；候选未合格，总体策略发现目标未完成。

S 唯一 Search 正式终态 `SEARCH_FINALIST_FROZEN`，核心及额外13门通过：33笔/32自然，保守净+165.319130 USDT，PF1.975491，小时收盘MTM DD9.945161%。收益集中末块，不证明稳健。

同一候选唯一 D 已原生执行；后处理因 Console 将 venv Python 软链接解析到缺 pandas 的基础解释器而失败。ResearchRun `68fcd677-fd22-40e9-a6f1-78ee910b3a68` 与唯一 Execution 保留技术 `FAILED`，指标 NULL、verdict NULL；六表计数1/2/1/1/1/0。不存在正式D通过或正式经济REJECTED的伪造入库。

监督单独授权同一幸存ZIP作 `POSTHOC_DIAGNOSTIC_ONLY`：31笔/25自然，价格毛利-50.691930 USDT，保守净-66.568424 USDT，PF0.759588，正常小时close MTM DD15.545210%，去最大赢家仍-108.093465 USDT。五项冻结门失败。该诊断不是第二次回测或正式D验收；与技术FAILED双事实并存，足以支持停止候选。原runner summary/日志与原raw ZIP未保留，缺失凭据保持UNKNOWN，不开发恢复入口、不伪造回执。

## 当前工程范围

PR99已合并：BCH/DOGE窄绑定，merge `df3dc41dba4ccba6dba84031de7e2568f7e63399`。

Console D/H 两处worker启动的venv语义已修复：验证目标存在、正规文件、可执行，但保留原venv调用路径。新增真实临时venv marker依赖回归，不运行策略；与D/H HTTP直接回归合计38 passed，0skip。无新依赖、表、native或策略修改。PR100以head `3cb3a73b2e37706dc23fc32c10cbb433a2de0fb8` 验收合并。

## 实际预算与证据

- 唯一CODEX Generation1、Candidate1、capture1、Search1、D1；重采/重放0，H/Stress/Release/交易0。
- Capture61 CCXT fetch，5,145,891 decoded bytes；wire attempts UNKNOWN。S+D来源同源分离；H未采集。
- 策略源码SHA `61488a724e54fca3dfe11a47294c3a3a02077090cb38baaef5385d16ef43d05f`；协议SHA `e0920ce3dfe27bdc7dff18828ed0676c6f3cbefa4eb160e33f5dcf5585ee9127`。
- D幸存净化ZIP SHA `31032c04d4cad38c3f8efda2cefb0dbc99376622386d85b1b060f209b9e0d278`，源码/manifest/CRC已验。
- 本地根 `/Users/shenjianpeng/.codex/runs/freqtrade-lab/doge-confirmed-reversal-bb9d-20260907`；`search-protocol-review.json`、`development-failure-inspection.json`、`development-posthoc-diagnostic.json` 保存完整区分，原ledger锁下已登记D消费。

下一研究由监督另开任务：本次S阳性/D诊断阴性显示跨期失效，D价格毛利已负，不能归因成仅费用问题。保留该家族负例，不能通过调整DOGE参数或打开H救活。总体策略发现目标未完成。
