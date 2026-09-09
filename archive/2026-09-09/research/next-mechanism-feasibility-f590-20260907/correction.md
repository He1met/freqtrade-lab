# 一次限定纠偏：探索训练 → 冻结 → 独立验证

**撤回“必须等到 2027 年、至少 156 周”的建议，也撤回把同家族视为排除条件的推断。** 当前应是“已有探索入口，具体训练源绑定待核，独立窗资格待核”，不是整个研究 NO_GO。已见 Search 摘要可以形成假设；再次计算旧值必须另获探索授权，不能回填旧终态或冒充新独立证据。原有每个协议的 no-replay/家族预算不会因为改叫探索而自动解除。

**1. 项目确有 EXPLORATORY 入口，无需先建平台。**

- `scripts/serve_research_console.py:50` 的 `--exploration-contract` 将合同传给 Generation；`lab/codex_generation.py:1717` 记录 `freqtrade-lab-exploratory-candidate-v1`；Search 和 Console 显示 `EXPLORATORY / NOT_INDEPENDENTLY_VALIDATED`。
- `lab/bounded_research.py:455` 校验合同字段：`protocol=EXPLORATORY_SESSION_RESEARCH_V1`、`status=NOT_INDEPENDENTLY_VALIDATED`、`exposure_audit_sha256`、1–8 条 `prior_research` 引用。名字含 SESSION，但校验并未把所有探索限制为某一 session 策略。
- `scripts/fetch_okx_profile_data.py:162` 接受 exploratory source-window；`run_bounded_research_pilot.py prepare-search-data --exploration-contract ...` 对应既有来源准备入口（本次未调用）。探索必须 `development_timerange=null`；不能同时用 `SINGLE_BASELINE_V1`。当前探索 active attempt 上限 2，R1 一条 seed，不能宣称已有原生“一轮一次完整 exploratory finalist”协议。
- `lab/bounded_research.py:1976` 的共享旧源要求原源与新消费合同**均有 exploration**，且来源/窗口/暴露合同及 Profile 非白名单字段一致。因此任意旧 independent 源或旧自制 sandbox 不是立即可接入；具体源根未在本次获准读取，绑定状态 UNKNOWN。最小缺口首先是核查已授权训练源是否已有合格 exploratory provenance；若只有 independent 来源，现入口不提供任意改标签转换，需准确的来源准备授权/合同处理，不手改旧 provenance，不先要求新 runner。
- `lab/search_campaign.py:1874` 与 `lab/development_run.py:898` 阻止探索 Candidate 直接生成 Development 绑定。训练后须新冻结、独立来源、新正常验证 Candidate/单次协议；不得把 exploration 状态原地洗成验证。

**2. 只选择一个值得修正的原因：旧 BTC absolute/dual momentum 的回撤口径无效。** 台账第 64 行明确 `MAX_DRAWDOWN_WRONG_DENOMINATOR / RETIRED_TECHNICAL_DRAWDOWN_INVALID`；这是已验证的历史技术失效记录，不是经济失败。最值得做的是先恢复可信测量，不靠换币或调均线“救”它。唯一拟议增量为**核算增量**：沿用该家族单资产 BTC absolute baseline 的冻结信号定义，使用现有原生单资产费用/现金核算，并独立检查 `DD_t=(历史权益峰值-当前权益)/历史权益峰值`。不恢复多资产切换，不增加波动率仓位回调；这不是新 alpha，也不是承诺修正后盈利。

可证伪项：持仓/现金/费用应守恒；合成权益 1000→1200→900 的 peak-relative DD 必须为 25%，不能按初始资金算成 30%。当前 parser 已读取原生 `max_drawdown_account`，Binance 附加小时 MTM 使用 `peak` 分母；但 OKX spot 的逐时 MTM/原生具体版本等价性、旧源码定义及同规则迁移尚未核验，不能声称旧问题已端到端修好。本次未运行合成/回测。**没有足够证据再追加经济规则增量，故本次经济候选增量为 0。** 如迁移旧信号需要白名单外能力，报告那个具体缺口即停。

**3. 保护按具体研究和标的划分，相关性不是全球禁用令。**

| 台账所指研究/标的 | 已见训练或 S | D/H 保护或暴露边界 |
|---|---|---|
| BTC/ETH 原探索协议 | 2020-01-01 至 2025-01-01 是已见探索训练；旧 Families 1/2 各有停止/不重跑约束 | 2025 全年 outer 有 BTC/ETH 文件 SHA 再封存记录，`exploratory_access_allowed=false`；本次不释放 |
| XRP 旧短反转协议 | S 2022-01-03 至 07-01：数据 QC 阻塞，不能推为未接触 | D 2022-07-01 至 12-31 保留；H 2026-10-01 至 2027-04-01 保留；这不禁止所有其它标的同日研究 |
| XRP 最近周动量 | S 2023-11-06 至 2024-11-04 已消费 | D 至 2025-11-03 已误暴露、不能算未见；H 2025-11-03 至 2026-05-25 未采集，仍按原协议保护 |
| BCH trend28 | S 2023-11-13 至 2024-07-15 已消费 | D 至 2025-07-14、H 至 2026-05-25 保留 |
| DOGE/ADA/BNB 各自协议 | S 2023-11-06 至 2024-11-04 已观察/执行，容量与经济状态各异 | 各自 D 2024-11-04 至 2025-11-03；H 至 2026-05-25。DOGE D 已执行并有技术/诊断记录，不能再称未见；其余按原状态保留，不读取 |
| ETC weekly spot | 2024 年 S 已消费 | 2025 D、2026-01-01 至 07-01 H 保留 |
| 其它标的/更早历史 | 未命中上述记录只是未发现冲突 | 外部未登记暴露、具体 source 与协议范围仍 UNKNOWN；不能推为可用，也不能一律判 NO |

未来任一历史验证都须披露共享牛熊市场因子、同家族学习和多次选择偏差；可以是资产级验证，但不能包装为全局未见。源保护还包含相应 warmup 和 metadata 暴露规则；以上简表不是放行清单。

**仅一次必要元数据检查已执行。** 依据本次限定授权，GET `https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId=BTC-USDT`：HTTP 200、1083 bytes、响应 SHA `5868aba36f44605b113b2602986f4e2b2e08c55b6bb6381ee2d925be4ff03a12`；只展示 `instId/instType/listTime/state/baseCcy/quoteCcy`，BTC-USDT/SPOT/live，`listTime=1611907686000` 即 2021-01-29 08:08:06 UTC。无价格、K线或资金费请求，无自动重试。官方 [OKX API](https://app.okx.com/docs-v5/en/) 的 history-candles 仅称 recent years，不能由 listTime 推出最早档案时间，也不能承诺 2018–2020 覆盖。故该更早 BTC 区间仍为 UNKNOWN，不是 NO。官方 [Binance public-data](https://github.com/binance/binance-public-data) 有按日/月档案体系，但本次没有再查询第二组目录；其目录存在也不等于 OKX source 身份成立，Binance spot 当前项目不支持。未用 archive 下载或 OHLCV API 来偷验覆盖。

**4. 现在的最小路径和 root 需要决定的事。**

1. 现在即可用本次台账与代码结论修正研究判断：把旧 BTC 回撤错误从“经济失败”中移出，保留原 invalid 终态。root 可下一次仅授权读取该 baseline 的准确旧源码路径，以及 2020–2024 已见训练源的**白名单合同元数据**，确认信号能否原样进入现成单资产入口、源是否已有 exploratory binding；不先放行行情/回测。旧探索 Families 1/2 不重跑条款仍在；如要复用其 sandbox 另做测量研究，需明确授权新的有限探索合同，不沿用旧预算自动续跑。
2. 若源与信号能合法接入，冻结一次测量修正训练：不调信号/资产、不比较参数，用合成先确认核算，再按 root 单独授权的有限市场调用记录 EXPLORATORY。即使 R1 好看也不得宣称完整两轮终态或独立 finalist；是否需要剩余轮次依真实既有入口判定，预算不是必须花完。若缺源绑定，只报告最小准备缺口；不扩成研究平台。
3. 只有得到可解释训练结果，才把唯一规则、成本、仓位、评价门与一个**具名且获准、未消费、未冲突**的验证窗口一起冻结，进入新正常验证。评价按真实持有期/事件容量设定，不规定全方案 52 周、不要求全新 alpha、不要求统计独立交易这个不现实的标签。若现有协议仍要求 S/D/H，遵守其门；日历长度由所选规则和合法数据决定。更早历史资格可以继续核，但当前元数据不足；是否授权之后的有限 source 覆盖核查，才是真正的数据成本权衡。

结论：**GO_FOR_BOUNDED_TRAINING_SOURCE_AUDIT；NOT_AUTHORIZED_TO_RUN。** 不需要现在接受三年等待；也不能据此立即重跑旧数据或借用保护窗。本次只改 Git 外报告，未改工程/台账/DB/Issue，未算信号或回测。台账 SHA 仍 `b29b11a8e01f43c00b742c994fde5df2d77a54df8f02f99ba8b96e3a03b20d73`。
