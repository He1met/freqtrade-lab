# XLM spot SMA90：唯一Search结束，无finalist

actual campaign `d381227c-eb46-4e14-8fb4-4fb45241924b`，S `[2021-05-01,2023-01-01)`。
真实HTTP、项目terminal、native ZIP及DB的MANUAL terminal projection已核对一致。
技术状态VALID，研究终态SEARCH_TERMINATED_NO_FINALIST。一次真实S，剩余0，无重试。

| S指标 | 实际结果 |
|---|---:|
| 毛价格PnL（费用前） | -492.13199344 USDT，约-49.2132% |
| 原生净PnL（已扣fee每边.001） | -504.63986144 USDT |
| 基础额外滑点（实际每腿名义额×.001） | 12.50786800 USDT |
| 基础成本后净PnL | -517.14772944 USDT |
| 敏感性固定路径算术估计 | -542.16346545 USDT |
| 原生最大回撤 | 50.46398614%（上限20%） |
| 原生PF | 0.04110039 |
| 自然平仓 | 13（要求≥6） |
| 完整90日暴露组 | 5（要求≥4） |
| 去最佳组后基础净PnL | -500.63346877 USDT |

失败已经发生在毛价格层面，不能归因于仅费用吞噬收益。经济、原生风险及集中度门失败；样本数门通过不改变no-finalist。原生手续费没有重复扣减。13笔均是固定约500名义仓位的完整入/出两腿，无缩仓/部分成交，逐腿重算与native总净PnL误差约3.52e-9 USDT（舍入）。

敏感性不是另一场native回测，也不能当作可执行路径收益：第13笔前按高成本账本现金为504.69022934，0.99倍小于500，固定仓位资格已失败。基础路径在全部已执行入场前均满足现金检查；基础最终现金约482.85227056，已不足以继续放置完整500仓位。未通过降低stake重跑。

在明确经济及原生DD硬失败后停止额外计算。逐日计成本MTM DD和B&H诊断未计算，记录NULL/UNKNOWN，不拿原生DD冒充逐日MTM验证；H bootstrap未实现/未读取。分组与集中度只对本次S原交易做协议算术，不构造删组后新回测。

证据：`search-economic-audit.json`及其一次性算术脚本；`search-http-terminal-context.json`；`terminal-identity-verification.json`。原始native ZIP SHA `5dc143f4f192c33d38de26de9f037b1018a0381f288671eaa7858822b5c86008`，terminal SHA `07ec71b7bf402a868827e2aa392f8210d26052345c10a880d5108bd8e3fe227d`。

DB：Profile1、Generation2（候选生成1+Search终态投影1）、Candidate1、ResearchRun0、Execution0、Release0。D/H/Stress保持SEALED_UNREAD，原source八文件及原protocol SHA未变。没有新候选、换币、换参数、倒转信号、R2或新Search。

工程PR91已合并`7ae2b6b6c45cfb57c40a13dccd697ce1c57d08a4`，与经济失败分开记录。Issue90待监督验收关闭；不会因这次现货失败断言合约有优势，也不会在已消费窗口重筛下一策略。
