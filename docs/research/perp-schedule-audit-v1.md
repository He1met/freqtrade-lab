# BTC/ETH 永续调度迁移盘点 v1

核验日期：2026-09-08；新方向 Issue #162。此表记录真实管理接口、本机只读配置和任务状态，不把文件存在视作已运行。

| 真实 ID | 调度器/范围 | 迁移前 | 已核迁移后 | 频率与依赖 |
|---|---|---|---|---|
| `freqtrade-lab-2` | Codex heartbeat，BTC/ETH永续研究 | ACTIVE（旧现货职责） | ACTIVE（已迁移） | 每30分钟；新目标 `01a08189-98b5-7013-b4ea-9903cd57b031`，新提示词已复读匹配 |
| `freqtrade-lab` | Codex cron，旧一次性 cohort 领取 | PAUSED | PAUSED | 每小时；local，项目 `ce2174f2-cbe8-490d-93e8-4acd3bb135df`，`gpt-5.6-sol`/ultra；绑定已消费旧契约 |
| `automation-2` | Codex heartbeat，旧 SOL/spot 授权等待 | PAUSED | PAUSED | 每10分钟；目标 `01a05dcc-17fd-7972-9177-9fed95e4b07a`；不恢复 |

迁移前快照由主任务保存于 `/tmp/perp-migration-v1`。暂停通过真实 `automation_update` 完成；再次读取 automation.toml 已核 `freqtrade-lab-2` 为 PAUSED，`updated_at=1788879893916`。三个 ID 均调用了管理工具 `view`，工具只返回已在应用渲染卡片，没有向模型提供最近调度运行、真实下次触发和调度内部时区；这些字段保持 **UNKNOWN**，不能从 RRULE 自算后写成已核实。旧任务的 startedAt 是会话运行时间，不证明调度触发来源。最终新提示、目标、启用与真实测试以主任务交付收据为准。

## 旧执行与入口

- `01a07c6a-d535-7030-814c-7775d0f27f99` 核验时 idle，其最新完成回合明确恢复了旧机制筛选。
- `01a07c7a-f82e-7e20-8bbc-4d10a3bc8bb8` 核验时 active，回合 `01a08184-2507-7ac2-a17c-5c7a26b91ef9`。暂停定时器不会证明已运行回合停止；主任务需要显式停止/重定向该旧执行并核回执。新 heartbeat 不应继续绑定旧监督上下文。
- 最小禁止新现货活动入口是 `scripts/spot139_forward.py` 的 `init/daily` 与 `scripts/issue155_forward.py` 的 `tick`。保留控制读取 `check/status`、合成测试、原始收据和历史结果；不重写旧冻结 manifest 以让它重新通过。
- #155 `slots()` 的价格源实际是 Binance **现货** `/api/v3/klines`，不可改名作为永续。Coin Metrics 供给完整性检查、原子写入及来源 SHA 机制可在新版本复用；旧月度事件/价格评分必须停止。`lab/spot139_forward.py` 固定现货域和钱包状态，不能直接成为永续采集主干。

## 本机边界

- 当前用户 `crontab -l` 经获准只读核验：`no crontab for shenjianpeng`。初次沙箱拒绝已通过获准只读方式解决；没有新建 cron。
- 扫描用户及系统 LaunchAgents/LaunchDaemons 的可读 plist，未发现指向本项目 `freqtrade-lab`/#139/#155 的任务。发现的是其他 `Freqtrade Ai`/canonical V1.3 服务，包含 order writer 与 runtime；全部保留，不属于本次修改范围。一个无关第三方系统 plist 解析失败不等于该服务不存在。
- 当前 GUI launchctl 列表无 freqtrade-lab 匹配。只读进程盘点发现 PID 73991 使用 `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python` 运行 `webserver`；未见精确 `trade` 模式。展示服务保留；本次未停止任何系统进程。
- 应用安装位于 `/Applications/ChatGPT.app`，bundle `com.openai.codex`，版本 `26.901.51231` / build `8109`；`codex-cli 0.153.4`。CLI `--help` 没有 `cron` 调度命令。本次用已支持的 Codex 管理工具，不虚构命令或编辑内部数据库。
- `uv 0.11.7` 可用；系统 Python 3.9 缺 `tomllib`。主仓库和旧 1b63 工作树的 `.venv/bin/python` 不存在；已观察到独立旧 native venv，是否适合新研究必须按主任务实际版本/依赖预检确认。未访问 auth、API key、账户数据库。
- 当前系统显示 `Asia/Shanghai` 相应的 `+0800 CST`。附件日汇总 `21:00 Asia/Tokyo` 明确折算为本机 **20:00 Asia/Shanghai**；周复盘 `周日18:00 Asia/Tokyo` 为 **周日17:00 Asia/Shanghai**。市场事件与持久状态统一 UTC。
- 本地任务依赖 Mac 与应用运行、网络和模型额度。连续后台能力、模型认证未来有效性、精确资源费用和真实下次触发均不能由一次工具成功推断。

## 最小调度承接

保留一个 heartbeat 真相源。拟保持30分钟，由持久 CLI 判断小时收盘后10分钟的数据任务、日/周报告和有限研究队列；这是对附件约15分钟健康检查建议的明确资源折中。CLI 本身不启动 daemon，不调用模型 API，不把 due 状态报告为采集或经济验证成功；等待数据时退出。真实重绑定、试运行、恢复和启用后状态应由主任务另附收据更新。

## 最终实施核验

主任务已完成旧执行停止确认：无在途操作，旧feature/price/model/native均0；旧监督确认不再派现货。#139/#155/#161按方向迁移归档，PR163关闭并保留分支，均非经济验收通过。

`freqtrade-lab-2` 已由管理接口重新启用为“BTC/ETH 永续研究与数据推进”，目标为当前任务 `01a08189-98b5-7013-b4ea-9903cd57b031`。再次读取真实automation.toml确认ACTIVE、目标正确，prompt与 `docs/research/perp-heartbeat-prompt-v1.md` 逐字一致，更新时间epoch毫秒1788881374346。其他两个旧任务保持PAUSED。前后快照最终持久路径为 `/Users/shenjianpeng/Documents/freqtrade-lab-local/perp-autonomous-v1/migration/`。

正式入口 `scripts/perp_tick.py` 已在真实root运行：研究登记RUNNING时返回WAIT_RESEARCH_WRITER/0GET；首轮finish后返回NO_OP_ALREADY_CAPTURED/core_complete=true/0GET，显示唯一后继QUEUED。明日预算未到的claim实测被拒绝，持久state字节未变、市场调用0。验收包含19项采集、12项调度、3项集成测试；原生pytest薄封装内部4项合约检查，合成累计3次、市场4次。四个真实原生结果的资金费/订单/MTM对账通过。

第一轮报告和唯一后继已落入持久队列。日/周checkpoint只是观察时点的状态，不能证明过去按时运行。当前层级是 **配置ACTIVE + 真实CLI/预算/恢复验证；首次自动唤醒待观察**。管理工具未返回last/next字段，Computer Use明确禁止访问Codex本体，所以实际下次触发仍UNKNOWN；未绕内部数据库。首次真正自动唤醒会追加 `migration/activation-observed.json`。
