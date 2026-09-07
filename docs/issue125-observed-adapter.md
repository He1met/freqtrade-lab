# Issue #125：真实源绑定的探索模型准备

本交付只完成 adapter、结构转换、固定模型和执行门禁。没有市场回测结果，没有新 GET，也没有调用 Backtesting 构造函数或 start。首批 10 个探索任务的 manifest 已生成；后 10 个流程检查任务封存。首次结构转换遇到解释器已安装包与锁定 checkout 的导入路径不一致、随后 manifest 字段重复，两次均在准备阶段失败；修复后重建，旧输出保留在 Git 外，没有占用 native 槽。最后一次准备前加入数据库拒绝与完整性检查，之前成功的准备包也作为 superseded 保留。

## 源和可见范围

`issue123-capture-terminal.json` 与其中 36 个原始响应的长度、SHA、时序、关联 mark 和覆盖范围共同绑定源。完整已采集区间只做结构检查：每币 10,248 小时、1,281 个 Regular 资金费事件，每名义 8 小时槽一个事件。附加等级为 `OBSERVED_API_COMPLETE_FOR_EXPLORATORY_MODEL`；原始 QC 的 `BLOCKED_DATA`、历史费率周期权威证明及实际结算资格 `UNKNOWN` 原样保留。

向策略和原生输入只提供 2023-11-01 至 2024-11-01 exclusive：274 日暖启动和 92 日探索，每币 8,784 小时。原生执行窗口从 2024-07-31 21:00 UTC 开始准备完整性检查，08-01 00:00 后才形成新意图。每币探索资金费 276 个，保留原毫秒时间、rate、同事件 associated mark。预留后片的研究入口在读文件前拒绝，生成的两个 Feather 文件不含后片。

## 唯一模型

机器合同为 `protocols/issue125-observed-semantics-v3.json`。五 mode 共用一个资金账户、BTC/ETH、central 63/2、base/stress 和 V2 风险退出/暂停逻辑。00:00 一次冻结信号、ATR、目标、候选、原数量及权益；01:00 只能向下约束冻结数量并激活 episode。旧家族午夜退出、老化、C 更新和暂停恢复不推迟。00/08/16 禁止增仓，允许减仓。

资金费不移动时间。小时 open 成交在该小时事件之前；delta=0 固定 fill 后 fee。事件变仓现金流取 `min(0, -q_before*r*m, -q_after*r*m)`，未变仓保持有符号现金流。没有未来 15 秒成交推断。金额用精确 Fraction，核心边界 Decimal 60，无 gate epsilon；模型资金费显式替换 native 资金费，调整 native free 后再与模型可用资金取保守约束。费用在原事件时点进入模型风险账，订单动作最早下一小时。

原生撮合保留。窄 funding loader 直接提供原始事件表，避免按小时 inner join 丢掉非零毫秒事件。每个实际订单必须有允许的来源 tag、整数小时、对应原 open/tick 价格；盘中或 native stop/liquidation/force_exit 即使时间恰为整点也使模型无效。策略回调错误被原生 wrapper 捕获后，sticky failure 在 validate_row 前强制终止。任何数据库模式都拒绝。固定 1x tier 只是装配假设，不是历史清算规则认证。

最后可用小时 2024-10-31 23:00 UTC open 请求平仓。无法执行则保留真实库存并失败，不能用 native 期末 force_exit 充当合法退出。实际资金费和订单不因失败而抹掉。

## 证据与结论边界

未来获准运行会在 Git 外保留 manifest、native archive、每小时 trace、稳定 ID 的 episode 激活/退出/原因、各家族净额前意图及风险缩放/暂停、实际订单与 fee、实际账户仓位周期、逐资金费记账点和 evidence-index SHA。订单和仓位周期数量均不代表家族独立样本。最后仍存在的逻辑 episode 标记边界截断。

家族 natural-cluster gate 明确 `NOT_EVALUATED`。原 30 自然簇门、未来独立确认门不变；后续归因与计数规则必须先冻结，才能只读这些证据统计，不重跑 native、不看收益选有利计数。未知值不填 0 或通过。本批输出最多为固定模型假设下净值/风险与技术可行性，负净值只说明该固定模拟路径为负，不能充分否定整个机制。

所有结果必须同时标记 `SIMULATED_UNDER_ASSUMPTIONS` 和 `NO_REAL_ECONOMIC_QUALIFICATION`。实际发布时间、舍入误差界、历史交易规则和连续盘中价格风险覆盖均 UNKNOWN；“保守”只在假设模型内部成立，不是实际 PnL 下界。没有晋级、统计优势或实盘资格。

## 执行门禁

用户入口：`scripts/run_portfolio_observed.py --prepare`，必须使用锁定的 Python 3.13.13 环境；该命令只创建新准备目录，不能覆盖、激活或回测。已有最终包见机器收据 `issue125-preparation-receipt.json`。

未来执行入口为同一脚本 `--run-key <首批精确 key>`，目前不可运行。缺少固定外部 `observed-v3-activation.json` 即失败；本交付不创建 activation。监督对完整固定 SHA 包统一审批后，外部 activation 需包含 schema `issue125-observed-activation-v1`、status `APPROVED_FIRST_EXPLORATION_BATCH`、审批记录、最终执行 commit、plan SHA 以及精确首 10 key→manifest SHA。运行时要求工作区干净且 HEAD 等于该 commit，同时复核所有项目代码/协议文件、native tree/依赖/解释器、源与输入 SHA。

20 个新旧键的一对一替换只有 activation 后生效；后 10 键仍硬拒绝。全局仍为 96 槽，已消费 8，20 个计划键之外保留 68，未借失败调用扩容。与原 budget 使用同一 writer.lock；锁内重新核对 anchor、activation、plan、manifest 和全部获准 SHA，再预约。每 job 在构造 native 前持久化 RESERVED 并做全局 checkpoint，失败也消费，不重放、无自动重试。原旧账完整前缀必须一致。首个工程装配失败、MODEL_INVALID、超时/中断或 CONTROL_INTEGRITY 终态会停止整批，后续 key 全部拒绝；当前没有继续执行或重试绕过开关。有效路径的负净值或 DD 超门不等于工程失败，保留 SUCCEEDED 技术终态和真实模型门结果，不自动调参。执行后的原生 archive 与证据摘要还需监督审阅；本 PR 不合并/关闭 Issue，不授权 native。

## 验证

114 项针对性测试通过，涵盖纯资金费因果顺序、冻结数量/午夜旧家族处理、实源前缀不变性、实际订单来源检查、sticky failure、期末失败保留库存、精度、逐 episode 证据及共享预算封存/重放/失败门禁，并回归既有 source/风险/预算/费用逻辑。

另外使用锁定环境逐一校验最终 10 个 manifest，以及直接在普通 namespace 上调用 funding loader，验证每币 276 条、毫秒时间逐条一致、无 NaN；未创建 Backtesting 实例。真实 Feather 转换是结构验证，不含行情收益、手工撮合或评分。没有实际执行过 native，因此装配、订单回调和真实 native 结果尚待首批获准调用验证。

## 734b78c 初审修复

每个 job 冻结 **180 秒** 内部 wall-clock 上限，沿既有合成上限，不因市场结果扩时。SIGALRM 抛出不会被 native `except Exception` 策略 wrapper 吞掉的 `BaseException`，与 SIGTERM/用户中断一起占槽并保留完整 exception traceback、已有 trace 和终态。该计时器由被绑定的 runner 自身实施；manifest 明确 `native_timeout_seconds=180`、`wrappers=[]`，没有外部 `sys.settrace` 或事后补救包装器。终态审计在关闭 native 计时器后运行。

预约前冻结已批准的代码、原 raw、Feather、事件表、market/tier、解释器、manifest、activation、plan SHA，以及当前项目/native Git HEAD/tree/dirty 和依赖版本。预约后另冻结原生账与输出 manifest，保存 `pre-call-integrity.json`。成功、异常、超时路径都执行相同的 `terminal-integrity.json` 复核，并复查 anchor；漂移单列 `CONTROL_INTEGRITY`，禁止 SUCCEEDED 和经济结果发布。原始 native 文件仍作为未可信诊断证据保留，不能充当有效经济输出。kill -9 或不可写存储造成无法完成收据时，既有 pending 槽仍不允许重放。

静态核对锁定 native `backtesting.py:944` 默认调用 `price_to_precision`；其 `rounding_mode=ccxt.ROUND`，正数 TICK_SIZE 半 tick 为 HALF_UP，不是 ROUND_UP/DOWN。21 个边界用例精确相等。market entry 不使用 limit custom-price rounder，因此额外验证全部 17,568 个获准小时 open 已在冻结 tick 上；在 native 月度推导精度下，探索 open 的纯舍入结果同样逐条不变。未放宽任何价差容忍，也未创建 Backtesting 对象。

新增纯测试覆盖实际内部计时器、占槽/终态与 traceback、成功/异常两路径七类控制文件漂移、锁内 anchor 变化、冻结时 SHA 变化、通用装配与 MODEL_INVALID 首失败停止后续九键，以及有效负路径不误停批次。旧 `734b78c` 准备目录完整保留为 superseded，新逐 job 清单重新生成；budget 仍不激活。
