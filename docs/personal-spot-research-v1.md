# PERSONAL_SPOT_RESEARCH_V1

用户结果：在本任务独立入口使用现有 Console 完成 OKX 单币、仅做多、无借贷现货的 Generation → 批准 → 有界 Search → 有条件 Development，并诚实呈现终态。盈利未知；合格仍需另行授权 H/Stress 和人工判定。

## 基线与范围

2026-09-06 本 worktree `/Users/shenjianpeng/.codex/worktrees/9121/freqtrade-lab` 干净，HEAD 与 `git ls-remote origin refs/heads/main` 均为 `5797c73813ee7b6ab047f4d7bfeccf4d1b391b6e`。不动原 checkout 和旧数据库。#84 保持其阻塞状态，不恢复旧 cohort。

- KEEP：现有六表、Profile/Generation/Candidate、原生 Freqtrade、来源与窗口验证、Search/Development 绑定及 Console。
- SIMPLIFY：在现合同增加窄 spot 分支；资金费与 mark 明确 N/A。新独立非敏感 DB，不迁移旧库。
- DELETE：本轮没有获准且必要的删除项；不建设通用 runner、交易所平台、服务或 SPA。
- UNKNOWN：资产历史连续性、独立窗口及经济优势，必须分别取证。

只调整现有 domain/trading_mode/margin_mode CHECK，增加 `OKX_CRYPTO_SPOT`/`spot`/空 margin；不加表、字段、索引。保留旧永续兼容，spot 拒绝 short/leverage/funding 规则及永续来源。

## 批次与验收

1. Profile/schema/Candidate 与原生配置（3–7h）：临时六表 DB 接受合法 spot，错误组合在副作用前拒绝；旧永续单测回归。
2. producer/consumer 与 Search/D/import（5–13h）：优先复用现下载能力，仅必要身份、凭据隔离与 QC 薄接线；单一 spot OHLCV，S/D 隔离，同源合同与 artifact 校验。
3. Console 与端到端验收（4–12h）：现页面真实 Generation/批准/Search/条件 D；未知保留 NULL，funding N/A，终态及 Git 外路径可恢复。无 finalist 不造 ResearchRun。

静态工程合计 12–32h；2h 内交首个可运行进展。超过范围或需要新表/runner立即交监督裁剪。每个小批精确提交、PR 交监督，不自行 merge 或关闭 Issue。

T0：相关单测。T1：受影响模块回归，纯合成 native 语义检查最多两次。T2：一次临时六表 DB + 真实 Console/API 整合，验证用户入口与失败行为。无理由不反复全量测试。原生固定 2026.7 / `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`，使用指定 sibling venv 与显式 PYTHONPATH，不改 native/venv。

## 研究门

最多比较三种机制权威文献与可表达性，最多预注册两假设，选一主假设。总真实 Search 最多三次，任何观察市场经济结果的 smoke 均计入。备选启用条件和值前参数明确；失败不得在旧窗口改参重放。

读本轮市场数值前，向监督交完整冻结提案：资产及暴露依据、timeframe、S/D/H 预留及 pre-roll、完整源码、仓位、现金/买入持有对照、费用依据/滑点、DD 计量/研究预算、净收益、成本敏感性、交易数/覆盖、异常成交与集中度、预算与停止规则。低频按合法历史容量设计，不事后降门；少量盈利仍可 UNDERPOWERED。DD 不是用户真实风险偏好。

仅在监督放行后有限采集；事前固定请求/重试边界。D 仅 producer QC，S 全门通过并获内部阶段放行后才读取执行。H/Stress 留封存，用户另行授权；无 Release、Demo、交易权限。技术失败分类网络/数据/合同，不能自动换币换根或救策略。

最终交一份短终态报告与必要原始回执：唯一入口、代码 SHA、DB/artifact 路径、测试与 UI 证据、真实 Search 预算、研究结论及限制。
