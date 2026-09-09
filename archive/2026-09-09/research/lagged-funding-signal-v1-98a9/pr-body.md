现有原生链路能记 funding 费用，但受限策略无法使用历史 funding 信号。本变更加入一份完整固定模板：UTC 00:05 按 24h 价格转弱做空，R2 仅多一个 D−48/40/32h 已结算 funding 均值条件；共同 guard、08:05 退出、3% stop 和禁用 ROI 均不可改写。

整个源 AST 精确匹配，生成 request/Candidate 通过既有 JSON 绑定信号合同、Profile 与探索身份；仍由现有 source SHA/窗口/网格和 consumer 校验绑定数据。原始 funding 非 open 列须符合 native 2026.7 的零占位表示。R2 移除唯一 funding conjunct 后，剩余整份 AST 必须与 R1 相同。无新表/字段/依赖/服务，不改 native、producer 或离线 runner。

验证：
- 9 个受影响模块回归：362 passed；新 source failure 负例补充后的 funding 专项：36 passed（与前者重叠）。使用临时 SQLite、pyarrow 25.0.0，无跳过；仅 Feather 弃用警告。
- 实际本地 HTTP：合成 fake Codex 进程→生成→预览/批准→R2 父子绑定；探索 Candidate 被 Development 拒绝。未调用真实模型。
- native 合成 gate-04、最终 gate-05 PASS：原样 SHA-bound adapter→Backtesting.start→原生 ZIP。5/4 笔合成交易、正常 480 分钟、stop 55 分钟、signed funding 正负方向、零值/缺失/补行、共享 guard、未来不影响过去、连续日与尾部均验证。
- 最终 gate 还使用现有 producer writer/provenance→prepare_search_data→consumer，验证合成来源链；新 March–July/289 合同只检查元数据行数。原始 ZIP、完整 argv/log、初期探针 setup 失败均保存在 Git 外私有目录。

限制：关联 #71，保留 Issue 开放，合并/关闭交监督核实。本批不进行真实行情读取/采集、经济回测、正式 Candidate/ResearchRun、Holdout 或交易。最少 32h 滞后仍只是历史 as-of 假设，发布时间 UNKNOWN；工程 PASS 不代表合格策略。家族当前 EXPLORATORY_ONLY，未来独立验证须另行冻结并授权合法 handoff，本次不实现晋级。
