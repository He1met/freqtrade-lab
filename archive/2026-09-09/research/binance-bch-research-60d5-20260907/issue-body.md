目标：通过现有 Profile → Generation → Candidate → Search → 同 ResearchRun 的 D/H/Stress 和 Console，完成首批 Binance BCH/USDT:USDT 日线有界趋势研究。成本后价值未知；允许诚实负例或样本不足终结。

前置 PR #95 MERGED / #94 CLOSED，已核远端 main fa1d19e8b56ed7cc5a9bf78d24b6d1be6114f9ac。本任务独立干净工作树 /Users/shenjianpeng/.codex/worktrees/60d5/freqtrade-lab，分支 codex/binance-bch-bounded-research-v1。监督任务 01a05dcc-17fd-7972-9177-9fed95e4b07a 负责协议冻结和阶段授权。

- [x] 首次经济评分前协议、台账冲突与自然样本容量检查，并由监督冻结。
- [x] 原生来源复用/有限采集、来源绑定与因果检查；通过现有页面生成批准 Candidate。
- [x] 有界 Search 和真实终态，原生指标与保守成本投影分开。
- [x] 阶段边界验收：真实 NO_FINALIST，因此 D/H/Stress 不运行，ResearchRun/Execution/Release 均0。
- [x] 项目页面/数据库/产物闭环、成本分解、风险与局限、终态报告。
- [x] root 已独立核验固定交付SHA，并授权合并/按负例关闭 Issue。

首次准备不读取经济结果、不采集 D/H、不做 native smoke、不启动 Search。拟议 single-baseline 一轮一次，首次评分前固定参数/门槛；上层预算最多两轮六次不意味着需要凑满。8–16 主动小时上限目标。无候选不制造 ResearchRun；数据问题为 BLOCKED_DATA，技术 INVALID 不当经济负例。

只用新 Git 外数据库与证据根 /Users/shenjianpeng/.codex/runs/freqtrade-lab/binance-bch-research-60d5-20260907。六表不变；不增字段/索引/平台/runner，不修改原生核心或原始 checkout，不读凭据或敏感旧数据库，不发布或交易。已有技术暴露周 [2023-11-06,2023-11-13) 从评分排除；D/H 不缩短救结果，跨交易所同资产不算独立。

## 实际交付，2026-09-07

文档提交 `2656bd19b0bc1c01675ce8a1453210536b207a5e` 已与远端分支逐SHA核对，工作树干净。唯一变更 `docs/issue96-bch-trend28-negative.md`；无schema/runner/实现变更，无raw/DB/产物入Git。root已核文档、DB和ZIP后授权交付关闭；PR #97 已按精确head guard合并，merge/main SHA `fcb52ff59013b3a49271a259293069b62907578e`。以真实NO_FINALIST负例完成Issue；D/H/Stress为N/A未执行，绝非通过。

真实 Search campaign / MANUAL generation `7c7450dc-67bb-4f27-baa3-961a4eaa043b`，原生一次，technical `VALID`，`SEARCH_TERMINATED_NO_FINALIST`。Candidate `89c0c792-93a3-4e3b-b8ac-67a56eca4dea`；CODEX generation `bdd08312-e427-4ce8-9145-5612a862704b`。9总交易但仅7有效自然交易（排除0分钟止损与force_exit）；两方向5/2、自然覆盖4/5块。净/PF/DD/有效样本/去最大赢家门失败；完整核验见 `search-protocol-review.json`。

纯价格毛利 -13.250440 USDT；原生资金费 -19.898564；已扣手续费/滑点代理各4.468098；原生净 -42.085199；附加保守扣减0.131588；保守净 -42.216787、PF0.836102。原生DD16.873488%与保守小时收盘MTM DD25.299915%口径分开；小时极值27.890252%只是补充压力，不是H Stress。去最大赢家后 -195.768148 USDT。不得仅换费率或资产挽救。

Git外根下 `terminal-ledger-record.json` / `terminal-ledger-receipt.json` 可核追加；全局台账本次前缀112022 bytes/SHA `84e8c49eab8b40eb39559e0468a914ae80506dbf7b60cb93402e9ecb18891271`。原生ZIP SHA `395aa758d92e79eb26fcbc5e3c569ee2b4fd56cad7095d5b0c15a02b83ec588b`，路径在报告中。`source-publication.json`、`source-aggregation-qc.json`、`aggregated-retained-v2/aggregation-manifest.json` 绑定旧S和一次新D抓取；新D33 fetch、3,095,502解码bytes、0重试。首次JSONL双换行仅本地格式失败，原响应未变，修正证据留存。

入口 http://127.0.0.1:8796/console 通过真实浏览器核验：NO_FINALIST和原生/保守指标可见，Round1/2/D/H禁用，D暂无数据，H/Stress封存，ResearchRun null，FreqUI UNAVAILABLE/版本UNKNOWN。`verify-readonly.sql` 可通过 sqlite3 -readonly 对该根新lab.sqlite核查；六表计数1/2/1/0/0/0。T0无市场因果检查、现有producer/consumer、原产物逐笔对账和实际页面足够；未重复工程全套测试。

本任务约0.5主动小时（粗估，非精确计时；不含前置工程），没有凑8–16小时预算。下一步只建议最多约45分钟的一次只读机制去重/未消耗窗口/成本与样本容量筛选；短期过度反应回归仅候选机制，不承诺有效，不挪用D/H，不新增实现或试跑。
