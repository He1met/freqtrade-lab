# Issue #63：Search 已终止，无合法 finalist

最终状态：`SEARCH_TERMINATED_NO_FINALIST`。恰好两次实际 Search，均技术有效，但分别只有 2、4 笔交易，均未达到冻结的至少 5 笔门槛。归因为**样本不足**，不是经济亏损，也不是数据失败。正收益和小样本高 PF 不能证明稳健或合格。本 cohort 不再重跑、调参、换币或移窗；Development 未执行，Holdout/Stress 保持 SEALED_UNREAD。

Issue：https://github.com/He1met/freqtrade-lab/issues/63 ，保持 OPEN，交监督任务验收，不关闭为成功。旧 #62 保持停止状态 OPEN/BLOCKED_DATA。

## 实际结果与冻结门槛

| 指标 | 冻结门槛 | R1：stoploss -20% | R2：stoploss -10% |
|---|---:|---:|---:|
| 技术状态 | VALID | VALID | VALID |
| 交易数 | ≥5 | **2，不通过** | **4，不通过** |
| 净收益，占初始1000余额 | >0 且 ≥1.25% | 8.144704804% | 7.079143201% |
| Profit factor | ≥1.10 | 10.7548887681 | 4.0101493861 |
| 最大回撤 | ≤15% | 0.834935692% | 2.3517581% |
| 平均持仓分钟 | ≥10080 | 128880 | 63720 |
| ROI退出次数 | 0 | 0 | 0 |
| 原始ZIP内 funding_fees 合计 | 实际存在且有限 | -10.95963145945 | -11.06531749061 |

唯一未通过项是交易数。两组都包含引擎在 Search 末端的常规 force_exit；R1 另有1次 exit_signal，R2 另有2次 stop_loss、1次 exit_signal。未添加强制持仓、ROI或时间条件。实际ZIP逐笔 fee_open=fee_close=.0005、leverage=1、is_short=False，资金费实际进入引擎结果。slippage=UNKNOWN。

## 数据与执行证据

- 本次范围内核验 #62 消费索引的36个引用hash、77个canonical元数据文件，未发现任何timeframe的LTC消费/封存记录；相关LTC Issue搜索无匹配。外部运行仍 NOT_AUDITED_UNKNOWN。未用旧市场价格/PnL选币或选窗。
- Search [2024-02-01,2025-02-01)，Development [2025-02-01,2026-02-01)；两阶段均120日预热。Holdout/Stress仅元数据 [2026-02-01,2026-07-31)，180日。
- 首个官方UTC+8月档86/86条通过后，连续完成25个月档全窗预检：2193/2193原始资金费timestamp精确8h网格、offset=0、唯一连续、身份及有限值通过。最终月档只选1条，83条窗外rate未解释。原档保留。
- 正式producer没有原档复用参数。监督批准仅采集衔接澄清：原样再次获取同一25档，真实receipt，全部ZIP/CSV hash与本root预检原档一致。未替换transport或修改producer。该澄清不改变窗口、经济门槛、策略或Search次数。
- 全预检通过后先建新隔离六表DB/Profile供正式CLI读取。正式source及独立切片、producer/consumer、hash/identity/UTC连续性/行数/保留期验证通过后才生成Candidate。
- Search slice：日线486、mark11664、funding1098；Development slice：日线485、mark11640、funding1095。Development只有数据准备，无引擎执行或经济评估。
- R1经正式Console/API调用Codex生成；批准前精确冻结AST/hash核验。R2批准前文本仅class名与stoploss变化，精确AST/hash/parent绑定及项目single-factor verifier通过。随后正式API执行第二轮，无第三次。
- 两个 generation 的 tool_event_count=0，均COMPLETED；Search compact terminal、attempts及外置hash绑定已由现有项目保存到generation_runs，非孤立JSON报告。

## 身份与SHA

- Executor task：`01a06e15-ffd9-7240-b492-9761a1285e98`；监督：`01a05dcc-17fd-7972-9177-9fed95e4b07a`。
- Worktree：`/Users/shenjianpeng/.codex/worktrees/1ad9/freqtrade-lab`；结束时 clean detached HEAD 和 live main 均 `dc82c61fe8a27a654977344755c088412518d858`。无业务代码/schema改动，无commit/PR。
- Git外0700 root：`/Users/shenjianpeng/.codex/runs/freqtrade-lab/ltc-exact-grid-dual-sma-28-84-v1/cohort-v1.0cg9aqkv`。
- 固定Freqtrade源SHA：`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`，clean tag2026.7；Python3.13.13、ccxt4.5.68、pandas3.0.3、pyarrow25.0.0。模型gpt-6-astra；本任务tier未暴露，UNKNOWN，未改配置。
- Profile：`ltc-exact-grid-dual-sma-28-84-v1`。
- R1 Generation：`3243aed5-a73a-438a-88c4-9fa8a137d003`；Candidate：`c63b42f8-9e16-424a-bb77-544ab93c4903`。
- R2 Generation：`1b705ba4-d20d-445c-9fdd-7f365ebb484e`；Candidate：`17c38879-1aab-4097-ac73-fd5f02cf8dc9`。
- Campaign/Search projection Generation：`192e766e-8ec9-4d35-a926-0890e54321b1`。
- ResearchRun ID、Development metrics、finalist binding：NULL。
- Source provenance SHA：`7210ee53ba8c9962ed1c4566043b7389390869dc331f97cbb7bf9ba3c7433714`。
- Source receipt SHA：`64fc8eb6ebda56fef2301eeaedca1539a83533d71d0544867bd107647740de50`。
- R1 code SHA：`9e8846c3a1abab6e6fba3e4c5d342b6f030ce89e2878a76591c7dc492153a191`；ZIP SHA：`a1a4cacd2914d12998f76e99400d8e7f2d49585fb84033770a6203e38c7bc3ff`。
- R2 code SHA：`5dbd4cdabea354505dc52ce45b445028743c677b9b491edd300c24acc609e67c`；ZIP SHA：`ce4b783c0fecba14ff754dbcca31e4d8e99be7a184e834e35449bedbb927d583`。
- Search terminal SHA：`6368e1abf98d36f837f7acc55adf3fc4f55faa4f9ade7d0810600a3c0c95af39`；trials SHA：`c7feadb3240718402894222cc4a4657f0ae80c3cd4696798da6288c9cce6d2e0`。

## 最终对账与限制

现有六表计数：research_profiles=1，generation_runs=3（两次CODEX生成＋一次MANUAL Search终态投影），candidates=2，research_runs=0，backtest_executions=0，releases=0。外键检查通过，未伪造pending ResearchRun。项目verify_search_terminal_projection、数据库response/evidence、API、terminal/trials/result及真实ZIP源码/关键指标一致。

已实际打开 `http://127.0.0.1:64601/console` 核对：终态、两次attempt及hash与API一致；Search两轮按钮禁用；无finalist；Development暂无数据；Holdout/Stress封存。页面仍显示既有generic Development READY，这不是finalist证据，未点击/执行。FreqUI与公共Freqtrade Webserver不可达，标记UNAVAILABLE，不影响已验证CLI引擎结果，也不声称FreqUI覆盖。

框架UI显示active3/hard6，本Issue的2次上限已耗尽；框架余量不构成继续授权。没有全套测试或独立smoke，只有必要数据、静态及真实引擎/持久化对账。启动Console曾因运行目录尚未建立报错，建立0700目录后正常启动；一条超1200字符生成请求在创建Generation前被400拒绝，缩短表述后提交，未改变策略或增加Search。日志中的pyarrow FutureWarning保留，未扩展修复。

原始精确网格只排除人为归整偏移，不证明逐秒实际结算、成交或滑点完全模拟。结论仅为本冻结cohort样本不足，不能据此宣称策略稳健、可交易或找到合格策略。监督验收后如需新方向，应独立预注册；本cohort不恢复。

机器核验摘要：`final-audit.json`；数据核验：`source-verification.json`、`funding-precheck-terminal.json`；生成审阅：`r1-static-review.json`、`r2-static-review.json`；原始数据/ZIP和日志均在本root下。
