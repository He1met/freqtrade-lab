# Issue #115：synthetic/6准备回执

状态 `PREPARED_NOT_EXECUTION_AUTHORIZED`。本轮0原生调用；不读取市场、资金费历史或保护窗。
旧base/semantics未变，96预算未重置。固定完整绑定在 `issue115-prepared-binding.json`。

## 固定输入与机制

`tests/fixtures/portfolio-causal-probe-v1.json` 是人工构造小fixture，非市场资料。
SHA256 `b3a14a673303bcb3f7406d0599756b2c4b1bfb5b35900f96573e841fd079cfce`。
280个日收盘生成两币各6720小时；日线OHLC直接聚合这组小时数据。
2019-10-03 00:00 UTC开始观察。所有数值是本合成覆盖建议，不用于市场评分或更改风险阈值。

- 完整warmup后实际 `daily_decision` 同时触发trend多/reversal空，没有注入Decision。
- 第2小时闭合high触发反转家族stop，趋势家族继续；预期原生先平空，下一小时才开多。
- 第5小时已知open跳空，触发趋势家族退出；不假定stop价成交。
- 冷却结束后真实日线再次激活；第77小时反转stop，保留趋势。
- 第97小时已完成mark降至交易价50%，目的是检验实际MTM halt。这个独立mark冲击
  不代表市场一致性或可成交真实性；预计可能超过用户20%风险门，必须同时报告风险失败。

实际成交、halt和净收益还没运行，不是已通过结果。

## 窄原生接线

锁定Freqtrade2026.7 source `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`。
`backtesting.py:1671` 先调用bot_loop_start，随后逐pair处理；`:1700`直接读取行中entry bits，
不调用策略get_entry_signal。因此只覆写 `validate_row` 的long/short信号位，将当前因果
净目标路由到原生；OHLC、订单、价格、手续费、钱包和撮合保持原生。
`:1610`时间循环从start+1h开始，所以加载范围前移一小时，并审计首点恰好等于日线决策边界。

`account_snapshot` 从实际已完成订单计算净量、费用/滑点/资金费与已知mark权益；
一旦开启新持仓周期即撤销旧flat receipt，直到该周期实际订单净量回零才产生新receipt。
失配/未来订单不放行，旧平仓时间不能批准后续翻向。原生未执行的减仓原样保留告警；
目标0不当作成交0。回调异常被原生wrapper吞掉时，本adapter锁定失败并保留错误轨迹。

每边6bp fee及6bp slip从实际成交额扣到净权益，后者进入日线ATR数量、peak/DD及halt。
native free扣累计slip再传给现金门；fee仍由原生收取。最终净权益要求和native profit减
实际fill slip复算一致。原生funding None仅表示该原生对象初始未计提状态；fixture结算事件
不缺失，但真实资金费首尾、舍入和结算资格仍 `UNVERIFIED`。

## 现金不足的可达性（未覆盖，不声称PASS）

`wallets.py:105–174`：isolated dry/backtest free = 初始余额 + 已实现利润 - 开放仓位stake，
没有把全部浮动mark PnL并入free；`:314–323`可用stake取free和剩余总stake限制的较小值。
`backtesting.py:719–758`加仓每次读取实际available，成功后update钱包；`:1266`创建订单后
尝试原生成交。`:1684`先处理已有仓位，但不能据此假设所有计划减仓均已释放。

所以最终目标<=80%不证明逐订单现金充足。当前固定输入两币同向同尺度、1x、market单、
无额外占款且不预花减仓释放，尚无证据表明会触发现金不足；不为覆盖添加假钱包/第三账户。
本原生场景标 `NOT_COVERED_NATIVE`，已有纯函数free=100测试及压力成本测试继续保留。
不将此缺口自动扩大成平台依赖，交监督统一裁定。

## 入口、绑定与验收

只读准备入口：

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python scripts/prepare_portfolio_causal_probe.py --native-source /Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade
```

CLI无执行、预留或重试参数。`run_reserved`供获准后最小dispatcher使用，要求已有唯一durable
synthetic/6 reservation及四重绑定，缺失先失败且不导入native。准备阶段只读取budget前缀。
预算reserve向后兼容旧记录，新6–8槽必须带semantics SHA；同输入技术重试必须继承该SHA。
批准后的dispatcher仍须持全程writer锁、先reserve+checkpoint、超时、失败占槽、证据落盘、
finish+checkpoint及事后code/source复验；本轮没有实现可直接绕过审核的执行CLI。

审计断言要求真实两币成交、原始日线决策、短家族stop后实际先空转多并等下一小时、gap真实
退出、实际mark halt后无新增单、净成本对账；任一缺少即失败，dust需显式审查。
实际订单/钱包/逐时轨迹和原生ZIP将留Git外。合成control PASS不等于risk PASS或市场资格。

测试：84项非原生测试通过；另在锁定native环境完成类导入和无constructor/start的方法验证，
确认bridge只修改两个信号位。实际prepare入口通过，输出清单保留旧6个已占槽。
账本SHA仍 `986f164d19be4d4188ef59d8a052102f3a9c479469c8a7bc1703d214c1c97d7a`。
下一门：监督审查固定提交、输入及断言，才决定放行现有synthetic/6一次。
