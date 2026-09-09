# BTC / ETH 永续自主研究迁移 V1

本轮已将活动研究切换为 BTC/ETH USDT 线性永续。现货任务停止、历史保留；新政策只作用于新研究批次。代码、源数据、原生计算和调度验收分别记证据，任何工程通过都不代表已找到盈利策略。

## 已核实现状

- 2026-09-08 远端 `git ls-remote origin refs/heads/main` 实核：`89eaa8fb3beeb67fb089dc870031d585aa318a55`。原工作目录 `cf33eb9` 落后149个提交，未提交 `docs/product-requirements-v1.md` 保留。新分支 `codex/btc-eth-perp-autonomous-v1` 在独立 `.worktrees/btc-eth-perp-v1` 上实施，未改原main。
- 统一实施 [Issue #162](https://github.com/He1met/freqtrade-lab/issues/162)。附件完整读取，原文与SHA保留于Git外迁移快照及新政策。
- 原生 Freqtrade 2026.7 / source `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`，当前venv Python3.13。主机裸 `python3` 不是正确研究运行入口；本批固定经过实测的venv。
- 当前唯一账户/场所/资金未核实，不读凭据或账户：Binance USD-M 是暂定研究来源，执行场所未确认；1000USDT是研究假设。BTC/ETH共用钱包、初始1x，不通过杠杆扩大收益。
- 原项目Profile/Console说明曾仅支持5m/1d，不应据此声称原生不支持1h。本切片使用现有Freqtrade原生Backtesting接口薄装配；无需新增表、前端、服务或交易引擎。当前没有实际交易部署。

## 已执行范围迁移

| 对象 | 迁移前 | 迁移后与证据 |
|---|---|---|
| `freqtrade-lab-2` | ACTIVE，30分钟，旧监督任务，含#139/#155/#161现货职责和20%硬限 | 管理接口先PAUSED防旧动作；新脚本验收后已重新ACTIVE并绑定本任务，新提示词复读匹配。详见调度验收 |
| `freqtrade-lab` | PAUSED，旧每小时cohort路径 | 继续PAUSED，不改旧冻结内容 |
| `automation-2` | PAUSED，旧SOL/spot研究 | 继续PAUSED，不恢复其它交易标的 |
| #139 | 现货B V3前向计划尚未开始 | 按方向迁移归档，禁止新现货实验/前向评分；历史原始证据完整保留 |
| #155 | 月度USDC→ETH现货三个未来观察待到期 | 按方向迁移归档，未来现货槽位不再执行；历史合同不改，Coin Metrics可在新合约因子协议中独立复用 |
| #161 / PR163 | 注意力现货机制活动分支 | 原执行任务确认 STOPPED_BY_DIRECTION_CHANGE，metadata1已完成；feature/price/model/native为0，无在途；PR保留并关闭，不删除分支 |
| 旧执行任务 `01a07c7a-f82e-7e20-8bbc-4d10a3bc8bb8` | 用户迁移时仍active | 已发送停止范围指令并收到停止确认；工作树干净，`69adc0be866932a19759ebee086187f6b936c64b`保留 |
| 旧监督任务 `01a07c6a-d535-7030-814c-7775d0f27f99` | 可继续唤醒旧分支 | 已确认不再启动现货、不并发改调度/仓库；新heartbeat不再绑定它 |

旧前向脚本与冻结manifest逐字保留，避免破坏原SHA/check语义；活动入口通过真实调度移除、Issue归档和顶层现行政策禁用。旧README示例统一标为历史入口。无需为归档删除共用采集代码或批量改写旧协议。

## 新旧规则区别

新政策 [BTC_ETH_PERP_AUTONOMOUS_V1](../protocols/perp-autonomous-policy-v1.json) 于2026-09-08T15:08:27Z生效：约20%为研究风险目标；略高结果完整披露并可归类风险待定标。旧批次20%硬限与风险否决不追改，实际交易保护和权限不变。新公开采集允许有界瞬时故障退避，永久语义/权限错误停止该端点并根据明确信息版本化修复，不再每一个GET要求人工批准。历史暴露保持开发用途，未来确认不用于选择。

首个问题是1h突破/延续基线是否从方向持续性或波动风险获得净增量，固定减风险做公平对照。最多4个变体、单市场worker。OI与链上只在可靠可用时点和覆盖成立时加作后续因子，不阻塞价格/资金费主干，也不制造多年OI。

## 调度与回滚

唯一调度真相源继续使用 Codex `freqtrade-lab-2` heartbeat；不新增系统cron/launchd或额外服务。保留30分钟健康检查，将附件建议15分钟调整为现有支持路径的保守频率；这不是交易保护轮询。行情仅在整点K线完成并延迟10分钟后更新，已完成小时不重算，错过的行情回填不称及时信号。

时区明确迁移：附件每日21:00 Asia/Tokyo = 每日20:00 Asia/Shanghai = 12:00UTC；周日18:00 Tokyo = 周日17:00 Shanghai = 09:00UTC。使用到点后的首次心跳，调度延迟或休眠恢复会如实记录；没有独立常驻15分钟采集器。

调度原文快照、附件原文保存在 `/Users/shenjianpeng/Documents/freqtrade-lab-local/perp-autonomous-v1/migration/`，包括三个真实automation的before.toml。管理界面/工具提供修改和暂停；不编辑内部数据库。回滚时先暂停 `freqtrade-lab-2` 并保留新收据，可恢复原提示词/目标/频率的快照字段，但现货仍保持PAUSED，恢复现货方向需要用户新指令。代码为独立分支，可保留并切回历史main，无需改写Git历史。

本地任务依赖主机开机及应用运行，云任务不自动拥有本地目录；CLI没有Scheduled管理入口。已核[官方定时任务说明](https://learn.chatgpt.com/docs/automations?surface=app)。管理工具未返回真实上次/下次运行时间时记录UNKNOWN，计算出的计划时间不能冒充调度器证据。

新状态、实测结果、报告和唯一下一方向以本目录最终交付记录及Git外队列为准；首次被调度器自动唤醒与手动CLI验收分开记录。
