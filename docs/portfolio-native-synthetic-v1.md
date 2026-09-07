# Issue #111：原生共享资金合成切片

基线main `4e1451b8028ff9a01b66be2ee08588d954a19aac`，前置经济协议
SHA `e664b6447879a350663fa7940036a2682d3970af65f7c218c540e2e62ff28e85`不修改。
本切片是固定目标执行内核的合成证明，不是完整趋势/反转经济模板；
完整日线指标、ATR家族生命周期、C波动公式、原始来源与实际结算精度仍为下游门。
禁止用这里的固定日历目标读取市场数据。试点正式市场许可仍false。

## 静态接口与最小探针计划（首次原生前固定）

官方Freqtrade2026.7，Git `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`，源码干净。
Python3.13.13 / ccxt4.5.68 / pandas3.0.3 / pyarrow25.0.0已核对。
现有单pair adapter不改。新入口只接受固定mode和锁定native源码目录，
不接受策略路径、行情路径、账户、命令或新预算目录。

```sh
PYTHONDONTWRITEBYTECODE=1 /path/to/pinned/venv/bin/python \
  scripts/run_portfolio_synthetic.py --mode B-risk \
  --native-source /path/to/clean/freqtrade-2026.7
```

实际环境使用已核对的issue-43-profile-driven-v1源码/venv，仅访问该代码和环境，
不读取同根研究DB或原生市场产物。每次一个Backtesting、一个策略、一个1000钱包和两个pair。
A-trend/A-reversal是两个分别执行的独立账户，B和C各自一个共享账户；绝不将A/B/C放同钱包。

| 固定槽 | mode | 非经济验收 |
| --- | --- | --- |
| synthetic/1 | B-risk | 过量两币目标按单账户MTM限额缩小；浮亏权益不同于wallet已实现余额；风险停止 |
| synthetic/2 | A-trend | 一家族两币共享账户；多空/翻向/小单跳过 |
| synthetic/3 | A-reversal | 另一家族独立两币账户；手续费/funding及退出 |
| synthetic/4 | B | 家族同币相反信号抵消、部分调仓、先平后下一小时翻向 |
| synthetic/5 | C | 固定因果降风险向量经过真实position adjustment；成本与MTM |

剩余synthetic/6–8不为凑数量而调用。最多4个技术备用，重试需要失败父槽和相同向量输入/原生源码，
改代码必须保留前后hash；改合成向量不是同输入修复。市场84计划槽不由本入口开放。
原生构造/执行失败均占槽。调用前在固定预算位置`~/.codex/runs/freqtrade-lab/btc-eth-portfolio-v1`
持久预约，output是其子目录，无输出目录选项。跨进程flock整个调用；记录fsync后才import原生。
事件追加hash链、终态只写一次；未闭合预约阻塞后续，不自动重放/回收。
异常原始日志/ZIP/trace在Git外，GitHub保存摘要与SHA。

固定合成向量在`lab/portfolio_execution.py::SYNTHETIC_VECTOR`，其规范JSON+mode绑定input_sha256。
OHLCV价格100/50，2020-01-01—01-08小时序列，固定八小时funding0.0001；
B-risk的mark在持仓第12小时降至90%、36小时至70%，OHLCV仍固定，用于区分mark浮亏与已实现钱包。
合成标记价格偏离成交价格是故意的风险探针，不声称真实市场形态。
第一输入raw目标BTC40/ETH80数量远超1000钱包；预算限额使实际总名义<=80%、单币<=40% MTM。
其它mode覆盖相反净额、减仓、翻向、零目标及小于最小名义但接近原生上调门的仓位。

### 原生已知行为与内核边界

`Backtesting`每账户共享wallet；`custom_stake_amount`与position adjustment可实现目标变化。
`wallets.validate_stake_amount`能将接近最小stake的值提高（最多30%）；
所以先按step向下取整，低于市场/原生padding最小值返回0，confirm再次防止实际quantity超目标。
部分退出用原生API要求的入场stake单位换算，不伪造分家族成交。
原生`wallets`余额不含全部mark未实现盈亏；内核从实际已成交order计算
`初始钱包 + Σ(-有符号数量×成交价-手续费) + Σ(净数量×已知mark) + funding`，
这是线性1x盈亏恒等式，不是撮合引擎。当前小时风险只看上一完整小时mark。

原生funding存储timeframe标签是1h，但该向量事件每8h一次，不能错误写成8h路径或补零。
原生calculate_funding_fees使用含首尾区间；后处理根据每个实际order间的持仓段与
同一固定funding/mark事件独立对账，不能只相信原生funding总数字。
手续费由每笔实际order数量价格重算，原生profit、最终平仓inventory和投影权益交叉校验。
这些是原生约定的合成对账；真实结算边界、保守扣减和滑点压力仍需后续消费者绑定。

网络在import原生前通过Python audit hook拒绝connect/getaddrinfo/bind，
exchange fetch也拒绝，不替换原生成交/钱包/资金费算法。生成数据只来自固定向量。
每次执行同时记录源码文件SHA、输入SHA、原生Git tree/commit、协议SHA、结果SHA与native ZIP SHA。

## 首次原生前验证

`PYTHONDONTWRITEBYTECODE=1 uv run --with pytest python -m pytest -q -p no:cacheprovider tests/test_portfolio_budget.py tests/test_portfolio_execution.py tests/test_portfolio_preflight.py`
→ 51 passed（0.17s）。覆盖重复/中断/锁/错误槽/损坏账、最小量不放大、
部分退出+费用+funding+持仓浮亏算术、前置协议不降级。
静态AST解析通过；未在这些测试中实例化原生引擎。

市场训练、完整A/B/C信号、独立确认、统计优势、FreqUI可见性均未证明。
首次原生计划与代码先推送冻结SHA，然后逐调用把实际结果、失败及修复追加到Issue #111。
