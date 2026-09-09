# GNO/BTC 1m 历史窗口资格核定

唯一结论：**B，BLOCKED（本次审计标签，不是 native 或经济终态）**。已有记录足以判定当前 Jan→Feb→March 路径及改用 March 做校准/Search 不合格；不是缺具体合同的 UNKNOWN。阻塞类别是 **BTC 参考窗口的数据资格/封存冲突**。现货工程授权是另一独立门，即使授权也不消除该冲突。本次提前停止，不提出新工程或其它币种。

关键新证据是同一 Issue #45 cohort-v3 的两个窗口文件职责不同。顶层 `window-spec.json` 只声明源窗口截止 `2026-03-01T00:00:00Z`，并不声明之后可自由分配。其 `development-pilot/window-spec.json` 明确 `holdout_start_utc=2026-03-01T00:00:00Z`、`end_exclusive_utc=2026-03-31T00:00:00Z`，即 UTC 半开 **[2026-03-01, 2026-03-31)**；不是到 April 1。原文件 SHA 与有限索引一致。相同 cohort 的 acquisition provenance 绑定 `BTC-USDT-SWAP`、`BTC/USDT:USDT`、OKX futures、1d；Search acquisition contract 明示 `holdout=SEALED_UNREAD`，D 为 `20250901-20260301`。这些是具体 BTC 绑定，不是因多币目录或相同日历推导封禁。

精确原证据均位于 `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-45-trend-holding-semantics-v1/cohort-v3.ZfK52c/`：

| 文件 | SHA-256 | 作用 |
|---|---|---|
| `window-spec.json` | `6d70a16366677f4edc89dfffaf1ca5f1d4fe2392bdee47248516b360874424f0` | 源窗口终点，不足以释放 H |
| `development-pilot/window-spec.json` | `a76be93e96c0a9d89b946b0a0f4f247daceabb28c434dead82b98e1813e386bc` | H 精确边界 |
| `development-pilot/acquisition/retained-data-provenance.json` | `50f722f576eb6ca6fce21fabff63a2c5c0c647e2c22bd92a1340940de9decc91` | BTC/venue/product/D 绑定 |
| `search-campaign/acquisition/retained-data-provenance.json` | `f20e99f9ceaac426dde73f09a55b46d3fc02ca5f88b350d161bcea64316327b4` | BTC 绑定及 H SEALED_UNREAD |

旧 ledger 共 84 行、SHA `96aa9ce415690f8e8efd97caeab4ce9dadf75ecb1b5fe5a52dfe9b479b331edd` 已核相符。仅对白名单元字段投影：line 48 的 BTC March 确为 `COVERAGE_CONTINUITY_ONLY_UNUSED`，signals/economic 都 false；这只能描述该次 QC，不会覆盖另一个 cohort 的 H 保护。line 49/51 定义 Jan Search、Feb reserved D；line 52 economic_results_opened=true、root_replay_allowed=false，保留已消费状态。精确 lagged-pressure contract 和 March receipt 哈希均与委托一致；实际来源为 OKX BTC-USDT spot 1h，March 全闭合、无认证，不读取其指向的数据文件。

因此 R 把 March 留作未核资格是合理的，但不能据 QC 无经济消费判为可分配。换 Binance spot 或 1m 不能重置同一 BTC 参考的信息接触/保护；不声称与 OKX swap 字节相同。本次没有把 BTC 保护扩展给 GNO；R 已核验交付只表明有限索引未发现 GNO，外部未登记仍 UNKNOWN，未做全球审计。

March 31→April 1 的一天**不在上述 H 合同内**，但本次不将其认定 eligible，更不靠其 1440 根 1m bar 拼成可信校准→S→D→H。后续窗口已有委托指明的接触线索，本次没有明确可用的额外历史候选，故不追加扫描。结论不声称所有历史研究永远不可能；也不以未来 H 尚未齐备为停止历史 S 的理由。本次停止的原因是已找到具体保护冲突。不存在可据本结果批准的精确分段协议；样本量/经济判据、preroll/标签成熟/embargo 尚未预注册，不能在看收益后补调。

唯一下一门：**监督记录该路径因 BTC H 冲突而停放并结束本轮资格搜寻**。恢复必须先有针对同一 GNO/BTC、覆盖校准及 preroll 和 S/D 的明确新独立窗口资格证据，且不改变既有保护；本次不提出解除保护，不授权进一步搜窗或采集。spot schema 授权不能作为该门通过的证据。

本工作树 `/Users/shenjianpeng/.codex/worktrees/66dd/freqtrade-lab` 已读 AGENTS，detached、干净，HEAD 与本次 `git ls-remote origin refs/heads/main` 均为 `0ace04b7c10ea35fb8ce6f25e043ac78be87c19e`；无活动 Issue 开发，未读取 Issue 绩效正文。原主 checkout 完全未触碰，其 behind28/未跟踪文件状态仅来自委托，不声称本次复核。使用 audit 技能及两份适用引用；记忆仅用于定位技能背景，窗口结论均来自本次原件核验。

执行仅涉及上述元信息、已核 R 交付和有限 LTC 元索引；一次索引输出过宽被截断，随后收窄至 Issue #45，内容仍为索引中的契约/状态元字段，未读市场值或绩效。未下载 ZIP、未发归档 HEAD、未读 DB/行情/价格/收益/交易/funding rate/封存值；未写代码/schema/ledger/GitHub，未启动采集/native/服务/Gen/Candidate，也未更改网络或模型设置。只新增本 Git 外 0700 私有目录两份报告。
