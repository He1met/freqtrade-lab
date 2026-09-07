# Issue 121：153日固定参数可行性修订

结论：`PREPARED_NOT_ACTIVATED`。本包是旧源BLOCKED_DATA后的新版本；不是旧24月四折的执行或补成绩。原协议、原37GET/7697705bytes、历史失败和封存保留。当前0新登记、0新GET、0native。

## 唯一时间与用途

[机器合同](protocols/issue121-short-feasibility-v2.json)：Binance BTC/ETH USDT perpetual源 `[2023-11-01,2025-01-01)`；274日warmup截至2024-08-01，随后153日。探索 `[2024-08-01,2024-11-01)` 92日；预留流程检查 `[2024-11-01,2025-01-01)` 61日。后片不能调参数、选择C或称独立确认。只用central trend63/reversal2；无超参数扫描，无market-exposure（定义未冻结）。五mode为A-trend/A-reversal/B/C/half-risk-B，各保留base/stress。

[scope快照](issue121-scope-snapshot.json)绑定当前186369字节全账SHA d596e9ce1f15c9271b8815e9e557187e97af3b240befb43f8e0e87250d34f5ee及174记录；原59/63是OKX spot指定源，2025 outer保持global保守保护，source end严格exclusive，2025事件不可取。唯一新增行176是旧2020–2023探索登记，未覆盖本段。其他明确资产/全局保护仍按原精确scope；任何账本变化先阻塞复核。2024与既往spot等研究见闻相关，本段只有探索意义。

结论仅可行性、机制负面或UNDERPOWERED；净成本/风险/自然簇证据必须分别报告。20%最大回撤、每family至少30自然簇和未来独立确认要求不降。样本不足就UNDERPOWERED，现金/0样本不合格；即使全部探索表现正也无晋级、无PASSED/交易结论。本段不是缩短持有期的理由。

## 有界源续接：先缺口后大文件

先exchangeInfo/fundingInfo，再BTC完整funding与ETH完整funding；全部原始associated mark存在、时序字段结构有效后才下载两币trade/mark 1h。任何字段缺失立即停止，不轮流探测其他窗口。不取2025边界事件；funding尾页确认仍限定endTime=2025-01-01毫秒-1。

427日=10248小时/资产。trade和mark各ceil(10248/1500)=7页，合计28GET。按8h预估funding每币1281事件、2页+1尾页，合计6GET，加元数据2：预计36GET。按每小时最密预留每币11页+1尾页，共24，加28+2=54GET；更密或多页不扩大预算。新旧合计最多91/122GET。

同一全局budget目录使用唯一`acquisition-continuation-v2.json`，导入旧37attempt逐字段原样、旧7697705bytes；旧parent文件/SHA不改，parent漂移即拒绝。新源只允许旧root内`continuation-v2`子段，不能换root重置。全局剩余85GET/59411159bytes，下一段额外上限54GET；失败保留整响应5MiB预留、单5MiB、总64MiB、无retry、单worker/1秒/20秒仍沿用。

旧程序没有durable终态elapsed字段。为不低估累计30分钟消耗，本提案使用旧capture开始至144eb608终态收据提交时间的上界，向上计130秒（包含HTTP后的工作），剩余1670秒；不只扣36.696695秒最后HTTP时间。该保守记账随整包裁定。未来续接持久保存`parent_seconds_charged`与新开始时间，等待审查时间不算活跃采集。无具体activation授权，ContinuationBudget拒绝构造；当前准备不会写它。原“无自动恢复”仍有效，只有后续具体批准的v2才能启动。

历史funding间隔证据仍UNKNOWN。新字段上线日期不证明全事件完整；仅观测8h间隔不能当官方全历史日历。缺证据维持BLOCKED_DATA不发布source-ready。精度/舍入规则UNKNOWN也不准称实际结算；不零填、不用小时mark替代关联mark、不实现区间代填。

## 消费者实际变化与边界

新`lab/portfolio_short.py`提供可直接复用的纯消费者，原合成文件不修改：

- `configuration/decision`把五mode、central63/2送入已有真实因果daily core，拒绝参数漂移；同一配置给出native fee及账本fee/slippage，base各0.0006/stress各0.0012。
- `account`复用真实订单净权益计算，明确传成本和逐事件funding；未来事件不读价格/rate/quantity。到期但available_at或eligibility_resolved_at未到，阻塞风险决策；已到且资格/关联mark未证明也阻塞。事件只计一次、按-q*r*m记现金，支持正负rate和仓位。没有原生funding再加一次的问题：该入口接收单一外部事件账，未来原生对账必须显式替换/调差。
- 此处资格/来源认证输入是待上游验证合同，布尔标签本身不是证据；本次没有发明资格切点或“15秒后必然已结算”。在整点成交与funding重合而无法证明资格时会阻塞，不擅自记收益。未来风险调用必须使用该净权益；不能让原生wallet未调funding的值绕过该入口。
- `reserve_additions`只处理同向加仓：按新增notional的fee+slippage扣权益，用向下lot量化后重新检验单资产40%/合计80%。已有超限直接禁止加仓；减仓/反转仍由原V2实际执行路径完成，min_qty/notional/max_qty还要由原订单规则检查。不豁免旧超限或20%失败。
- `ContinuationBudget`是固定单v2累计预算消费者，锁与parent SHA复核防重复激活，继承真实reserve-before-GET/失败保留规则；当前未构造实际runtime实例。

市场原生适配器尚未绑定此新源和事件认证输入；pure模式/成本测试不代表native运行已验证。源间隔、结算精度/资格仍是市场评分前的真实阻塞。当前不创建假可执行源或虚假的native启动清单。

## 20个新job与原总预算映射

原已用8槽，剩88。提出取原24个未用training槽中的前20个，一一**在批准激活后**retire并映射至新命名`BTC_ETH_SHORT_FEASIBILITY_V2/...`（机器合同列完整旧键/新键）。不是用旧键执行不同日期。新5mode×2cost×2时间片=20；先探索10，后流程检查10预留、不自动开启。剩余68（原余下64市场键和4备用槽）不激活，总8+20+68=96。没有新增native retry预算、没有按结果救援。该映射是审批提案，旧native账未改，下一真实reserve须绑定获准映射/输入/代码/源/阶段。

## 实际准备入口与验证

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/prepare_portfolio_short.py
PYTHONDONTWRITEBYTECODE=1 uv run --with pytest python -m pytest -q -p no:cacheprovider tests/test_portfolio_short.py tests/test_portfolio_source.py
```

prepare只读当前scope/parent预算，输出每个mode成本配置、85GET等总余量、新54GET上限和20个job；不登记、不开预算续接、不GET/native。27项测试通过，覆盖真实daily core mode传递、stress净权益差异、未来值不泄漏/到期未决阻塞、资金费方向/去重、扣费后量化caps、旧预算前缀/请求38/时间保守扣减/禁止重置，以及已有producer安全测试。旧失败包不重跑。

整包交监督一次裁定短阶段及续接预算。可先裁定上述确定源采集；native仍必须在源QC和市场适配器/资金费资格/精度证据满足后固定真实启动身份。后片流程检查和未来独立确认不因工程合并自动授权。
