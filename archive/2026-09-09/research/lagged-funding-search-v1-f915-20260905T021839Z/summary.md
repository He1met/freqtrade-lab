# LAGGED_FUNDING_SEARCH_V1：两轮探索负终态

**SEARCH_TERMINATED_NO_FINALIST；2/2 次 native 已耗尽，无候选进入独立验证。** R1 收益/PF 失败；R2 另有 19<20 笔样本不足。只收口本批，不代表找合格策略的总目标完成。

LINK/USDT:USDT，OKX isolated，5m short-only，1x，wallet2000/stake400；已见 A/B 探索池 [20240301,20240731)。02:18:39Z 值前冻结，02:25:16Z 首个结果，02:26:17Z 两轮原生终态。两次真实 Codex 返回均逐字/SHA匹配已冻源，无 Generation 重试。

| 指标 | R1 价格转弱基线 | R2 额外 funding 过滤 |
|---|---:|---:|
| 笔数 | 50 | 19 |
| 价格毛额 USDT | -10.845500 | -22.186400 |
| 交易费扣减 USDT | 19.970482 | 7.595429 |
| signed funding USDT | +2.052157 | +1.799561 |
| 原生净额 USDT | -28.763824 | -27.982268 |
| 额外每腿2bps扣减 USDT | 7.988193 | 3.038172 |
| 扣减后净额 USDT | -36.752017 | -31.020439 |
| 原生 PF / DD | 0.833478 / 3.103715% | 0.544232 / 1.803117% |
| 平均持仓分钟（范围） | 465.5（260–480） | 463.158（315–480） |
| 08:05正常退出 / stop / ROI | 44 / 6 / 0 | 17 / 2 / 0 |

R2 比 R1 原生少亏0.781556、额外成本后少亏5.731577，但两者自身均失败，故 **funding 增益候选=false，R1也不保留**。R2 是 R1 的19笔完全相同子集，过滤31笔；价格毛额反而恶化11.3409，主要靠少交易节省费用，不能据此认定 funding 有用。原生 PF/DD 未计额外2bps；原生 gross_profit_before_fees 含 funding，本表“价格毛额”单独剥离了 funding。

3–7月原生净额：R1 **-9.44/-31.05/+6.07/-12.33/+17.98**；R2 **+2.97/-12.86/-8.65/-9.44/0（7月无交易）**。最大盈利单笔 R1 Jul5 +26.161216，占盈利单笔总额18.17%；R2 Mar12 +13.825008，占41.38%。不删坏月、不调参。

逐笔审计：150个每日决策槽与全部真实交易逐点一致；00:00 closed→00:05 next-open、08:00 closed→08:05 next-open、3% stop首次触发bar、每日不重入/不加仓/无重叠均通过。44/17次真实08:00 funding以对应mark重算匹配；stop均在结算前、funding=0来自真实无持仓结算事件。末笔 R1 Jul26 stop、R2 Jun9正常；此后到Jul30无合法信号，无尾部force_exit。逐笔价格毛额−费+funding与native净额差<6e-8 USDT。

producer→prepare→真实Console/API→native全链有效，数据44065/3673/456行；五个月ZIP/CSV同已审原件，无恢复GET。原生 terminal/ranking 未改。DB恰六表：Profile1、generation_runs3（CODEX2+原生Search MANUAL1）、Candidate2，research_runs/backtest_executions/releases均0。实际页面与API/DB一致，Round1/2按钮已禁用；Development=EXPLORATORY_ONLY，Holdout/Stress=SEALED_UNREAD，FreqUI=UNAVAILABLE。历史发布时间、真实滑点、有效独立样本数仍UNKNOWN；未取独立Dev值。

项目 main a0a6229dd75724e5cbd2f892eac0b8ebcb8b6e14，无代码修改/新PR/新提交。初次请求前导入路径失败已保留，监督授权仅进程PYTHONPATH修正后完成首次实际采集。

证据入口：`result-audit.json`（全部逐笔/月份/成本）、`database-api-reconciliation.json`、`ui-check.json`、`raw-chain-check.json`、`freeze-manifest.json`、`delivery-manifest.json`。原生 `search/search-terminal.json` SHA 804e4b27c5f2b9446ba8374f08d6f41d0b677da39b436727d27f2d6127efa434；campaign e43b76cc-7a1c-47ff-a6b5-1df843c7e146。实际页面 http://127.0.0.1:49469/console 。Issue #73 交监督复核收口。
