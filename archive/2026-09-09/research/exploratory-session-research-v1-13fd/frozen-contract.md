# EXPLORATORY_SESSION_RESEARCH_V1 — 路线 A 值前冻结

创建任务时间 `2026-09-05T00:57:21Z`；Issue #69；工作树 `13fd`；分支 `codex/exploratory-session-research-v1`。本合同只授权后续监督放行后的两次探索，不授予独立验证资格。

**数据**：LINK/USDT:USDT、5m；Search `[2024-02-01T00:00Z,2024-07-31T00:00Z)`。一次纯 metadata 日期修正已获监督批准，避免原终点所需的 August funding 整包。共享 source 预滚 73 根：OHLCV 从 Jan31 17:55Z，mark 从 Jan31 17:00Z，均止于 Jul31 00Z。A 自身 startup/lookback 72 不变。funding 采用实际历史 8h 费率，语义 `[Feb1 00Z,Jul31 00Z)`；Feb–Jul 六个 UTC+8 月档整包 raw envelope `[Jan31 16Z,Jul31 16Z)`，实际包元数据和端点另留 receipt，超出则停止。整个包的曝光与语义选取分别记账。

已见跨币训练、#49/#52 已实际执行并公开的 Development 降格为本轮探索训练；旧结果不变。其未打开 H、2025 outer、#62 和其他仍受保护 Dev/H 不释放。`exposure-audit-v2.json` SHA 与 `lookback-coordination.json` 一起说明范围；索引外为 UNKNOWN。B 将共享同一原始 source/SHA，但独立 SQLite/campaign，不能称两份独立数据。

**策略**：区域参与时钟假设，参照 NYSE 常规 09:30–16:00 ET（https://www.nyse.com/trade/hours-calendars），不是加密币开收市，也不声称完整复制论文。所有纽约周一至周五，包括美国假日；固定 America/New_York 处理 DST。
- R1 `SessionBaselineV1`：15:25 的 5m bar 在 15:30 闭合；早段方向 `close.shift(66)/open.shift(71)-1`。正做多、负做空、零不入，next-open 15:30 入，15:55 bar 闭合后的 16:00 出。
- R2 `SessionAgreementV1`：唯一新增 `close/open.shift(5)-1` 与早段同号过滤；零或相反不入。`changed_factor=session_pre_entry_agreement_v1`，已通过归一类名后的严格 AST 比较。
- 同一固定 `stoploss=-0.02`、`minimal_roi={}`、1x、单持仓；每天最多一次，止损后不重入；signal/entry/exit 不冲突；末端 `force_exit` 单列。纯合成原生 FT 已覆盖冬夏 UTC、双方向、周末、零信号、R2过滤、止损及 force_exit。

**资金与 Gate**：wallet 2000 USDT、固定 stake 500（25% wallet）、max_open_trades=1；2%止损对应约0.5%初始wallet风险，费用另计。129个工作日最多129次机会；事前 minimum trades=50（覆盖约39%机会；仍可能统计不足）。R2稀疏未达50即失败，不降门槛。net>0且>=1.25%初始wallet（25 USDT）、PF>=1.10、peakDD<=15%；ROI退出必须0。

**成本**：至少5bps/side，按各腿实际notional计费；原生实际funding入账，禁止0替代缺失；原生5m next-open无额外滑点，真实滑点 UNKNOWN。另固定报告1bp/side附加滑点敏感性（逐腿notional扣减），不能把它称真实成交。按129笔×500近似notional，达到25 USDT门槛最低平均毛边际约13.88bps/round-trip（含10bps手续费，不含funding）；50笔时约20bps。加固定2bps/round-trip滑点敏感性后分别15.88/22bps，仅算术而非收益预期。不得加杠杆/stake救结果。

**预算与停止**：A唯一R1一次＋唯一R2一次（即使R1经济负，技术有效仍按冻结对照执行R2），与B合计最多4次真实尝试；串行原生FT，共同冻结后才获取新值。无额外真实smoke。网络429沿用项目有限重试，缺口/成本/源/窗口不匹配保存失败证据并停止；不新窗补测或重跑经济结果。技术失败只可由监督决定后续，不自行重采。初始工程4活跃小时，60分钟无可运行增量需报告。

**实际入口**：`http://127.0.0.1:8791/console`。R1/R2已由实际 `/api/generations` 生成且技术批准；项目 `fetch_okx_profile_data.py` 获取公有源（原生 download-data 无法单独提供所需历史 funding 月档），`prepare-search-data --exploration-contract ...` 形成只读隔离 acquisition；页面 `/api/search-campaigns` 发起两轮，原生 `screen-search` 账本执行。新 root `/Users/shenjianpeng/.codex/runs/freqtrade-lab/exploratory-session-research-v1-13fd`；source 目标 `source-acquisition`；A Search 目标 `search-campaign`；数据库 `research.sqlite`。只有该新库在范围内。

**冻结身份**：Profile `exploratory-session-link-v1`；R1 Generation `f0d527af-a0b2-48ac-a755-34efdcf46d19` / Candidate `c2fd8e00-0c62-4100-bce0-8bdd30313737` / source SHA `09308a1f7535ebca5dae811f0396a16cbe3ccaaed4127e5077a2c850d2321cbb`；R2 Generation `10fee03c-c583-4cf5-86aa-377f6512b13b` / Candidate `531a6f9f-ec14-445a-b429-b3c2c258047d` / SHA `e3d234f07b6911bfc66e5d6f62e3b83efa95b4777bd0db58dd3764f3b5c4122b`。原边界草稿 Generation `179f5886-4865-4795-a404-4decaccf4559` 技术拒绝保留，未进Search。

**限制**：EXPLORATORY / NOT_INDEPENDENTLY_VALIDATED。Dev日期 UNKNOWN/null；H/Stress SEALED_UNREAD；探索拒绝创建ResearchRun、Execution、Release或提供finalist→Dev绑定。六业务表不变；Search-only后三表0行是正确结果。本轮不运行Dev/H/Stress/Judge/Release/Demo/交易。
