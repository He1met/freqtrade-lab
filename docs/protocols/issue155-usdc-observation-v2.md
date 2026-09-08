# Issue155 v2：前三个未来月事件观察，非交易

监督授权155#issuecomment-5585194678。v1原文保留，仅为历史设计；本v2替代其未来输入必须全新、24个月不披露结果、49GET建议。未来outcome检验可以使用决定前实际观察到的历史特征；月度固定描述不等于调参或逐次显著性检验。原历史独立范围尚未建立的审计结论不变。

## 冻结经济规则和授权期

唯一信号Coin Metrics `usdc_eth/SplyCur`，Ethereum链USDC存量，不解释为净新美元。事件月M的前一完整月月末/再前一完整月月末−1，严格>0 EXPAND，否则OTHER；任一输入月无效为UNKNOWN。ETHUSDT Binance spot；每月8日00UTC决定，01UTC入场，次月8日01UTC退出。单次1quote事件，base fee=.001/slip=.0006，stress=.002/.0012；净倍率 `(Pout/Pin)*(1-s)/(1+s)*(1-f)^2`。无钱包、复利、交易、参数选择。

| 事件 | 供给首次实际观察窗口 [start, stop)，UTC | 供给日标签（完整自然月，含首尾） | 价格一次观察窗口 [start, stop)，UTC |
|---|---|---|---|
| 2026-10-08 01 → 2026-11-08 01 | 2026-10-07 00 → 10-08 00 | 2026-08-01—09-30，61日；1 GET | 2026-11-08 02:10 → 11-09 02:10 |
| 2026-11-08 01 → 2026-12-08 01 | 2026-11-07 00 → 11-08 00 | 2026-10-01—10-31，31日；1 GET，复用已存九月 | 2026-12-08 02:10 → 12-09 02:10 |
| 2026-12-08 01 → 2027-01-08 01 | 2026-12-07 00 → 12-08 00 | 2026-11-01—11-30，30日；1 GET，复用已存十月 | 2027-01-08 02:10 → 01-09 02:10 |

每份供给响应、完整性检查及终态必须在stop前实际取得并持久化，才能使用。日期字段允许UTC零点Z/+00:00及全零小数秒；按自然月检查全部日标签唯一、finite、>0。缺日/重复/非法数值使所属整月NULL，不填零、不插值。身份/schema/非空分页不合约则整个请求UNKNOWN，不自动改字段。月报可在退出后由冻结规则机械重建信号，但只引用决定前已持久化且哈希吻合的快照，不补录迟到值。

供给等级`AS_OBSERVED_NOT_FIRST_PUBLISHED`：能证明决定前实际取得的版本，不能证明供应商最早发布时间/修订史。八九月历史特征不是新outcome，不需将其强行移到未来。每份已采供给版本固定，后续月不重取旧月。

每次价格GET只取对应事件 `[entry, exit]` 的ETH 1h K线：所有持有小时必须完整，退出仅要求有效open；最多745行、`limit=1000`，没有分页。未知/短持有小时整事件UNKNOWN。相邻事件只共用边界open，不重放旧开发期价格；后采的未来K线不是当时成交回执。B同时期观察不改变本候选冻结规则，也不构成两份独立市场样本。

## 预算、恢复与描述报告

授权总计6数据GET：3 supply+3 price，最多6MiB响应体；每次20秒/1MiB、0retry/redirect/pagination。每采集任务含检查<=60秒。每个price终态后至多一次离线描述评分，3次各<=180秒，总分析<=540秒；总采集加分析任务上限900秒。当前工程实现与冻结切片真实数据GET=0，首次到期为2026-10-07。

独立Git外root `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue155-forward-v2`。固定六个具名slot目录，创建即保守消耗一次预算资格；attempt在HTTP之前落盘。root独占flock防重入，原子写入+fsync发布控制/终态。已有slot绝不重试：进程中断即`INTERRUPTED_NO_RETRY`，HTTP失败/校验失败/迟到均UNKNOWN；错过时窗`MISSED_WINDOW`，不补取或滚动额度。原响应/headers/receipt/check/attempt完整保留；校验receipt、响应及check SHA后才能评分。控制/代码漂移在CLI触达运行root或网络前拒绝。评分中断占用该月分析名，后续累计报告把它列UNKNOWN，不重算旧事件。

每个完成事件一次报告：本月输入增长/分组、毛净、UNKNOWN原因、原收据哈希，及只从先前报告派生的累计事件、组n、两成本均值/中位数/正数/集中度/组差和实际覆盖月份。`tick`/`status`返回报告路径。月报不是逐次假设检验，不以报告结果停选/改规则/凑组。前三月全部终态必须`UNDERPOWERED`，即使全部正收益也不宣布成功。机器休眠/断网/监督未在时窗运行，按上述明确缺失处理。

用户20%风险硬要求不变；本事件诊断`wallet=false, drawdown=NULL, risk_qualified=false`，不代表策略运行或满足风险要求。没有交易授权，不直接晋级。未来因结果改变规则则原确认结束，另立新假说，不能继续累样本洗白。

## 24月设计边界与实际入口

整体仅预注册2026-10—2028-09共24个事件，末次退出2028-10-08 01UTC；不是24月采集授权，当前CLI根本没有后21事件slot。最终预定描述门：任一有效组<5或任一组在前12月(2026-10—2027-09)/后12月(2027-10—2028-09)没有事件，报样本/时期不足；否则任一成本组差<=0报STOP_RULE_NOT_SUPPORTED，再否则EXPAND任一净均值<=0报NO_LONG_COST_SUPPORT，否则至多PROSPECTIVE_SIGNAL_ASSOCIATION_REPLICATED。n与半期覆盖是设计建议，无80%功效保证；序列相关、时期混杂依然存在，24月结果无钱包资格。剩余范围须另有明确预算授权，不能重命名root扩展当前六slot。

入口（在本仓库执行，`FREEZE_SHA`替换为交付的完整SHA）：

```sh
PYTHONDONTWRITEBYTECODE=1 uv run python scripts/issue155_forward.py check --manifest docs/issue155-freeze-v2.json --sha256 FREEZE_SHA
PYTHONDONTWRITEBYTECODE=1 uv run python scripts/issue155_forward.py status --manifest docs/issue155-freeze-v2.json --sha256 FREEZE_SHA
PYTHONDONTWRITEBYTECODE=1 uv run python scripts/issue155_forward.py tick --manifest docs/issue155-freeze-v2.json --sha256 FREEZE_SHA
```

`check`不创建root、不读市场原文、不联网；`status`只读本候选控制终态。`tick`用机器实际UTC，无CLI伪造时间/root/URL/预算开关；时窗前仅初始化隔离freeze身份并返回PENDING，时窗中取该固定slot一次，超期标缺失，有price终态则报告一次。同一入口可重复调用，前后三个月之外没有额外请求。监督验收后由现有heartbeat在每个due窗口调用即可，范围内无需逐次用户审批。本次不新增automation/daemon、不修改既有heartbeat、不改global或B任何grant/执行文件、不加DB表/账户/key。

必要验证限合成时钟+本地生成供给/K线、临时目录与mock transport：完整六slot生命周期、重复调用、缺失/迟到/中断、预算/HTTP边界、日历/schema、持有小时、收据漂移、锁与freeze拒绝、月度累计和UNDERPOWERED。测试fixture无市场来源；工程通过不是策略证据。保留Issue155 OPEN交PR监督验收；验收合并也不代表实际三个月观察已完成。
