# 已执行最小预检：本窗口 NO_GO

2026-09-07：监督批准更紧的5个单日fundingRate probe，取代下文原5GET提案。实际首日2021-01-04即失败，HTTP200/3事件/337bytes，associated mark不是有限正值；仅1GET，未执行其余4GET，无exchangeInfo/K线/收益计算。原响应SHA19d96bc0efa8001aa7ed8a4f9a420d54fb494f3b02af44424d591daf1fd60626。metadata-probe/receipt.json与ledger-append-receipt.json为最终证据；原锁追加1条DATA_METADATA_ONLY、旧135943bytes前缀不变。D/H没有发生本次接触。

**BLOCKED_DATA；当前早期窗口在BINANCE_ASSOCIATED_MARK_BOUNDARY_V1下NO_GO，经济UNKNOWN。停止该方案设计和候选生成，不放宽associated mark合同。下一步需要监督另选合法窗口或明确数据合同决策，不自动执行。下文为数据前比较记录，预算和阶段建议均未授权、已不构成可执行计划。**

# 下一轮有界可行性（待监督批准，2026-09-07）

**唯一推荐先检验 ADA 日线冲击延续、48h持仓的数据可行性；当前不能称可执行或盈利。** 先申请下述5 GET边界元数据probe。早期associated mark缺失风险高，失败即停止，不先开发。尚未创建Issue/新采集/Generation/native/写业务DB或ledger；只新增本文。

## 当前基线与复盘

已读任务01a07a3d最新收尾。当前8941 worktree干净detached HEAD，HEAD及本次git ls-remote main均fa6e49e4a0d9b53345821bf5312bf3443e7b68a1，无需切换。远端Issue101 CLOSED、PR103 MERGED。ADA final receipt SHA867548ba3ce64b12893922c1699b76f36e9852dd0db27348738d596c0b8896e0验证一致：14/5/9、PnL NULL、Search0、六表1/1/1/0/0/0，已完成项目预筛闭环。原仓库及旧worktree未修改。

BCH旧趋势Search负；DOGE公开D事后诊断保守净-6.65684%、PF0.75959、DD15.54521%，正式D仍FAILED_TECHNICAL_UNRECOVERED；修复解释器不修复经济结果。ADA复合回撤因容量不足结束，不能叫经济亏损。不重算任何旧S或读取旧D/H行情。

## 三案比较与唯一选择

| 方案 | 经济与容量取舍 | 成本与工程 |
|---|---|---|
| ADA 4h、过去24h冲击延续、24–48h持仓 | 6次/日观察可更早入场，但重叠24h收益与冲击聚集不提供6倍独立样本。单仓24/48h的年度理想上限364/182，尚未扣抑制与止损 | 每笔20bp不变；24h资金边界敏感性4次、48h7次。可能减少等待日线的价格损耗，但也可能提高噪声/换手，实际改善UNKNOWN |
| **ADA 1d、单日冲击延续、48h** | 只保留冲击和流动性有效性，不再叠趋势/回撤/次日确认；已知动量家族试验，非独立alpha。准入相隔>=3日，一年自然完成上限121 | 每笔20bp+7次资金敏感性。现有链支持；保留同币，避免机械换币 |
| ADA 1d冲击回归、72h | 简化旧回归家族，但DOGE跨期失败降低先验信心；4日准入间距，一年完成上限90 | 20bp+10次资金敏感性；更长持仓降低样本并增加资金暴露；本轮不选 |

4h最小适配不是换一个字符串：lab/binance_source.py的URL interval/capture/compile硬编码；lab/bounded_strategy.py、lab/codex_generation.py、lab/research_candidate.py的周期准入；lab/bounded_research.py的Profile/consumer步长；lab/backtest_artifact.py导入步长，至少6文件及对应合成测试，还须审database/Profile约束。风险为startup单位、48h退出根数、next-open、资金/mark映射及H绑定漏改。粗估3–6主动小时，不需新runner，但尚未逐函数穷尽，不是工时承诺。已有日线候选合成/配置约1–2小时。选择日线也基于24–48h经济尺度无需每4h抢入、48h费用摊销与样本上限有空间；并非证实日线较优。4h潜在频率收益无法由目前证据量化，且同样受早期mark缺失阻塞，不值得在probe前投资。若数据通过、监督认为更快响应值得3–6小时，可另批准4h协议替代本推荐，必须在任何行情信号前决策，不能日线失败后救援。

## 值前规则草案

ADA/USDT:USDT，UTC 1d、isolated 1x、单仓，初始1000 USDT、固定stake250、余额比例0.99。日t闭盘r=C[t]/C[t-1]-1。有效性=volume>0且过去30个已闭日 min(Low*base_volume)>=500000 USDT（只是粗流动性代理）。Q+=有效且r>=3%，Q-=有效且r<=-3%；Q为并集。E[t]=Q[t]且前两日原始Q均假。t+1 open同向入场；E.shift(2)于t+2发退出，正常t+3 open退出，48h。止损8%，ROI={}，无callback/trailing/加仓。3%是值前大冲击幅度，不能把过去3%当未来收益。预热35日；评分前事件不带仓进入。合成验证因果、双向、2日抑制、48h退出与阶段边界后冻结唯一源码，不用市场值调参数。

## 精确窗口与审计

全部UTC左闭右开，未预留。ledger只读135943bytes、123非空记录，SHA b3775aaee9bfb7a0c8821f0db1f9c8343630018611e4f5b38adcdf0d28de5c63；仅提取必要元数据。

| 阶段 | 评分区间 | 35日预热起点 | 日数 / 含预热日线 / 小时mark / 评分8h资金 |
|---|---|---|---|
| S | [2021-01-04,2022-01-03) | 2020-11-30 | 364 / 399 / 9576 / 1092 |
| D | [2022-01-03,2023-01-02) | 2021-11-29 | 364 / 399 / 9576 / 1092 |
| H/Stress | [2023-01-02,2023-07-03) | 2022-11-28 | 182 / 217 / 5208 / 546 |

S四块端点2021-01-04/04-05/07-05/10-04/2022-01-03；D为2022-01-03/04-04/07-04/10-03/2023-01-02；H三块2023-01-02/03-03/05-03/07-03。按入场归块、不重置仓位。阶段评分时间不重叠，D/H预热只单向使用前阶段末段。

ADA/DOGE旧S[2023-11-06,2024-11-04)消费；DOGE旧D[2024-11-04,2025-11-03)消费，ADA同D仅QC保护；两者H[2025-11-03,2026-05-25)未采集封存。BCH源QC[2023-07-03,2024-07-15)，工程经济暴露[2023-11-06,11-13)，Search[2023-11-13,2024-07-15)消费；D[2024-07-15,2025-07-14)QC保护，H[2025-07-14,2026-05-25)封存。全部避开；全资产UNKNOWN[2026-05-31,2026-07-31)也排除。

未发现ADA早期三窗具名占用，但BTC/ETH已探索2020–2024、LTC早期S及XRP2022来源QC存在，跨资产同历史时代有研究学习污染，外部未登记暴露UNKNOWN。不能称统计独立；H只能称本ADA行情尚未语义读取的留出。若监督的保护口径连相关资产同期也排除，本历史计划NO_GO，不能自行换币绕过。早期资金及associated mark覆盖全部UNKNOWN、高缺失风险。

## 事前自然样本和费用门

121/121/60是纯结构自然完成上限，不是自然到达率。IID敏感性模型E率p(1-p)^2，最大4/27（p=1/3）；真实冲击聚集不独立，可能远低。p=0.1/0.2/0.4/0.6时全年期望E仅在该假设下为29.5/46.6/52.4/34.9；若自然完成率50%–80%，约15–42笔，既非预测区间也非数据证据。方向失衡及短时止损另减样本。自然频率UNKNOWN，必须唯一预筛/Search证伪。

冻结S/D自然>=24、各向>=8；H/Stress>=14、各向>=4。理由是一年约每月2笔且覆盖双向，半年门类似，仍不是统计显著门。自然=持仓>=1440min、exit_signal/stop_loss；所有其他退出计损益/风险不计自然。总笔数也达门、平均持仓>=1440min、ROI退出0。各阶段价格毛利>0、保守净>=钱包1%、PF>=1.10、原生及保守小时close MTM DD<=10%、现金可执行非负、去最佳单笔后净>0。S/D至少3/4块净正，H/Stress至少2/3；每块有自然样本，最大正块占正块盈利<=60%。这些门不用于挽救旧结果。

base每边10bp=手续费假设5bp+滑点价差代理5bp，往返20bp；Stress每边20bp，往返40bp，不是账户费率。48h含边界付款至多7次资金敏感性：每次1/5bp时，base毛盈亏平衡27/55bp、Stress47/75bp。24h为24/40bp，72h30/70bp，Stress各加20bp。稳定名义本金的一阶算术，实际资金不封顶，不能叫成本上限。24笔赚钱包1%需每笔净16.67bp，48h毛需43.67/71.67bp；H14笔需净28.57bp，毛55.57/83.57bp（Stress各加20bp）。过去3%不保证能赚到这些毛收益。

保留BINANCE_ASSOCIATED_MARK_BOUNDARY_V1原timestamp/分钟映射、完整8h资金、associated mark、内部较不利现金流、边界付款计入/收款不计；不以小时mark替代缺失关联mark。实际价格毛利/费用/资金分拆，PnL当前UNKNOWN。

## 最小probe请求（现在唯一申请）

最多 **5匿名GET、10分钟、2MiB decoded、零重试/重定向**，新Git外净化根，非native。1次exchangeInfo只提取ADA身份/perpetual/USDT/onboardDate/status；4次fundingRate，symbol=ADAUSDT、limit=6，UTC区间如下，实际endTime均排他终点减1ms：

1. [2021-01-04,2021-01-05)：S左界，期望3事件。
2. [2022-01-02,2022-01-04)：S右界/D左界，期望6事件。
3. [2023-01-01,2023-01-03)：D右界/H左界，期望6事件。
4. [2023-07-02,2023-07-03)：H右界，期望3事件。

仅校身份、事件数/UTC连续/重复/分钟映射、associated mark存在且有限正值，输出布尔/时间端点/SHA，不输出或研究fundingRate/mark经济值，不取K线。资金率字段不做经济解释，D/H本次接触将明确记为边界QC，不能再叫物理未采集；OHLCV仍封存。任一缺失/错时/网络失败/超限立即停止剩余请求，经济UNKNOWN。抽样通过只说明值得继续全期QC，不是完整覆盖证明；S/D全期及H内部仍UNKNOWN。请求同时授权原lock下append这一次QC接触元数据并验证旧前缀字节不变；不授权窗口占用/业务DB/行情扫描。

## 通过probe后的有界路径（均另待授权）

- 监督确认可行后建一个精简Issue。复用Generation/批准/六表API/Console：唯一Candidate、一次真实Generation、合成因果/边界/平价费用负例后冻结；不新增runner或schema。当前日线路径支持，候选AST尚未实测。4h未接通。
- 一次S+D capture经scripts/fetch_binance_profile_data.py，范围[2020-11-30,2023-01-02)，763日线/18312小时mark、2184评分资金，S/D物理隔离，D仅机器QC。现capture硬限2000 CCXT fetch/2GiB decoded/5GiB磁盘/2小时；预计同旧800日约64fetch/5.3MB量级，但不是本次观测。无需改预算框架；如需更紧硬限先审现入口窄调整，不另造runner。完整覆盖失败即停，不拼接/重试；H暂不取。
- 唯一S总容量预筛，无PnL。如果总E<24，经现PR103 attach CLI正式入Candidate.metadata_json、PnL NULL、验API/页面，终止。该API只支持总量不足；总数足够但单边/分块不足交正式Search判，不任意扩预筛平台。
- Search单轮单次<=1h；只有全门通过才请监督放D单次<=1h；D全门后另授权H源单次<=2h、H/Stress各native1次<=1h，必须同research_run_id。正式终态实际留DB/Console，不只外部JSON，无finalist不造ResearchRun。任何门失败终止，技术调用也占预算，零native smoke/参数网格/回放/换窗救援。

预计probe主动20–40min、墙钟<=10min；通过后候选合成/配置/审阅1–2主动小时，capture/Search审计1–2小时；后续每阶段0.5–1主动小时。完整顺利路径4–7主动小时加独立审阅/计算，无历史自然等待；第一步很可能因旧mark缺失终止，不据此追加工程。

## 三份权威依据（本次已查，非本策略盈利证明）

[Liu & Tsyvinski, NBER WP24877 (2018)](https://www.nber.org/papers/w24877)：BTC/Ripple/ETH时间序列动量及注意力现象提供延续假说，不覆盖ADA或本参数。[Moskowitz/Ooi/Pedersen, JFE (2012)](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)：跨资产中期动量支持已知家族标签，不能外推48h效果。[Binance Funding History](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History)：associated mark、包含式端点、升序、limit<=1000；文档不保证早期mark实际覆盖。
