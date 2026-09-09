# ATOM_REGIME_PULLBACK_V1：SEARCH_TERMINATED_NO_FINALIST

唯一一次真实 Search 已完成，技术状态 VALID，原生终态与协议审计一致拒绝。**毛价格收益已经为负，且原生 DD 超过20%；本轮不是仅被交易成本或样本门淘汰。** 没有重跑、调参、消融或后续阶段。

| S 结果，E0=1000 USDT | 数值 / 判定 |
|---|---|
| 毛价格 PnL | **−38.420153870 USDT** |
| 原生实际开平手续费 | 19.961579355984 USDT |
| 原生费后净收益 | −58.38173322 USDT |
| 额外基本滑点 | 19.961579355984 USDT |
| 基本成本后净收益 | **−78.343312575984 USDT；FAIL** |
| 敏感性固定路径净收益 | −118.266471287952 USDT；FAIL；不是第二次 native |
| 原生 DD / PF | 26.3591831% / 0.8882161；均FAIL |
| 每日 cost-MTM DD | **NULL**：按已授权的决定性负结果早停规则未计算，未把闭合交易DD当盯市DD |
| 固定500 stake现金可执行性 | native/base/sensitivity 均PASS；未缩仓，未重复扣原生费 |
| 自然交易 / ROI / 期末强平 | 20 / 0 / 0；自然交易≥12通过 |
| 延伸30日完整暴露组 | 7 < 8；FAIL，组数不是IID证明 |
| 移除最好组后的基本净收益 | −242.315666877 USDT；FAIL |

退出构成：9次信号退出、11次止损；平均持仓4464分钟（3.1日）。约20个往返的实际腿费用与额外滑点进一步恶化了已为负的毛收益，不能推断长期状态过滤有增量预测效果。逐腿利润与原生报告的合计舍入差约 `−5.984e−9 USDT`。三种成本路径最终现金约941.62、921.66、881.73 USDT，所有入场均有完整stake资金。

实际 campaign **`2cd91f74-4db9-4a35-9d11-5615053babd6`**；planned `6dd19656-db5e-4e56-8b47-bd3a02b74337` 只保留为原意图，不回写。唯一 attempt 已消费1/1，remaining=0。原生ZIP SHA：
`ad3881b9896faeecd6ef946329d699fbabd8edf5970c4e91e6e8f0599939088d`。

[原始ZIP](/Users/shenjianpeng/.codex/runs/freqtrade-lab/atom-regime-pullback-v1/cohort-20260906-0413/search/search-results-round-1/232031bf-5e0b-44ff-82be-8b7e30afaa38/raw/backtest-result-2026-09-06_04-25-30.zip) · [逐腿/现金/分组审计](/Users/shenjianpeng/.codex/runs/freqtrade-lab/atom-regime-pullback-v1/cohort-20260906-0413/search-economic-audit.json) · [终态一致性与全部SHA](/Users/shenjianpeng/.codex/runs/freqtrade-lab/atom-regime-pullback-v1/cohort-20260906-0413/terminal-identity-verification.json) · [实际只读页面](http://127.0.0.1:50783/console)。

原生terminal JSON与Generation数据库投影逐对象相等，实际HTTP终态、ZIP和指标一致。Profile1、Generation2（其中1条为Search终态）、Candidate1；ResearchRun/Execution/Release均0。全部冻结文件与source SHA未改变。D仅此前producer QC，没有经济运行；H未取得，H/Stress保持封存。

最小合成例通过只覆盖所列场景。未用于本轮真实计算的 `daily_mtm` helper 按同刻卖出优先排序，不能正确处理新仓同bar止损；不宣称它已普遍验证或可直接复用。本轮真实MTM为NULL，拒绝结论不依赖该helper，也不追加开发测试。原生终态保持不变，补充审计单独保存。

**当前停止。** [Issue92](https://github.com/He1met/freqtrade-lab/issues/92)仍开放，全局终态账本尚未追加，待监督核证后决定收口。不导入finalist，不启动D/H，不另开救援方案。

收口追加（2026-09-06 04:33:32 UTC）：监督验收后已精确追加一条实际campaign终态，旧账本92,162字节前缀及空行保持不变，after为93,576字节、SHA `8defdf5888380fe9c0ae95a99cc15be3c140de392441d67e7f229b893dd20f49`，实际campaign仅一条记录。[账本追加回执](/Users/shenjianpeng/.codex/runs/freqtrade-lab/atom-regime-pullback-v1/cohort-20260906-0413/global-ledger-terminal-receipt.json)。Issue92已远端读回 **CLOSED**，见[远端状态回执](/Users/shenjianpeng/.codex/runs/freqtrade-lab/atom-regime-pullback-v1/cohort-20260906-0413/issue-closed-remote.json)。上述待收口状态已完成；历史冻结、原生结果和审计未改，D/H边界不变。等待下一研究决策。
