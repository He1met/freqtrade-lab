# DOGE_BIDIRECTIONAL_SMA_10_30_V1 终态

**DEVELOPMENT_REJECTED；退役当前简单双均线路线。** 本轮真实执行 2 次 Search、仅 finalist R2 的 1 次 Development。两次 Search 全门槛通过，独立 Dev 净收益不足 1.25%、PF 不足 1.10。没有合格策略，不做第三次 Search、R1 Dev 或换币/换窗。

|阶段|笔数|净收益 %|PF|DD %|平均真实持仓 分钟|ROI退出|判定|
|---|---:|---:|---:|---:|---:|---:|---|
|Search R1|17|23.48702228|3.27697777|7.17091153|30578.82352941|0|PASS|
|Search R2|21|24.06991408|3.58995359|6.21539139|24480.00000000|0|PASS|
|Dev R2|22|0.72969889|1.06643142|6.11182705|23170.90909091|0|REJECTED|

Dev 唯二失败：`MINIMUM_PROFIT_FACTOR_NOT_MET`、`MINIMUM_NET_PROFIT_AFTER_BASE_FEES_PCT_NOT_MET`。交易数、净正收益、DD≤15%、平均持仓≥10080分钟和ROI退出0通过；未四舍五入放行。3 次原生执行均技术成功。

|阶段|多头笔数 / 净损益 USDT|空头笔数 / 净损益 USDT|手续费 USDT|资金费净收付 USDT|总净损益 USDT|
|---|---:|---:|---:|---:|---:|
|Search R1|8 / 244.69857571|9 / -9.82835296|1.82749175|-23.19278548|234.87022275|
|Search R2|11 / 244.84830294|10 / -4.14916215|2.22278100|-23.18787821|240.69914079|
|Dev R2|11 / -35.08090018|11 / 42.37788906|2.14495160|-1.13445952|7.29698888|

手续费为配置的每边0.0005，1x；资金费负数表示净支付。逐笔核对 `方向价格损益 − 手续费 + signed funding = 净损益`，多空和总和与ZIP/API相同。Dev 多头 funding −2.84998889、空头 +1.71552937 USDT。方向贡献仅描述实际组合，未回测剔除亏损方向，不能证明双向修复 BCH 或优于 BCH。Dev 退出：12 exit_signal、9 stop_loss、1 force_exit。slippage UNKNOWN；exact-grid 不证明逐秒真实结算。

数据：25月2193 funding events全PASS，offset0；首月86、末月1。正式未修改producer重取同源一次，25 ZIP及CSV SHA均与预检一致。完整source rows851/20424/2193；Search486/11664/1098；Dev485/11640/1095（futures/mark/funding）。UTC连续、范围、source provenance及现有producer/consumer隔离验证通过；mark volume按原生语义保留NULL。消费检查复用87条元数据索引+11条新增canonical记录，所有timeframe及原始范围无DOGE冲突；覆盖外部UNKNOWN。后续已消费本轮Search/Dev，不可重放。

持久化与页面：原六表 counts `research_profiles=1,generation_runs=3,candidates=2,research_runs=1,backtest_executions=1,releases=0`。generation为2个CODEX + 1个MANUAL Search终态；投影、finalist绑定、foreign keys、策略AST/hash、API/三ZIP/逐笔持仓资金费全部对账。live Console同campaign显示SEARCH_FINALIST_FROZEN、同run Dev SUCCEEDED/REJECTED，H/Stress各0且SEALED_UNREAD，Release0。FreqUI UNAVAILABLE。通用UI仍显示非finalist R1 READY及R2 ALREADY_PENDING标签，不构成允许R1 Dev或未完成证据；以规范化终态为准，未点按钮。

- Profile: `doge-bidirectional-sma-10-30-v1`
- Campaign / MANUAL generation: `01dc3151-e7d3-46a9-a6ae-9cbb28f6bcae`
- DogeBidirectionalSmaR1: generation `2eb33eed-8573-46a8-8de4-265113e195be`; Candidate `5ddc038a-4882-40f5-a995-4a0f196fda8b`
- DogeBidirectionalSmaR2: generation `d8296e85-34be-435d-bc84-088c2a8fc1b1`; Candidate `62f1dbb1-f332-4f6d-8bbc-a821ba8d8160`
- 唯一 finalist: `62f1dbb1-f332-4f6d-8bbc-a821ba8d8160`
- ResearchRun: `32998e0a-65ad-4f2f-aa94-e43cee6af640`; Development execution: `b814574f-bbaa-4c20-94c3-058786f490ed`

代码/数据/产物 SHA-256：

|对象|SHA-256|
|---|---|
|Lab HEAD / live main|dc82c61fe8a27a654977344755c088412518d858|
|Freqtrade 2026.7 commit|52bc96f4480b1a0da6a9b455bd00b17fbb6786a5|
|R1 actual code|900b7e0f7be73235153d446bf525cb86480fd3f81088a8430a195a5d719ae97c|
|R2 actual code|5f46bc934f219a34bb201ffe0e980c1f8c3154356d74f4efc2885536caff664a|
|source provenance|947f6c35c8aefca8f31b45ebc0e078fa36e44487c8c7607060a35297fbcd6d09|
|source receipt|20629026d11c65b19ea4ff43f38f5763a8ba5b9849db573475dea3adbbb09d3f|
|R1 Search ZIP|16427a22880e2de5abbc4ec7e428b90ab8a200ee9b1afc6da952501d2cc97aa2|
|R2 Search ZIP|d3939a09f9dc1428dd06b759075a5ec42a24459a364047d79cb53f11cbaed501|
|R2 Dev ZIP|a3c8ab8773fa3ef6c631d90a6208f64f0efd38dd00d12cadc7a7aa5a14dc12eb|
|Search terminal|244f8b71fec591a5602f9aa638e3a13c998bbee062d1196bf1c944360ab60dbe|
|Search trials|ba2336352fd2196450c10c461e5cb2dd84bc3c9253f770b481bbe2203fb9fb2e|

Git commit IDs上表为SHA-1，其余为SHA-256。9个数据文件SHA见 `data-grid-audit.json`；月档SHA见 `source-verification.json`。全部产物留外置root，无业务代码/schema变更、无人工commit/PR，工作区干净且main实时一致。

预注册程序偏差：GitHub #65 created_at=updated_at 2026-09-04T21:11:47Z，完整契约已在首归档21:12:14.965731Z前公开冻结；本地文件mtime21:11:46Z，回读21:12:12Z。初次manifest命令因Python3.9 `datetime.UTC`失败，编排未中断，SHA清单到21:12:24.961837Z才补记，**不是事前哈希**。监督独立核对接受既有远端预注册锚点，保留原文/文件/原SHA，不重跑；详见[例外记录](https://github.com/He1met/freqtrade-lab/issues/65#issuecomment-5546527109)。技术兼容勘误仅补入现有强制未用imports ta/qtpylib，原冻结class主体AST保持完全相同，R2仅class/stoploss改变，通过项目单因子verifier。没有参数/信号/窗口/Gate后见更改。

本假设来源为 [Moskowitz/Ooi/Pedersen](https://pages.stern.nyu.edu/~lpederse/papers/TimeSeriesMomentum.pdf) 的传统期货自身过去收益方向、多空与波动率缩放，不能验证DOGE/10-30/固定仓位，本轮非论文复现。[Liu/Tsyvinski官方摘要](https://academic.oup.com/rfs/article-abstract/34/6/2689/5912024)本次直连不可用，仅保留原先给定的广义动量动机。[Freqtrade官方](https://www.freqtrade.io/en/stable/leverage/)与本地原生代码确认short/默认1x/信号shift1能力。

跨币同日历窗口相关，不能称统计独立重复。已知LTC/BCH/DOGE路线至少6次Search、本轮唯一Dev；更早累计研究未穷尽，保留多重选择风险。按冻结最后扩展规则退役简单双均线，由监督另选不同机制。实际服务档位UNKNOWN；监督已核验本执行gpt-6-astra/high，未改全局配置。

Issue #65 保持OPEN等待监督验收。产物root：`/Users/shenjianpeng/.codex/runs/freqtrade-lab/doge-bidirectional-sma-10-30-v1/cohort-v1.OTBhEVwa`。核心证据 `final-audit.json`、`data-grid-audit.json`、`page-observation.json`。
