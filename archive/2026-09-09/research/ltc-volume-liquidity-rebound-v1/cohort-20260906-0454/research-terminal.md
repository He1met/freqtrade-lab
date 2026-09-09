# LTC_VOLUME_LIQUIDITY_REBOUND_V1：SEARCH_TERMINATED_NO_FINALIST

唯一一次真实Search已结束，技术状态 **VALID**，原生终态与补充审计一致拒绝。**毛价格收益为正，但原生PF低于冻结1.10门，基本滑点进一步将费后收益转为负。** 没有重跑、变体或消融，D/H/Stress未运行。

| S结果，E0=1000 USDT | 数值／判定 |
|---|---|
| 毛价格PnL | +30.21474670 USDT |
| 原生实际进出手续费 | 16.03021370932 USDT |
| 原生费后PnL | +14.18453299068 USDT |
| 额外基本滑点，每腿10bps | 16.03021370932 USDT |
| 未被原生反映的跳空补差 | 0.0 USDT；无重复扣损 |
| 基本成本后净收益 | **−1.84568071864 USDT；FAIL** |
| 每腿fee20bps＋slippage20bps敏感性 | **−33.90610813728 USDT；FAIL**，同路径算术，不是第二次native |
| 原生PF | **1.0470090443 < 1.10；FAIL** |
| 原生DD | 10.7982497625% ≤20%；仅该原生指标PASS |
| 每日cost-MTM DD | **NULL**：按决定性PF/成本门失败的授权早停；不以原生DD冒充该门 |
| 固定500 stake现金可执行性 | native/base/sensitivity均PASS；未缩仓，精度舍入与lot匹配 |
| 自然交易／期末强平／ROI退出 | 16／0／0；自然交易≥12 PASS |
| 完整30日活跃块／正收益块 | 15／8；块数≥8且正块严格过半PASS；不是IID证明 |
| 移除最好完整块后的基本净收益 | **−103.12166470000 USDT；FAIL** |
| 剔除期末强平后的基本净收益 | −1.84568071864 USDT；无强平，仍FAIL |
| 最大单腿量／该日基础币总量 | 约0.004520% ≤0.1%；粗粒度容量门PASS，开盘深度仍UNKNOWN |

9笔信号退出均实际持有48小时；7笔止损，其中6笔入场同bar止损、1笔次日止损。实际入场均对应前一完整日的冻结Q、去重与liq条件。按照原生JSON中每笔交易及两个订单的不可变位置身份核对时序，同bar先买后卖，没有把卖出放在持仓创建之前。原生导出没有trade_id/order_id，审计使用`ZIP SHA + JSON trades[i]/orders[j]`定位并明确标注，不伪造交易所ID。

逐腿精确手续费重建与原生PnL只有约6.8e−10 USDT舍入差。三种路径终值分别为1014.18453299068、998.15431928136、966.09389186272 USDT。所有持仓已平，实际现金只在成交时变动；此轮按协议未计算逐日MTM，故没有将预计清算准备写入实际现金。D/H专属CI不适用本S，保持NULL。

该结果说明这次冻结规则的微弱毛收益不足以通过预设成本与稳健性门。不能据此归因于成交量提供独立预测能力，也不将换币或反转谓词称作新独立发现。价格回补有发生，仍不足以晋级。

实际campaign **`0c9ab37c-7d1d-413b-bf9a-f42bec79860a`**；planned `8d8fb912-cd54-42d2-8d89-70b2dea155c3`已另记映射，原intent未改。1轮／1attempt，已用1、remaining0，新增native恰好1。

唯一原生ZIP SHA：`4ed632a76a06ba0ddf433e8d9aca43c06956f6be510a43013a8d2bd4360ff419`。

[原生ZIP](/Users/shenjianpeng/.codex/runs/freqtrade-lab/ltc-volume-liquidity-rebound-v1/cohort-20260906-0454/search/search-results-round-1/5e9f5c5c-bc9e-4488-971d-800375b82504/raw/backtest-result-2026-09-06_05-16-07.zip) · [逐腿、现金、分组及各门审计](/Users/shenjianpeng/.codex/runs/freqtrade-lab/ltc-volume-liquidity-rebound-v1/cohort-20260906-0454/search-economic-audit.json) · [全部身份与SHA验证](/Users/shenjianpeng/.codex/runs/freqtrade-lab/ltc-volume-liquidity-rebound-v1/cohort-20260906-0454/terminal-identity-verification.json) · [实际页面](http://127.0.0.1:52800/console)。

原生`search/search-terminal.json`与实际Generation.response_json逐对象相等，HTTP终态与唯一ZIP一致。六表计数 **1/2/1/0/0/0**；search_finalist为NULL，ResearchRun/Execution/Release不存在。全部原冻结、源文件和source-ready列出的文件SHA仍一致；source始终1次／15HTTP。D仍仅producer/QC，H未取且封存。

**监督验收后已收口**：[Issue #93](https://github.com/He1met/freqtrade-lab/issues/93)已于2026-09-06 05:41:16 UTC关闭并读回CLOSED；[原Search授权](https://github.com/He1met/freqtrade-lab/issues/93#issuecomment-5557138373)与[终态说明](https://github.com/He1met/freqtrade-lab/issues/93#issuecomment-5557247350)均已记录。全局ledger在现有sidecar锁内使用apply_patch精确追加一次实际campaign终态，原96819字节前缀及空行完全保留，actual仅匹配1条。新长度98397字节，SHA `2f2e1ee577ca324f82e25f1222058b159cff0949a6b502a43eee9ba58c584205`。S[20210501,20240101)已消费；D仍仅QC，H未采封存，无ResearchRun。

[账本收尾回执](/Users/shenjianpeng/.codex/runs/freqtrade-lab/ltc-volume-liquidity-rebound-v1/cohort-20260906-0454/global-ledger-terminal-receipt.json)及[Issue远端读回](/Users/shenjianpeng/.codex/runs/freqtrade-lab/ltc-volume-liquidity-rebound-v1/cohort-20260906-0454/issue-closed-readback.json)是本次收口证据。原terminal-identity-verification.json中“未关闭/未追加”描述的是监督验收前快照，保持原字节；本段补充其后状态，不改变原生终态、策略、协议、源或审计结果。关闭代表这次有界研究交付完成，不代表盈利。没有新增回测、下载或后续阶段。
