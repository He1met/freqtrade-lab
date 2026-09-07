# Issue 117：BTC/ETH 有限训练准入包

状态：`REVIEWABLE_PLAN_NOT_MARKET_READY`。基线 main `5ab45481e3dfae14ae5c5bc5933d61e356531c35`；原协议 SHA `e664b6447879a350663fa7940036a2682d3970af65f7c218c540e2e62ff28e85` 不变。本次仅控制元数据、官方文档与两个公开元数据 GET；价格/历史 funding 读取 0，新增 native 0。以下新经济语义均为待统一审查的提案，尚未替换已冻结合同。

## 1. 可登记的具体候选

Binance USDT perpetual，BTCUSDT/ETHUSDT；训练池 `[2021-01-01,2023-01-01)`，warmup `[2020-04-02,2021-01-01)`，全部 UTC。总源包 1004 日、每资产 24096 根 1h；每日信号由24根完整小时合成。274日 warmup 不计分。四折沿用12月训练/3月验证、每3月滚动。用途仅 `EXPLORATORY_TRAINING`，同日历和既往研究见闻有相关性；跨交易所不是独立验证。未来独立确认仍必须最终冻结后的新窗口。

机器可读候选与88个剩余逐job键见 [candidate contract](issue117-training-candidate.json)。BTC onboard为2019-09-08T17:55:00Z，ETH为2019-11-27T07:45:00Z。

这是当前用户授权研究范围内的候选合同；尚未向运行注册账追加、尚未授权采集。公开上市时间早于 warmup，历史完整性在授权采集前仍 UNKNOWN。注册前重新检查完整最新账本 SHA；新明确保护冲突则停止。

## 2. 精确保护范围与监督裁定

控制账快照 SHA `b395c63a777eebbb453ec73e2a71cd3c4ead194ed4a71f23ff9854720c362b15`，175物理行/173 JSON记录（两行空白），185542 bytes。逐记录身份和原字段见 [registry projection](issue117-registry-conflicts.json)，完整 SHA 为该文件权威值；表中短 SHA 仅便于定位。

|账行/记录 SHA 前缀|时间 UTC 2026-09-02|原用途/窗口|来源范围证据|原发行者/授权/explicit supersedes|
|---|---|---|---|---|
|59 / 7da0da0e6987|10:55:22|Search 2022；reserved Development 2023|master a36c2598…：OKX BTC-USDT/ETH-USDT；Development receipt 5045ccf2…：OKX spot daily|均 UNKNOWN|
|63 / ec7d7cef80a2|11:03:07|Search 2020；reserved Development 2021|master 57a2b350…：OKX BTC-USDT/ETH-USDT；Development receipt 16ec6763…：OKX spot daily|均 UNKNOWN|
|67 / a72b80abb743|11:40:30|2025 outer；UNIQUE_OUTER_VALIDATION_ONLY；禁止 exploratory|seal 9b75af36…；指定源 receipt 193d7f2d…|均 UNKNOWN|
|68 / c481c320ac30|11:52:00|training 2020–2025；NO_UNBIASED_ECONOMIC_CLAIM|protocol d050d038…直接列出相同2021/2023 receipts；spot_fee，BTC-USDT|均 UNKNOWN；不推定解除59/63|
|73 / bbe7f94e8d0f|12:25:00|2025 outer 再验证 SEALED_UNREAD|同67 seal|均 UNKNOWN|

监督任务 `01a07c6a-d535-7030-814c-7775d0f27f99` 在本次审查中明确裁定：59/63保护的是OKX spot指定源，不自动扩大为Binance perpetual同日历禁窗；原合同没写“允许其他域”本身不产生额外授权缺口。68是否解除旧OKX保护仍 UNKNOWN，本研究不依赖它，也不读取旧产物。此裁定只允许完成具体候选合同/准入PR，实际登记/采集/native仍待固定包统一审查。

已投影检查全部173记录的顶层和嵌套窗口/保护/scope元数据；未发现明确覆盖本候选 Binance BTC/ETH perpetual 的保护。2025 outer继续保留。行107明确 all-assets `[2026-05-31,2026-07-31)` 不相交。其他 SOL/XRP/LINK/DOT/BCH/DOGE/ADA/BNB 等特定资产保护不扩为全资产，但保留原记录；BTC/ETH近2026窗口、2024 spot训练亦不相交。行2引用[#30](https://github.com/He1met/freqtrade-lab/issues/30)为历史Development终态/其Holdout封存，body为指定Pilot源隔离，未提供覆盖本候选的全域日历限制；不据此读取其产物。当前GitHub按旧cohort关键词查询无结果，不能补造旧授权链接。

准入 scope 规则：先按原声明 `GLOBAL` 或明确 exchange + instrument type + pair 匹配，再做半开区间重叠（含warmup）；仅有源绑定的保护按核验的原contract/receipt解出scope，不能仅按BTC字符串推定global。无法解析但可能相交的保护保持UNKNOWN。注册用途授权与已见状态分开；旧通用 `check_registry()` 的 symbol-only 与 allowed_seen-only合同不适合作本候选的最终准入器，需窄修复后才能消费。

## 3. 真实交易规则证据及资金费边界

公开元数据实取收据见 [exchange metadata](issue117-exchange-metadata.json)，原完整响应在Git外。两个GET为exchangeInfo与fundingInfo，未调用行情/funding历史。两合约当前 TRADING/PERPETUAL，数量step/min均0.001；BTC最小notional50 USDT、ETH20 USDT，tick分别0.10/0.01；当前funding interval均8h。这些是当前规则快照，不能伪称2020–2022逐日历史规则。

[官方 REST 市场数据文档](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)区分过滤器与precision字段，funding历史提供原始fundingTime、rate和associated mark。请求start/end的包含关系不是持仓结算资格。quotePrecision=8也不是已核验的费用结算舍入规则。历史规则与结算精度仍UNKNOWN。

[官方 funding FAQ](https://www.binance.com/en/support/faq/detail/360033525031)说明资金费按仓位名义值和rate计算，时间附近可能仍被计费："There is a 15-second deviation in the actual funding fee transaction time." 它不能证明只是账户显示晚15秒，也不能给出精确资格切点。小时策略会在整点开/减/平仓，因此与funding时间重合不是罕见边缘。不得挪动fundingTime、用请求边界代替资格、或把不确定收益计入合格收益。FAQ标注可能过时；Clearing Procedures PDF未成功取得，真实结算精度不宣称已证实。

原生pin `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5` 的 `exchange.py:calculate_funding_fees` 对开仓、平仓时间双端包含，NaN转0；这不能作为真实边界/缺失处理的凭据。相邻trade段在同一事件处可能重复计费，必须按pair/event和真实有符号仓位独立重建并与原生账对账。

**唯一建议的保守模型（需再冻结）**：保留原始事件。用事件前后15秒作为模型的资格不确定区间（±15秒是保守提案，并非声称官方定义）。区间内仓位有变化时，枚举可行有符号持仓的funding现金流，取 `min(0, cashflow_candidates)`，每pair/event只记一次；无变化时按实际signed数量与associated mark计算。该模型不计不确定credit、扣最坏可行debit，结果标为保守模拟，不能标实际账户结算。原生与模型差额逐事件显式入账，不重复扣原生金额。缺rate/associated mark/仓位连续性直接BLOCKED，绝不零填。整点末端平仓需事件覆盖与同样边界处理。

结算精度目前仍是启动阻塞：先取得官方精度/舍入规则再冻结消费者。不能自行从quotePrecision推导8位，也不能以任意小额容差豁免0净收益门。若官方资料仍不能证实，统一审查需明确是否接受带可证明误差上界的保守研究模型；本包不默认授权该替代。

## 4. 成本、风险与最小消费者修复

基础每边fee/slippage各0.0006；压力各0.0012，实际signed funding不简单乘2。fee高于冻结值时先再冻结再评分。当前合成消费者手续费固定基础值，shadow slippage也走默认值，尚未证明压力成本同时到达订单、权益、风险与结果。

建议新增下单成本预留，不追认历史超限：每次新增名义额deltaN先从当前净权益扣预计fee+slippage，再以净额检查总80%/单资产40%和现金余额，数量只向下量化。从空仓且合计满额时上界 `N <= 0.8*E/(1+0.8*c)`，c为单边fee+slippage；已有仓位时按真实增减delta和成本逐腿重算。价格跳变仍可能造成控制前超限；必须同时报告控制前和执行后暴露，继续保留continuous compliance失败，不把触发减仓本身视为从未超限。20%净权益回撤门不变，旧synthetic/6与/7失败不豁免。

|可复用工程|最小缺口与完成判据|
|---|---|
|因果日信号、净权益核算、V2减仓/暂停状态机|绑定市场源的离线入口；拒绝synthetic固定输入与不完整源；全wrapper纳入启动前manifest|
|pure core A-trend/A-reversal/B/C/halfB|原生策略initial_state/make_decision当前固定B；用冻结job配置传mode/参数，逐mode测真实决策输入|
|协议fold选择规则|训练筛选、central/ascending tie、无合格family现金；validation不参与；最终按唯一UTC日均值后计一次、逐fold风险门|
|job plan列有market-exposure|因果benchmark消费者/具体调仓定义尚缺；需监督冻结定义，不凭名称编造行为|
|基础成本合成对账|base/stress由同一job配置传至所有消费者；真实funding事件账和结算精度未完成|
|96槽合成预算防重放|当前reserve只允许synthetic/retry；市场逐job键/阶段依赖/输入+代码+源绑定、失败消耗、只同输入技术retry需接入|

此Issue交付准入设计和证据，不为了绿灯重复合成。不新增表/服务/UI。后续先在同一窄执行路径补齐以上纯工程，针对mode、stress、边界、失败零native、fold泄漏与预算异常测试；再对固定SHA统一审查启动。

## 5. 有限采集合同提案

单一新Git外根，预先绑定候选/审批/代码/源契约SHA；不复用旧受保护源。仅两个symbol、三个端点：`/fapi/v1/klines` (1h)、`/fapi/v1/markPriceKlines` (1h)、`/fapi/v1/fundingRate`。范围严格为上述1004日。每页写原响应SHA、请求参数、HTTP状态、获取UTC、字节数；endTime=半开终点毫秒-1，按最后返回timestamp+1推进并检查进展、重复及越界。

上限122个GET：trade34页+mark34页（每symbol每类ceil(24096/1500)=17）、funding最多50页+2次有界末尾确认（按最密1h、每页1000预算）+公开元数据刷新2次。比1h更密或边界额外需求不自动扩大预算。单worker，最多1请求/秒，每请求20秒，整次30分钟，解码后总64MiB/单响应5MiB；不自动重试，429/418立即停并保留Retry-After、失败收据与未发布临时包。不得把不完整源标策略失败。这里只是采集计划，未执行。

QC必须核对24096 trade及mark小时/资产、UTC唯一升序无缺口/无越界、OHLC合法、完整日聚合、warmup和计分物理视图、funding原时间/有限signed rate/正associated mark/原事件唯一。当前8h不能证明历史固定8h；需要官方历史调整证据覆盖事件间隔，缺失/异常不插零、不强行对齐整点。历史接口可获得性与完整性只能由获准后的实取QC证实；上市时间只是必要条件。首/末事件资格覆盖不足直接BLOCKED_DATA。原始源不入Git；只允许审查过的sanitized receipt/fixture。

## 6. 预算和首次训练启动门

calls.jsonl快照 SHA `a828469373802b7296a19d15bb79735d3adf30ca31c7201e4ff881b59e969e18`；已消耗8槽（7 synthetic + retry/1），其中7次实际原生。剩余88：synthetic/8一槽（尚无绑定/授权）、retry/2–4三槽、training24、validation base24/stress24、final diagnostic base6/stress6。总96不变；84个市场job当前均未授权，不能挪用合成或重试槽。

最早启动顺序：固定包审查 → 精确scope登记与有限采集授权 → 新根采集/QC → 最小消费者完成且精度/资金费/风险提案冻结 → 固定代码/输入/源/全部wrapper manifest复核 → 逐job预留后首次训练。第一批仅24训练job，validation/diagnostic依赖冻结训练选择结果及其授权，不提前评分。任何行情合格结论、native预算允许和阶段授权三者不能互相替代。

当前终态是可登记候选与修复计划待统一审查；主要阻塞为真实结算精度、待批准经济模型、市场消费者与注册/采集尚未实施。不是无训练池，也不是合格策略或交易许可。官方UI没有本研究的市场结果可展示。
