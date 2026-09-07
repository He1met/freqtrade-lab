# Issue #111 原生合成执行验收收据

验收日期2026-09-08（Asia/Shanghai），实际调用UTC 2026-09-07约16:05–16:12。
状态：`RUNNABLE_WITH_LIMITS`，**共享资金目标执行内核的技术证明**。
完整经济信号模板、数据来源/计费资格、市场训练、独立确认、实盘均未完成。
原生数据是代码生成的合成向量，没有市场报价/资金费请求，没有旧保护窗值。

## 实际调用与不可变失败历史

| 槽 | 当时执行源码 | 原生构造/回测 | 包装终态与后续 |
| --- | --- | --- | --- |
| synthetic/1 B-risk | 26cf104 | 0 / 0 | FAILED：单pair配置复用函数拒绝两pair；占槽不回收 |
| retry/1 B-risk | 8c037bb | 1 / 1 | 原生成功，包装序列化Timedelta失败；原FAILED保留 |
| retry/1后处理 | ab0cf6a | 新增0 / 0 | 读取原ZIP恢复审计PASS，追加AUDIT_RECOVERED，不重放 |
| synthetic/2 A-trend | eb5bdf0 | 1 / 1 | SUCCEEDED，实际两币独立A-trend钱包 |
| synthetic/3 A-reversal | eb5bdf0 | 1 / 1 | SUCCEEDED，实际两币独立A-reversal钱包 |
| synthetic/4 B | eb5bdf0 | 1 / 1 | SUCCEEDED，实际两家族目标净额共用两币钱包 |
| synthetic/5 C | eb5bdf0 | 1 / 1 | SUCCEEDED，实际降风险目标/position adjustment |

总计**6个消耗槽、5次真实Backtesting、1次零调用后处理恢复**。
未用synthetic/6–8及retry/2–4；总96预算已用6，剩余90不等于本阶段获准市场执行。
没有凑满8、没有隐含重试、没有改固定向量。网络hook每次阻断一次socket.bind，
没有放行connect/getaddrinfo/交易所请求；不声称底层库没有尝试任何socket操作。
首个恢复前风险报告的socket尝试列表未单独保留，不能补造为0。

官方源码commit `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`、干净工作树；
Python3.13.13 / Freqtrade2026.7 / ccxt4.5.68 / pandas3.0.3 / pyarrow25.0.0。
每个实际调用的input SHA及源码逐文件SHA在
[脱敏合成摘要](issue111-synthetic-summary.json)中，不用当前源码覆盖旧调用身份。
固定合成向量`SYNTHETIC_VECTOR`规范JSON+mode绑定input hash，重试保持相同输入/native tree。

## 技术断言与风险结果分开

下表金额都是**合成验证单位**，不是市场收益或经济样本。

| 模式 | trades / orders | 实际订单fee | native/source funding | 最终原生权益 |
| --- | --- | ---: | ---: | ---: |
| B-risk | 2 / 11 | 0.95988000 | −0.3588745 | 998.6812455 |
| A-trend | 3 / 7 | 0.960000 | −0.27 | 998.77 |
| A-reversal | 5 / 10 | 0.720000 | +0.06 | 999.34 |
| B | 3 / 9 | 1.43916000 | −0.29001 | 998.27083 |
| C | 3 / 8 | 0.576000 | −0.089 | 999.335 |

每个账户只有一个策略和共享wallet，同时实际持有过BTC/ETH。A两个家族各跑自己的钱包，
B/C各一个独立钱包，未把多个策略的净值相加。B/C在相反BTC目标日没有BTC成交；
多空翻向在实际平仓后至少一小时，低于最小额日无成交。原生实际订单手续费、
逐持仓段funding、最终平仓库存及最终权益独立对账通过。
所有调用的结果和未通过情况完整保留；C的合成费用更少不表示存在动态经济增量。

### B-risk明确突破20%风险目标

控制行为断言PASS，**风险限额达标=false**。最大观察DD **22.19316445%**，
小时mark最低权益 **778.0683555**。不能写为“满足20%回撤要求”。

| 首次穿越 | 所用上一完整mark小时 | mark可得/控制决策 | 最早可执行 | 该时权益 |
| --- | --- | --- | --- | ---: |
| 10% | 2020-01-03 12:00–13:00 UTC | 13:00 UTC | 13:00 UTC小时开盘 | 778.0683555 |
| 15% | 同上 | 同上，停止新增/目标清零 | 同上 | 778.0683555 |
| 20% | 同上 | 同上，保持停止 | 同上 | 778.0683555 |

两币实际退出均为2020-01-03 **13:00 UTC**，退出原因`portfolio_target_close`；
实际开仓是2020-01-02 01:00 UTC。冲击在同一已闭合小时一次跨过全部阈值，
不是15%提前退出可以保证不越20%。没有修改向量/阈值或丢弃这段风险路径来通过。

本探针故意让OHLCV固定100/50而mark骤降至70%，因此原生按固定成交价格退出后权益
回到约999，不是现实清算/滑点/极端流动性证明。保证金清算、真实可成交成本与盘中连续DD均UNKNOWN。
这里证明的是控制器看得到未实现损益并及时发出停止，而不是实盘能以同价格无损逃离冲击。

## 预算、恢复和真实入口

唯一预算根由全局固定anchor绑定，无法传入新budget/output目录。
anchor SHA `7aaba6a65e372275d3a65a2fbaaf79abdd3a9597ae98eba62e5344edf3af79e9`。
原全局182823字节SHA b04a689820be336826c255ee9835b0b1db4c2fcd31bbf8f8a897c5aed9b5f90c完整保留；
追加anchor和checkpoint后183727字节，SHA
`89c063daaefc763b9bf7ed2b8a4b9dac7e1190ece53585baca5bd310e0a77ecc`。
预算账13条事件、5994字节，SHA
`986f164d19be4d4188ef59d8a052102f3a9c479469c8a7bc1703d214c1c97d7a`。
后续允许追加；旧prefix必须一致，不要求全局永远保持末尾SHA。

已完成调用后增加防恢复漂移检查：当前合成向量hash必须与失败预约相同；
全局checkpoint阻止预算文件丢失/截断/改写后重新建零账；预约及终态自动checkpoint。
这些恢复/准入修复未再次调用原生。原始失败`evidence.json`、ZIP和trace均未覆盖，
恢复写独立`audit-evidence.json`，原调用仍消耗，成功恢复后禁止原生retry。

真实入口示例见[执行说明](portfolio-native-synthetic-v1.md)。首次5模式均实际执行。
同一B命令重复调用已验证退出2、`BLOCKED_BEFORE_NATIVE`，原因旧输出已存在，
预算仍为上述5994字节及同SHA；没有为了展示幂等而再启动原生。
budget pending表示中断/UNKNOWN且占槽，后续调用拒绝；不会擅自清锁、回收或重放。

## 测试、工件和剩余门

首次非原生51项通过；单pair配置修复52项，恢复保护53项，checkpoint54项，
风险语义最终55项通过（0.22s）。原生五组验证全部来自原生Backtesting及immutable ZIP，
单测不替代这些证据。随后新模块+相邻旧SingleBaseline完整固定依赖回归
**69 passed**（9.32s），12项既有pyarrow弃用警告：

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --with pytest --with freqtrade==2026.7 \
  --with ccxt==4.5.68 --with pandas==3.0.3 --with pyarrow==25.0.0 \
  python -m pytest -q -p no:cacheprovider tests/test_portfolio_budget.py \
  tests/test_portfolio_execution.py tests/test_portfolio_preflight.py tests/test_single_baseline.py
```

无六表/字段/索引修改、无服务或生产部署、无市场数据fixture；全量E2E/市场测试不触发。

可公开摘要数据字典：`native_profit_synthetic_only`是原生实际合成订单净额；
`fees/funding/source_funding`为成本对账；`risk_observation`明确回撤达标布尔值、穿越时序；
`archive/evidence/trace/input/code`的SHA绑定原始外部产物。
摘要只有固定合成值及身份，无账户、凭据、私有路径、受限市场数据；
其SHA为 `38488957d8d45275343662d2275ec386e2470047b6b7baf5346c1bf1f24104b2`。

KEEP原生撮合/钱包及旧单pairAPI；只实现窄固定目标内核、预算和对账。
不建设通用组合平台。当前**完整因果指标、ATR家族状态、C波动规则未实现**，
不得使用本合成模板跑市场。下一依赖仍需真实经济模板与受控输入，然后才是来源登记/有限训练。
本PR按固定SHA交监督，不自合并/关闭Issue，不把工程内核完成当总体研究终态。
