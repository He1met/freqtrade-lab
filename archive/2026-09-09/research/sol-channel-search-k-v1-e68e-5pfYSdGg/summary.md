# SOL prior-close channel：两轮结束，无合格候选

**SEARCH_TERMINATED_NO_FINALIST；累计2/2次native Search已完成且技术有效。R1小幅正收益但样本、净收益、PF不达门；R2零交易，盘整增量未获支持。** 不进入D，不扩窗、降门、改为spot或追加回测。只结束本cohort，不代表整体寻找合格策略的目标完成。

SOL/USDT:USDT，OKX isolated futures，1d双向1x，wallet2000/stake400/max_open_trades1。S=[20240301,20250301)；D=[20250301,20260301)仅QC物化、研究者未读；H/Stress=[20260301,20260831)值与评价SEALED_UNREAD。pre-roll29仅因果warmup。项目0ace04b7c10ea35fb8ce6f25e043ac78be87c19e，native2026.7/52bc96f4480b1a0da6a9b455bd00b17fbb6786a5，未修改业务/native/runner/producer代码。

| 指标 | R1通道基线 | R2此前28close区间≤1.10 |
|---|---:|---:|
| 真实native closed trades | 15 | 0 |
| 价格毛收益 USDT | 65.33750000 | 0 |
| 交易费扣减 | 6.04893805 | 0 |
| signed funding | -36.26800794 | 0 |
| native净收益 | 23.02055401 | 0 |
| 每腿额外2bps扣减 | 2.41957522 | 0 |
| 额外成本后净收益 | 20.60097879 | 0 |
| native钱包收益率 | 1.15102770% | 0% |
| extra钱包收益率 | 1.03004894% | 0% |
| native PF | 1.0991603924 | 0（原生投影） |
| native DD | 8.53793995% | 0% |
| extra PF / realized DD | 1.08812859 / 8.60328558% | NULL / 0% |
| 平均持仓分钟；范围 | 21600；0–47520 | NULL |
| 多 / 空 | 8 / 7 | 0 / 0 |
| stop / signal / force / ROI退出 | 5 / 9 / 1 / 0 | 0 / 0 / 0 / 0 |
| 价格毛额 / entry notionals | 0.010904364745 | NULL |

R1的15<24笔、native23.02<25、extra20.60<25、PF1.09916<1.10，独立各项均不通过；不因接近阈值作四舍五入放行。资金费吞噬了36.27USDT价格毛收益。R2没有成交，holding和毛额/notional分母为零时均保留NULL；其native0/PF0/DD0来自真实零交易输出，不代表足够样本或低风险。R2自身门失败，三项严格优于R1的增量条件也均不成立。规范terminal与完整补充经济资格一致，无winner替换。

值前冻结的分析脚本原样执行成功：对15笔原生交易核查上一根已关闭日线信号→下一根open入场、1x、真实导出订单notional、basefee、逐事件mark×funding×signed quantity与native funding一致，并逐笔核对price−fee+funding=net；两份ZIP内源码SHA也与冻结源一致。此处是原生历史模拟fill，不是真实成交证明；日线不能证明盘中精确触发时间或真实滑点。native duration0保留为同日模型时间粒度，未强制持仓。唯一末笔force_exit为2025Feb17–Feb28标签的空单，净106.30645593，占全部正收益单41.66%，大于整批23.02净额，结果依赖少数大盈利，不移除或另算通过。原生末端bar时间标签与close可得时间需保持区分；被动归因按首S open至末S close计量。

S内、下一日open仍在S的日线入场信号机会：R1 long47/short27，R2 long0/short0。R2零成交与零合法入场机会一致，不伪造逐笔配对；持仓占用一般会破坏R1/R2成交子集关系。

R1按close月的native净额（USDT）：2024Mar -35.0184，Apr +62.7873，May -13.5612，Jun +7.7481，Jul -50.6789，Aug -51.5221，Sep -31.8852，Oct -33.2304，Nov +4.6151，Dec +73.7184，2025Jan -3.9887，Feb +94.0366。季度closed counts为2024Q1/Q2/Q3/Q4/2025Q1：1/3/5/3/3。R2各月/季无交易。完整逐笔和月度cost拆分见result-audit.json；coverage与平均15日只报告，不作新增hard gate。

必报归因对照（非额外策略回测/门）：cash0；初始400notional被动多native成本语义净6.91342519、extra6.73908695；被动空-7.78511639、extra-7.95945463。R1平均signed quantity0.28227397对应被动净0.61300865、extra0.59755020；R2平均quantity0对应0。按冻结的native持仓分钟计算平均敞口，受日线模型时间分辨率限制。对照不改变任何资格判定。

## 数据与封存证据

首次官方producer main于03:12:00.803–03:12:34.648Z成功，无重采集：759日线/18216小时mark/2190个8h funding；223请求，25个月包GET、5个catalog组。S和D官方consumer各394/9456/1095，完整source binding/UTC连续唯一/正有限OHLC/依赖版本和严格0..2000ms选中funding网格按原代码通过。

物理层：S+D源已获取，必要March2026边界ZIP/CSV opaque字节在内存获取并hashed，**raw retained=false**，不可声称从未获取H相关原始字节。QC层：官方producer/consumer只对选中S+D数据确定性验证与物化。研究者语义层：只读取S孤立切片/结果；D价格/费率/信号/统计/结果未读。评价层：仅S两次，D/H/Stress/Judge/Release均0。

March2026包93记录，selected1（D最后Feb28T16Z网格、drift0），uninterpreted92，uninterpreted validation=NOT_PERFORMED。原selector先检查raw和normalized半开区间再访问rate。原safe receipt未暴露完整raw timestamp envelope，因此其范围UNKNOWN；未自写selector或为补证重取raw。H费率finiteness UNKNOWN，H蜡烛/mark未取。producer兼容字段development_start_utc映射本次Search起点、holdout_start_utc映射本次Development起点，不能误认为真H被读取。其他原sealed windows完整保留，外部未登记消费仍UNKNOWN。

## 真实Generation、行政恢复和数据库

原实例因我填写大写strategy_family产生HTTP409 invalid_seed_set；发生在Search plan/native之前。原真实Generation ea832723-5c6c-4c6f-abb1-feb71053d614与Candidate22c852c0-d0e3-4a68-877c-aed934155100保持原样。监督授权仅一次ADMINISTRATIVE_RECOVERY_BEFORE_SEARCH：同Issue76、同cohort，用新六表DB仅改family为sol_prior_close_channel_consolidation_v1。Profile snapshot、window/source/gates/analysis和双源完全不改；复用已有consumer、无下载。旧DB SHA d995c11dc30578c71e3c8c887e3097749d25b066fca40d88d01860fd156eba64复核未变，原native0不隐藏。

恢复实例admin-recovery-Kaiq8nmX/research.sqlite：Profile1、generation_runs3（CODEX2+官方Search terminal MANUAL1）、Candidate2，ResearchRun/Execution/Release均0。旧DB六表counts1/1/1/0/0/0。合计真实CODEX Generation3次（含行政旧实例），均输出逐字匹配源；经济native严格2次。

- R1 Generation d74c5e7a-fc0d-489a-916f-6729707586e5；Candidate76a0cfd8-ac20-4e6d-8590-bda1e41b5a31。
- R2 Generation826229ec-784c-4901-b230-7c23038df703；Candidate2a2ef369-d392-4e2d-b700-f406b18648d1。
- Search campaign1e46d311-e03a-437b-98b9-20654962dd5d。

实际Console http://127.0.0.1:52920/console 与API/DB/terminal对齐，Round1/2已禁用；FreqUI实测UNAVAILABLE。UI仍把技术READY候选显示在Development下并使按钮可点，这是展示边界缺口；未点击/POST D。只读代码确认服务器create_research_run检查持久finalist，未发起执行型验证。本报告不把READY按钮或MANUAL COMPLETED投影称为盈利、资格或D授权。

## 交付定位

root=/Users/shenjianpeng/.codex/runs/freqtrade-lab/sol-channel-search-k-v1-e68e-5pfYSdGg。
执行DB=root/admin-recovery-Kaiq8nmX/research.sqlite；原DB=root/research.sqlite。分析result-audit.json；metadata=data-metadata-audit.json；DB/API=database-api-reconciliation.json；UI=ui-check.json；恢复关系=admin-recovery-Kaiq8nmX/administrative-recovery-before.json及administrative-recovery-initialized.json。全部在Git外，未提交业务代码或PR。

freeze-manifest SHA d2e80a40cabc705b1d083aa4e18781eeaa44d27e7465725d7f38eb04d41ba169；source receipt66f88a465c9fc37cd6af62c80320c8656d4909cedd0c2ffb06ba0af0a4141329，source provenancefc1a667a2ede3ce4f4a1823ffba5f85ebb7eae2f92caf86c2a116ad88b2c296f。
R1 ZIP4c23adb22bcb8bee048ac5e2b8061e9d76193375e81f781ee6c24d6d430525f9；R2 ZIPb2f7c0b99cd5c1e4901430b638284a05996f0806000195f919eb5b7b0f360116。
terminal68b1ac6d407750d72592b844c62fad209b7d672bb91d132d8fbae4abf8f923af；trialsccb3a324e2d7b6763250d609ab797f85c00a3b34f84e0b4982f12a39dd47187a。

定向现有测试12passed/6skipped；真实producer/两consumer/三次Generation/两次native、原样冻结analysis与DB/API核查均有实际记录。测试结果不替代经济门。模型gpt-6-astra；内部effort/tier UNKNOWN，未改全局设置。Issue76保持OPEN，交监督独立复核，未获关闭许可。不存在合格finalist，后继阶段继续封存。
