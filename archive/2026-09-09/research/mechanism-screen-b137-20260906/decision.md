# 有界机制筛选决策（2026-09-06）

**NO_GO_WITHIN_CURRENT_SCOPE：本次比较的三项中，没有可立即登记为新独立 baseline 的方案。** 这不是“所有策略都无效”，也不是新的 Search 终态。真实 Search 授权/使用均为 **0/0**。不选资产、不开 Issue、不冻结 S/D/H。当前最值得消除的具体不确定性是既有 #84 的资金费时间戳来源合同；它是同族、数据阻塞的旧假设，不包装为新发现，也不自动恢复。

| 机制与原始来源（仅三项） | 收益来源、适用性与本项目差异 | 值前成本、容量、忠实表达与决定 |
|---|---|---|
| 低相对活动的流动性补偿/反转：[Bianchi、Babiak、Dickerson，2022，原始工作论文](https://www.cerge-ei.cz/pdf/wp/Wp730.pdf) | 日频、跨币 USD 现货、跨交易所汇总；持有库存与逆向选择风险的补偿。论文的截面组合不能直接推成单币永续，更不能把低活动解释成低滑点。 | 单币近似可用现有 OHLCV/rolling/shift，然而已经是 [#84](https://github.com/He1met/freqtrade-lab/issues/84) 的 DOT 低活动两日反转；相对 #82 是同族条件改进。正常永续往返约20bp，另加实际资金费；48h按假设六次各付1bp，则需有利价格幅度约26bp，非已观测优势。1d全年366根，至少三日间隔只提供约122个事件槽上限，实际完整交易未知；原40交易/26活跃周门不改。已有唯一候选，无需再写策略；数据资格仍BLOCKED，拒绝复制/换币/换spot重跑。 |
| 对冲 carry：[Schmeling、Schrimpf、Todorov，BIS WP1087](https://www.bis.org/publications/working-paper-1087-crypto-carry) | BTC/ETH现货多头+期货空头，赚基差收敛/提供套利资本；与单腿 lagged funding filter 不同，但账本已有 spot_perp_basis_funding 旧身份。把到期基差换成永续收款不再是锁定到期收益。 | 两腿同名义N，往返约50bp/N；假设净收款3bp/日，17日才覆盖交易成本，尚未补偿抵押现金机会成本、价差变化、清算/平台风险。无杠杆融资、N=250/E0=1000时，至少500资本用于现货及1倍空头保证金，剩500缓冲；年度最多约21个不重叠17日持仓槽，日结算不是独立样本。当前单一market/Profile/pair无法原生合并两腿现金、成交与保证金；新会计/runner范围，主动工程粗估2–5日且数据因果风险未解，拒绝直接实施。 |
| 加密资产特定注意力：[Liu、Tsyvinski作者研究说明](https://cepr.org/voxeu/columns/risks-and-returns-cryptocurrencies)，[原论文](https://www.nber.org/papers/w24877) | BTC/Ripple/ETH，周频Google搜索与Twitter注意力预测；新增信息来自外部关注度，不能用价格动量或volume冒充。历史回归不是当下可交易规则，更不是因果盈利保证。 | 现货只做多，周持有往返约30bp；4倍滑点下约60bp，必须由完整持有期价格涨幅覆盖。单年最多52个不重叠周槽，事件过滤后更少。现有策略输入无注意力列/外部发布时间；本轮没有取得任何当时可见历史快照证明。历史Google Trends抽样/归一化不能自动等同当时已发布值。窄导入/因果绑定粗估1–3工程日，首先仍需证明数据可得性；前瞻积累一年只有52周。没有合法可执行候选，NO_GO。 |

成本均为**筛选假设，不是用户实际费率、历史实收费用或价格预测**：spot每边10bp、perp每边5bp，正常每边滑点5bp；敏感性滑点20bp。官方[费用说明](https://www.okx.com/en-sg/help/trading-fee-rules-faq)区分市场/费率等级，[合约示例](https://www.okx.com/en-us/help/how-to-calculate-the-contract-transaction-fee)为taker5bp；未访问账户。上表小幅度为一阶收支估算，冻结执行须按实际双边名义金额核算。永续资金费每次按持仓名义金额计，[OKX规则](https://www.okx.com/en-gb/help/perps-funding-fee-mechanism)允许1/2/4/8小时周期及动态调整，不能把六次结算或固定正资金费当作历史事实。carry价格方向一阶对冲，真正要覆盖的是净收款/基差改善，不是BTC上涨。

已知负证据沿用本次授权输入及允许的 #85 delivery：ETC2024毛收益已负；DOT短周期毛正成本负；SOL/LINK无finalist、NEAR少样本、lagged funding负。三种方案都不能靠调门解释成“已盈利”。本次未再读取旧交易/PnL或任何封存D/H值。[Google官方数据说明](https://support.google.com/trends/answer/4365533?hl=en)确认抽样与按查询时段/地区归一化；缺少历史first-seen证据是本项目当前证据缺口，不是声称世界上不存在这类数据。

当前状态与去重：

- 初始b137干净detached `5797c738`，远端main已是 `f3ada868f8ea737756b7a68227cfd1829086f600`。先报告STALE_CODE_CONTEXT，随后监督明确授权fetch与本worktree精确detach；现已核对新main源码与AGENTS。local main、原用户checkout、9121及运行数据均未改。工具没有速度参数，未主动启用fast；不能证明或更改宿主实际服务档位。
- 三个指定索引只输出身份、窗口、暴露/终态白名单与键名，识别了flat `data.instrument_id`；另外只读GitHub #61/#63/#64身份与窗口token，补回ADA/LTC/BCH，未凭索引无命中宣称全局未消费。外部未登记暴露为UNKNOWN。同资产spot/perp不清零历史暴露；不同币同日历不自动禁止。
- ledger物理行44–47已有carry身份与 `RETIRED_TECHNICAL_CAUSALITY_UNPROVEN`；92–93是DOT #84，S=[2024-01-01,2025-01-01)，D=[2025-01-01,2026-01-01)，33日pre-roll自2023-11-29，Search=0，`BLOCKED_DATA_TIMESTAMP_QC`，`retry_authorized=false`。#84远端仍open，不能建重复Issue/伪造独立方向。#85已closed，ETC2024已消费、2025D仅QC、2026上半年H不释放。
- 新main `lab/bounded_strategy.py:27–69`限定输入OHLCV、5m/1d和三个populate方法；`lab/search_campaign.py:581–603`绑定单pair/Profile；`lab/market_contract.py:7–36`只接受单一spot或isolated futures，spot拒绝short/funding。`scripts/fetch_okx_profile_data.py:848–899`先验身份、月份及时间漂移，再读取rate。没有为筛选运行测试/native、数据库或Console服务。

**#84 确切解阻裁决：当前没有值得立即重试的已证变化，也没有成立的窄代码缺陷。** 原始 [terminal.json](/Users/shenjianpeng/Documents/freqtrade-lab-local/dot-low-activity-2d-cohort-20260905T140100Z/terminal.json) SHA `3ba8924e6a6e8b783d24ac55ea2ee0f022a31dafccc124eb91b7c2db9be9152d` 与ledger一致：2024-01归档row12，`1704326403000` 相对8h格点 `1704326400000` 偏移3000ms，超过冻结2000ms；原因只有 `DRIFT_EXCEEDS_LIMIT`，expected/actual月份都为2024-01。归档SHA `c6d4b272624ee05e6fc843e8a6b66c2beb499db5b390b840207e59b3c380981d`。这不是月界/时区错误，不能用UTC转换“修好”。 **字段业务语义为UNKNOWN**：本次只证实代码将CSV第3列整数时间戳相对8h网格取余并执行2秒门；原证据未证明该字段究竟代表实际结算时间、记录时间或其他时间。2秒是当前已冻结的网格对齐校验假设，不能声称是交易所实际结算时刻保证。官方允许结算延迟，也不能据此把旧CSV容差放到3秒。

S=0由同一terminal的 `actual_native_Search_attempts=0`、`search_campaign_id=null`、`native_Search_terminal=null` 共同支持。模型市场数值/研究信号结果均0；producer已在内存接触S/D futures+mark并做分页形状检查，以及一月funding前部，不能声称“完全未接触”。D未完成整段连续性QC、未物化；H未分配未采集。真实取得source次数1，进程2次中的第一次为联网前行政失败；旧source预算0，当前可执行Search预算也0（并非已消费一次S）。原 `source-acquisition` 目录当前不存在，归档未保留、Feather0、source receipt/provenance均null；旧根其余协议和失败证据保留，不能拼接恢复。源码SHA与protocol文件SHA重新计算，均与ledger原绑定一致。

经济规则、DOT资产、原S/D窗口、33日预热、原净收益/DD/交易数/集中度/敏感性门可以保留；**不能说旧source预算原样可用**。任何再取值必须由监督新增明确、有限source授权，记录为关联旧失败的新来源尝试；总source尝试将从1增至2，Search仍最多一个baseline。也须先审查原producer接触层与其他登记暴露，不能因S0清空暴露记录。现在不改ledger、不创建新root、不重开Issue（#84本就open）。

再次采集合理的最小可观测变化是：交易所明确修正该月归档，或提供可核对的修订/字段语义证据；获监督批准后，才以一次有预算QC取得修订字节，验证SHA确实变化、身份/全部相关时间戳通过原2秒与月份合同，以及完整来源连续性。仅hash变化仍不够；若相同坏字节/同一错误则停止。当前没有观察到这种发布变化，不能把“也许下载会好”算依据。窄修复只有在新增证据证明producer误解**另一项字段语义**且能用纯合成案例证明修复、保持2秒硬门时才值得提案；目前证据不支持。转换数据源、改变结算时点解释或8h合同属于新范围，先交监督，不伪装bugfix。

所以本次具体建议是保留 #84 的条件恢复资格，但**不立即重采、不再重复原因诊断**，由监督裁决等待来源修订，或另行授权一次明确的数据来源合同评审。代码改动0；后者主动评审可限30分钟、实际运行0，外部修订等待时间UNKNOWN。即使技术解阻成功，费用后优势仍须原唯一S评估价格毛收益、双边费用/滑点/实际funding后净正、原风险/样本/覆盖/集中度/敏感性/现金与BH对照全门；S通过也只能申请独立D，绝不继承论文或#82毛收益作为证据。

没有选中新候选，因此不制造源码、资产选择或S/D/H完整协议。后续若重新开放旧假设，也必须保持旧数据暴露、原门和终态，重新单独裁决合法新source身份及一次baseline预算。当前没有S探索性经济证据，更没有独立D/H资格；D后H/Stress仍需用户另行授权、同一research_run_id。无Release/Demo/订单权限。当前阶段就此结束，不继续循环搜索文献。

监督最终裁决：原数据条件未变化，不批准原样重试，不放宽2秒阈值；本执行任务停止旧证据核查。后续是否仅核官方字段语义或改变研究方向，由监督决定。
