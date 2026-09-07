# 研究知识与机制卡机械预筛

交付状态：`RUNNABLE_WITH_LIMITS`。一条本地机制卡可引用已审阅的失败知识，得到可复算的`PRECHECK_BLOCKED`或`NEEDS_EVIDENCE`及来源SHA。它是研究准备输入，不是Candidate批准、市场准入或持续自主研究。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/precheck_mechanism.py \
  --card tests/fixtures/research_precheck/candidate-card-v1.json
```

CLI只读机制卡和仓库内已绑定知识来源，向stdout输出JSON，无数据库/网络/市场执行/后台进程。正常业务阻塞也exit0，必须读取JSON状态；非法或漂移输入exit2并输出`PRECHECK_BLOCKED / INVALID_OR_DRIFTED_INPUT`。无`--run`、审批、自动写库或输出覆盖参数。

## 可复用知识和适用范围

`docs/research-knowledge/btc-eth-1000-central-v1.json`复用#127诊断、#129修复及#131终态等现有JSON/文档，逐来源绑定SHA。七类知识各有稳定ID、证据层、来源及适用边界：

| 知识ID | 机械意义 |
|---|---|
| RESERVE_ENDPOINT | 已知旧源码端点缺陷可阻塞；已修源码身份仅支持工程判断，未知源码需要证据 |
| NATIVE_CELL_MINIMUM | 冻结合成场景按risk cell、lot、实际native调用点padding算必要条件，不向上凑单 |
| SAMPLE_EVIDENCE_TYPE | 逻辑episode、订单、实际cycle、受支持自然簇不同；新候选期待次数默认为UNKNOWN |
| QUALIFICATION_LAYERS | 代码/测试、模型行为、模型净值与真实资格分层；卡片不能自授资格 |
| EXPOSED_WINDOW | 具名scope内半开窗口含warmup检查；已见片非独立、后片sealed；其他scope仍UNKNOWN |
| BUDGET_NO_REPLAY | 历史28/96及10sealed/58未分配不是新授权，旧/退役/后片key禁止复用 |
| TERMINAL_NO_RETUNE | 精确关闭的BTC_ETH_1000_CENTRAL_V1不自动重放；改ID不能证明新机制，需后续去重审阅 |

知识记录保存旧试点逐路径actual cycle与自然簇/上界，不含新计算收益，且明确不能移植到新候选。`UNDERPOWERED`是该1000USDT/central/窗口试点终态，不是所有趋势或组合机制的普遍失败结论。原20退休资源的机器映射含validation身份，但资源名称不是实际数据用途。

知识JSON及来源都先验SHA。源文件变化后本入口fail closed，需审阅更新记录，不静默相信旧字段。本记录是版本化历史知识，不读取实时预算台账；预算输出明确`snapshot_only=true`，未知其他项目预算/窗口状态不会变成授权。没有写Codex memory。

## 机制卡和输出

卡片沿用现有Candidate的`idea`、`strategy_family`、`expected_failure_mode`字段，额外记录知识引用、具名scope/UTC窗口、源码SHA、冻结场景ID、证据类型声明及预算意图。它不是已有Generation/Profile API的直接payload；当前不附加Candidate数据库或触发生成。

示例是一条未获研究批准的趋势延续想法卡，用于演示成本、数量与稀少样本约束。没有替它冻结新市场研究。`candidate-card-v1.json`及provenance记录是人工脱敏fixture，来源、版本、SHA明确；场景数字均是手造校准，不是假装采集到的行情。知识引用影响可追溯标签，不是开关；删掉引用不会跳过规则。

本切片只消费知识JSON中两份已冻结合成单资产、flat账户、1x场景，避免从LLM文字推断当前价格/ATR/手续费规则。没有场景或scope不匹配就输出缺证据/阻塞；不能把BTC校准用于ETH或多资产。不会读取卡片提供的任意证据路径，更不会把自由文本当冻结数据。需要未来真实候选的量化证据时，应由后续有限接口绑定已审阅来源，不能把这些校准数值套到实际市场。

BTC示例精确算术：`1000 × 1% / 10000 = 0.001 BTC`，lot向下量化后不变；名义金额60。原native fresh-entry stop_arg=-0.05和默认reserve0.05给出 `max(50×1.05/0.95, 0.001×60000×1.05)=63`。满足native门需要最少0.002网格数量，对应风险20，超过风险单元10。因此返回`SCENARIO_CELL_BLOCKED`，仍输出原0.001数量、不放大仓位。该必要门结论只属于合成场景，不是实际市场拒单原因或资本建议。

ETH校准即便算术过门，整体仍`NEEDS_EVIDENCE`。所有数值使用Fraction，结果保留numerator/denominator；不计算收益。此版本没有未来交易次数估算器或候选样本收据消费者，所以即使卡片填`claimed_expected_trades=9999`，可信`expected_trades`仍NULL/UNKNOWN，原claim仅为审计字段。声称已有SUPPORTED_NATURAL_CLUSTERS也不能凭类型字符串建立数量/真实资格。所有返回的`execution_authorized`和`promotion_authorized`为false，不存在整体PASS/READY状态。

## 与最初自主发现目标的真实差距

| 能力 | 当前证据及限制 |
|---|---|
| 有限研究执行 | 已有固定协议/数据/预算/单worker/终态收据路径；本次未启动它们，旧BTC/ETH试点已关闭 |
| 有界Candidate生成 | 现有Console/Profile接受受限idea并生成PENDING Candidate；仍需既有准入和外部动作，不是互联网想法自动发现 |
| 失败知识输入及机械预筛 | 本次实际CLI可运行，证据SHA和算术可复算；尚未自动接入Generation/Profile和Candidate持久化 |
| 互联网想法摄取及去重 | 当前切片未实现来源抓取/引文冻结/结构化卡片生成/语义或经济机制去重；换ID尚不能证明独立 |
| 调度与恢复 | 已有单次进程、锁、budget/terminal审计；未建设自主排队、崩溃后安全恢复决策或持续scheduler，也未恢复旧automation |
| 自动晋级风险合同 | 既有局部阶段门不等于端到端自动晋级授权；未来跨研究晋级、资金/实盘风险合同仍未建立 |

唯一最短后续依赖：由监督另行批准一个**有限来源想法摄取/去重→机制卡→本预筛**接口，复用现有Generation的受限idea字段并输出待审卡片。先固定来源集合、去重依据和数量预算，解决“下一张卡从哪里来且为何不是旧机制变体”；不让用户重新提供策略想法，也不先建常驻调度器。该接口、任何真实数据读取或研究执行都未在本次启动。

## 本次交付取舍和验证

- KEEP：现有六表、Candidate字段、受限Generation及阶段准入；它们已有明确边界。
- SIMPLIFY：新知识为一份JSON，前置检查为纯函数+CLI；不新增表/字段/索引、服务、通用规则引擎。
- DELETE：未新增需要删除的旧组件，不做无关重构。
- UNKNOWN：互联网摄取、语义去重、持续运行与自动晋级资格，不用当前CLI绿色结果冒充完成。

风险相称的验证仅为该纯输入/算术模块的快速测试和真实CLI示例：23项定向测试，包括手算native最小门、算术过门仍缺证据、LLM数值声明无效、旧源码、样本类型、窗口/warmup/半开边界、旧key及预算、SHA漂移、非法JSON和CLI确定性。无需DB矩阵、原生回测或重跑旧69/32测试。实际CLI的输出SHA、代码提交及控制不变证据见本Issue交付收据。

回滚只需撤销本Issue新增JSON/模块/CLI/fixture及README入口，不涉及数据库或运行台账。本切片完成后交监督固定SHA审阅；不自行合并关闭、不扩大执行授权。
