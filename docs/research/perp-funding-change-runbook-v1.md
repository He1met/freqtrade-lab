# 已结算资金费水平与变化：第五轮入口

本轮承接已完成每日发现中唯一保留的资金费变化机制。此前冲击反转分支已终止，不重跑；固定 carry_nonpaying 确认保持原候选、窗口及代码 SHA。

只用 first-capture-v1 已曝光开发数据，评分窗口2025-01-09T00Z至2026-07-01T00Z。预先排除无法在窗口内完整持有8小时的尾部事件。资金费水平逆向与资金费变化逆向共用两条已可用结算记录，零值空仓。每小时开始时已有仓位则永久跳过本次事件，包含随后在该小时到期平仓的情况；不得原地反手或延迟补入。

输入准入实际于2026-09-09T01:58:21Z完成：BTC/ETH各1614个评分事件（尾部排除之前），非零变化1504/1491，水平与变化决策分歧728/691；未读取收益标签或运行native。该检查证明对照存在决策差异，不证明预测价值。来源时点仍为历史保守假设，未升级为PIT或独立证据。

经济协议 `docs/protocols/perp-funding-change-v1.json` 于02:00:04Z冻结。两个变体共900秒、0技术重试；共用原V3 8/day、28/week预算与原writer锁。单边6bp taker+2bp滑点、真实毫秒资金费、1x和共享研究钱包均复用现有原生组件。

活动入口是 `scripts/run_perp_funding_change_v1.py`。参数为：

- `--source-root`：运行根的 `data/first-capture-v1`。
- `--runtime-root`：`/Users/shenjianpeng/Documents/freqtrade-lab-local/perp-autonomous-v1`。
- `--output-root`：该运行根的 `experiments/round-005-funding-change-v1`。
- `--development-manifest`：该运行根的 `development-admissions/flow-reversal-v1.json`；沿用同一实际源清单，文件名不改变数据用途或已消耗实验身份。
- `--policy` / `--dispatch-policy`：原V3预算与已安装dispatch政策。
- 准备时只用 `--check-only`；执行时必须是实际新dispatcher领取后的 `--claim-json`。

原 `reserve_once`、超时异常、输入SHA核验、共享钱包及成本核账函数直接复用；新代码只加入资金费事件规则和对应原生适配，没有新通用框架或第二撮合器。维护后满足900秒+300秒余量，立即claim→native→原finish；stdout包含原生表格，结果从持久summary读取。

运行准备回执位于 `funding-change-preparation-v1`，其中保存输入准入、实际执行预检、任务、claim和各阶段原始stdout/stderr。已有原生预约、RUNNING、未知中断或产物时仅核原件，不覆盖、不重新获取预算或更名重跑。

定向纯检查：机制10项、独立成交审计8项通过。包含严格可用时间、同小时跳过、零值、单次事件、8h及尾部限制、成交标签与资金费毫秒审计；未重跑旧调度回归。实际原生与经济结果须由本轮完成报告单独证明。
