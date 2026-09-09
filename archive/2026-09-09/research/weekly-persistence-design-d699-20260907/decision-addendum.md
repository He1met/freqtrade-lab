# 一次决策补充：合成可行，市场尚不放行

本文纠正并收紧 `proposal.md` 的推进路径、基准记录和边界表述；不重解释旧 BNB 否决。原提案 SHA `2272bf7bccb9e4d12af19979cea124293ba9771de01a74c4b1d804b2ecbd239b` 保留不改。

## 原生合成结果

已完成授权的2组人工序列、共2次原生 `Backtesting.backtest`，2026.7，合计1.323秒（脚本计时），网络调用0。只使用人工XRP报价/精度/档位、人工每8小时1bp资金和人工小时mark，绝非历史XRP数据。没有使用自制撮合器：真实 Binance 类、原生信号移位、撮合、订单、钱包、资金计算均未改写；仅用无副作用观察包装记录 `backtest_loop` 前后现金。OS `sandbox-exec (deny network*)` 加 Python 网络拒绝；没有DB连接/写入或Generation。第一轮脚本在任何fixture/撮合前因误取验证函数返回值失败，改为其真实None返回语义；正式2组均完成，未重跑。

随后只读取已产出的 native trades/钱包轨迹完成48条显式断言，0次追加撮合。证据为 `synthetic-native-report.json`、`synthetic-assertions.json` 和两个fixture目录下的原始JSON/Feather。原生 `backtesting.py` SHA始终为 `7afec2d7c6f924642d410ff3974bf9932982bc9cf2f8c194b266a0b8c77ebf55`；策略草稿SHA `652eb9a89f5e35ade766bb6cb6c1108f15e04813222dbaf1ccb7539d4be1df9f`，现有bounded AST通过。

| 规则 | 实际人工序列证据 |
|---|---|
| 周日闭合→周一00:00成交 | 首多2030-01-28；所有10笔开仓均为周一00:00，无周日提前成交 |
| 多→空同根 | 2030-02-11旧多先平，新空同时间开；首组free从750.000016→1000.8038461（含旧仓完整净额）→750.8038861 |
| 空→多同根 | 2030-02-25旧空先平再开多；轨迹两个事件、旧仓先消失，中间现金状态精确传给下一次原生调用 |
| 同向不换手 | 首组01-28多一直到02-11；03-11多一直到03-31，没有逐周凑笔数 |
| 周中止损等待 | 第二组多01-30止损后02-04再入；空02-13止损后02-18再入，均为下周一 |
| 零方向 | 03-04平多，到03-11一直现金 |
| 前缀因果 | 每组21/35/49/56/70根五个前缀，指标及四类信号与完整序列同前缀逐项相等 |
| 保证金/成本/资金 | 250名义金额仅受人工精度取整；逐笔纯价格−双边fee+native资金=原生净额；最终钱包与全部原生交易相加对齐 |

原生钱包free不是实时扣完所有费用/资金的保守可用现金，首开显示约750而非749.75；不能把它当最终现金合格证明。另调用既有 `audit_native_trades` 对同批原生成交审核，没有自制资金核算：两组保守最低free分别748.407253、688.164786 USDT，均可执行；边界资金收款被保守扣减。人工获利/亏损数没有任何市场经济含义。

**窗口末端准确含义**：人工授权数据评分 `[2030-01-21,2030-04-01)`；原生 `end_date=2030-03-31` 指最后一根日K的起始时间，而审计 `end_ms=2030-04-01` 是来源排他终点，两者并不差一日来源。最后剩余多在03-31 00:00按最后K开盘121.428571强平，不是04-01或03-31收盘。草稿无显式末日条件；原生 `not is_last_row`/`can_enter` 已拒绝最后K新仓。实际fixture没有最后K新仓，源码证明其无条件保护；未增加第三组去重测。

需一起冻结并接受的原生近似：最后K仍先执行其常规exit/stop检查，只有余仓再按该K开盘force_exit。因此不能声称“最后一日开盘先于所有止损无条件清仓”。两组未强行制造末日stop，只读源码已说明顺序；若root要求那种严格开盘清仓模型，此草稿不证明它，不能用测试结果包装成等价。

各正式窗口的native最后K分别为S 2024-11-03、D 2025-11-02、H/Stress 2026-05-24；同样禁止最后K开仓，余仓按原生该Kopen强平，未用排他终点外价格。强平全部成本/资金/PnL归所在阶段最后日历块，剩余时间现金不计虚构利息；强平episode不是自然完成样本，亏损仍保留。块边界用当时可清算MTM，跨块不断仓；边界处成交/资金只按时间先后记一次。该native末K路径是回测假设，不是实盘确定可成交事实。

## 1. 修正探索标记与可推进路径

原提案同时写SINGLE_BASELINE与NOT_INDEPENDENTLY_VALIDATED，若指项目正式exploration字段，确实不成立：`bounded_research.py:713`拒绝single+exploration，exploration要求development_timerange=null；`search_campaign.py:2299`拒绝exploratory finalist binding，`development_run.py:898`拒绝带exploration的Candidate。不能删除已有探索标记、复制Candidate改标签、伪造独立协议或绕过该判断。

项目 `INDEPENDENT_VALIDATION_REQUIRED` 是**待满足独立验证要求的运行模式**，不是已经独立、也不是论文收益背书。本批还没有Candidate/来源/Search，因而现在可由root事前作一次实质设计选择：若确认“XRP目标资产直接未见的互斥S/D/H + 完整披露其它币共同因子学习”是有条件的分阶段验证协议，可在首次新值前冻结一个全新普通single-baseline cohort，并把具体跨资产暴露清单/台账SHA/限制写进冻结protocol及现有Generation请求的协议引用；不是将任何已执行EXPLORATORY结果转正。S仍是探索性选拔证据，D/H只是资产级外样本，需要逐阶段核验和最终共同因子风险审阅。正式UI模式保持INDEPENDENT_VALIDATION_REQUIRED，文稿也不得声称全局无预知。

若root判断现有宏观/家族学习使该D/H不足以承担这个有条件验证要求，就应现在 `NO_GO_MARKET_UNDER_THIS_PROTOCOL`，**不先花市场Search预算再撞EXPLORATORY_ONLY**。另一诚实选项是纯EXPLORATORY、没有D承诺，但不推荐它作为当前“找到真正合格策略”目标的交付路径。最终真正合格仍需审查共享因子暴露及证据强度；不能只靠历史门变绿，也不预先指定/占用任何旧未来保护窗。

## 2. 基准真实来源、预算与合法入库缺口

保留固定250初始名义long buy-and-hold成本基准门，不因接口不足删除。现有低层 `_run_scenario` + `scripts/run_freqtrade_backtest.py` 能按策略SHA/来源/窗口执行原生场景，`_screen_candidate` 已有保留原数据收据、派生新策略provenance的模式。但主策略provenance绑定精确策略路径和SHA：不能把buy-and-hold文件塞进主策略收据、不能覆写原来源。基准必须使用同raw acquisition父SHA和同阶段文件SHA的独立派生manifest、自己代码/config/原生ZIP/资金audit/receipt；不得追加另一套市场取值或假称业务Candidate。

**目前未发现合法通用benchmark写入/展示API。** 原来的“1 Generation + benchmark只外部report”只能保留文件，不能声称已真实入库。Search拒绝附件仅支持REJECTED，不能拿它塞成功基准；D/H execution需绑定主Candidate，同一个ResearchRun，不能把基准伪装成第二个D/H或main finalist。原提案“唯一产品缺口只是XRP allowlist”撤回。

推荐最小工程选项（待root授权，当前未实现）：在已有Candidate.metadata_json上增加**仅本实验的比较附件入口**并让现有Console显示。入口验证主Candidate/协议/阶段、基准独立provenance父来源SHA、双方原生ZIP及真实cost audit/次数receipt；Search阶段绑定真实campaign，D/H/Stress阶段绑定已有主research_run_id。元数据仅保存经验证的路径/摘要、双方指标、comparison verdict和费用口径，原始大文件仍Git外；不新建表/字段/索引，不增加benchmark Candidate、Generation或ResearchRun。写入口一阶段一附件、幂等、失败前不写、不可修改原证据。S完整protocol review包含该门后才传PASSED handoff；D/H及最终资格仍由root按全部外层门决定，不把core绿灯写成full-protocol绿灯。若要求机器自动挡住每个D/H/Release按钮，那是额外阶段附件检查范围，必须在同Issue显式列明，不默默扩展。

这仍是一个尚待实现/验证的缺口，不是现成合法路径；目前不授权先跑经济数据。估计pair绑定30–60分钟，比较附件/现页投影/定向临时DB验证60–120分钟，全部复用原生runner和解析/成本函数。粗规模：限定附件CLI/验证约80–160行、现页展示30–60行、定向测试60–100行，合计约170–320行，未经实现不承诺精确行数；只复用Candidate.metadata_json/updated_at及已有原生证据字段。若root不接受此小范围，可选择保留Git外强绑定报告作为手动研究证据并明确“基准未入DB”，但这不满足当前要求的真实入库验收，不能装成已交付。

基准还有边界要在市场前固定：它不是weekly reentry，不用主策略8%止损；近乎全损stoploss不是严格buy-and-hold。项目bounded Candidate要求`-1<stoploss<0`，因此不应伪造一个可晋级benchmark Candidate来绕规则。应通过已授权的受SHA绑定原生诊断调用表达持续1x long、无自主止损（保留交易所原生liquidation），并确认原生配置可表达，若不能则报告模型保真缺口。此次预算只验证主策略，没有额外运行基准撮合；该路径目前是代码层候选方案，不是已运行证明。

## 3. 总预算、核心门映射与外层判断

预注册经济native最大预算现在明确为：S主策略1+基准1；D主策略1+基准1；H主策略1+基准1；H Stress主策略1+基准1，共8次（Search部分2次，不超过六次Search总上限）。H/Stress用同封存来源及同主research_run_id，基准只是比较附件，不创建第二Run。每阶段基准fee与主策略相同：S/D/H每边0.001，Stress每边0.002，资金事件和保守审计不变。前阶段失败后后续预算全停；已运行的基准或失败调用都记消耗，不能以diagnostic/retry免费重算。已完成合成2次单列为非市场证明；它们不占/不扩充经济预算。若原生流程另外强制smoke/lookahead经济调用，先显式计入总预算再授权，不能藏在工程检查里。

| 意图 | 现有核心配置/实际口径 | 必须保留的外层门 |
|---|---|---|
| S/D >=12自然完成episode | Profile min_development_trades=12，核心只数原生trade（含强平/stop），不是独立样本 | 将同一连续目标方向中的止损再入合并；完整方向episode>=12、正/负各>=4，boundary未完成不算；其PNL全计 |
| H/Stress >=8自然episode | min_holdout_trades=8；同样仅是trade数必要条件 | 完整方向episode>=8、两方向各>=3；Stress多出的stop不新增独立episode |
| 平均自然持有>=3天 | economic_gate minimum_average_holding_period_minutes=4320作用于所有原生trade平均，并非自然episode | 两个平均都报告并都须>=4320；不拿较长episode平均覆盖较短原生trade平均 |
| PF | Profile min_profit_factor=1.10，全阶段原生/保守核心统一 | 完整自然episode与全交易PF区别披露；Stress实际可用核心也>=1.10，收紧原提案“>1.0”，不为它新增可变stage PF合同 |
| 收益 | S/D economic_gate minimum_net_profit_after_base_fees_pct=1.0，保守资金门同用；H核心净正 | 外层H>=0.5%，Stress净正，pure-price gross>0；若实有核心要求更严须同时满足，不能靠手工绿灯覆盖core拒绝 |
| DD | Profile max_drawdown_pct=10，原生及保守资金审计均检查 | 所有MTM块、去最大episode、同成本基准风险收益门仍是完整protocol review内容 |

4/52或2/29个日历块不等于独立市场复制；长持仓不拆成独立周。自然episode报告需对照策略周目标序列，不能仅凭交易列表推断止损再入的独立性。bootstrap本轮删除实现计划，仅保留未来可选解释，不写脚本、不成为继续研究理由。

**提交root一次决策**：主策略原生时序可行已证；没有新市场值。现在决定有条件验证口径、明确native末K近似，以及是否授权“XRP绑定 + 限定比较附件/来源派生 + 基准表达验证”的最小实现。否则维持NO_GO_MARKET。没有probe/采集/DB/产品代码/Issue动作，也没有再增加合成组。
