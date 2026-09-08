# BTC/ETH 永续研究首次交付与恢复验收

已实际迁移并完成首轮4个原生有限对照，没有找到合格盈利策略。全部2025-01—2026-07历史属于开发证据，独立确认尚未执行。最有信息价值的方向过滤版本净亏8.36%、小时MTM回撤22.56%；继续理由是毛价格效应正而完整成本吃掉收益，绝不是降低门槛让它通过。

- [范围/政策迁移](perp-migration-v1.md)：保留原main和未提交用户文档，新研究仅BTC/ETH USDT线性永续、1h、1x；研究20%目标不改变实盘权限。
- [真实数据/旧证据核验](perp-data-audit-v1.md)及[因子目录](perp-factor-catalog-v1.json)：两币各18月13104小时、1638结算；近期OI与日级链上；总100公共GET，真实增量15GET/同小时0GET。
- [首轮完整中文报告](perp-first-experiment-v1.md)及[机器摘要](perp-first-experiment-v1.summary.json)：4次原生/0市场重试，完整净值/成本/资金费/订单/多空/分期/事件/基准/消融及未算不确定性。动态波动减风险没有胜过固定减风险。
- [任务前后清单与恢复验收](perp-schedule-audit-v1.md)：实际暂停旧方向并迁移唯一 `freqtrade-lab-2` 至本任务，30分钟ACTIVE；旧 `freqtrade-lab`、`automation-2` 保持PAUSED。#139/#155/#161及PR163为方向归档，证据保留。
- [更新后的知识库](../research-knowledge/perp-autonomous-v1.json)存储现行入口、负结果边界和唯一优先后继，不修改旧知识。

首轮任务 `perp-round-001` 已在专用状态中COMPLETED。后继 `perp-round-002-turnover` 于2026-09-08T15:25:41Z实际QUEUED，只比较24h/48h反向退出，12h父结果不重跑；新增2个native，今日预算已满，最早2026-09-09T00:00UTC。V2代码尚待最小参数化和新的实际代码/数据冻结，不把父代码SHA写成已完成V2。若两个变体仍成本后负或毛效应消失即收束这一成本分支。

正式持久入口：

```sh
cd /Users/shenjianpeng/Documents/freqtrade-lab/.worktrees/btc-eth-perp-v1
PYTHONDONTWRITEBYTECODE=1 /Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python \
  scripts/perp_tick.py \
  --root /Users/shenjianpeng/Documents/freqtrade-lab-local/perp-autonomous-v1 \
  --policy docs/protocols/perp-autonomous-policy-v1.json
```

该入口实际做状态/数据更新，不执行生产订单，也不把due变成已完成研究。市场计算必须通过持久claim与原生manifest，预算和writer状态在真实root验收过。集成曾发现中间receipt被误认为成功，已修为只有完整提交且core_complete=true才就绪；中断与失败分别保存且不自动重试未知capture。

测试口径：19项采集测试、12项调度测试、3项heartbeat集成测试；原生默认pytest薄封装1项内部执行4项合约/因果检查（不重复相加成5个独立测试）。合成原生累计3次，市场原生4次；最后没有因文件整理重复测试/市场回放。未知保持未知：实际订单簿冲击/小时内风险/历史规格PIT/独立确认/精确模型费用。

调度保存ACTIVE且提示词、目标、频率均复读核验；已验证真实CLI承接、锁、幂等、预算拒绝、故障收据和时区。**首次自动唤醒及调度器真实下次触发尚未观测，保持UNKNOWN**，不能说已经证明关机或休眠时也持续运行。没有新增系统定时器；该研究heartbeat依赖Mac与Codex应用运行。原计划Tokyo21:00/周日18:00已显式换算Shanghai20:00/周日17:00，实际于其后的首次心跳生成检查点。

快照与回滚：专用Git外 `migration/` 内的三个before.toml与附件原文保留；暂停唯一heartbeat即可停止新调度，原任务均可审查回滚但现货默认仍暂停。没有改动网络、代理、系统保护、其他Freqtrade Ai服务或真实交易账户。Issue #162保留OPEN，首个自动唤醒和后续研究由已启用调度承接，代码通过审查PR交付。
