# Issue 119：已授权的唯一公开源采集

依据 [固定准入审查及采集授权](https://github.com/He1met/freqtrade-lab/pull/118#issuecomment-5574136863)，只采集 BTCUSDT/ETHUSDT Binance USDT perpetual `[2020-04-02,2023-01-01)`；2021年前仅warmup。经济合格、native和独立验证均未授权。

## 实际入口

`python scripts/capture_portfolio_source.py prepare docs/issue119-launch-manifest.json` 仅检查控制元数据并冻结文件/解释器SHA与完整命令。该manifest推送后，用其command原样执行一次 `capture`。无额外wrapper，无后台服务。唯一root与持久预算路径在 [源合同](protocols/issue119-source-contract.json)。raw、预算、登记及完整QC收据留在Git外。

[scope snapshot](issue119-scope-snapshot.json)绑定完整当前账本SHA和全部173记录身份；任何新增/修改记录都会在网络前阻塞，要求重新审阅实际元数据，而不是静默忽略新保护。59/63按已核验OKX spot原源scope；其他特定资产保护保守跨venue匹配该资产，2025 outer保守保留global、107原all-assets保护不变。此投影仅回答本次候选，不取代原账本；不靠68解除保护。首次GET前追加用途、含warmup源窗、training窗、审批及manifest绑定。原记录/数据不修改。

## 预算与失败行为

122次GET含失败、元数据和尾页；单worker，请求开始间隔至少1秒；单请求SIGALRM覆盖DNS/headers/read共20秒；整个采集30分钟。64MiB总/单响应5MiB。每次网络前fsync持久化一次请求及整5MiB保守预留，成功按实际原响应字节结算；失败/中断保留预留。最后余量不足覆盖下一整响应时会提前停止，这比总上限保守，不能自行增加额度。identity encoding；拒绝redirect与未知压缩，以免隐藏GET或解码量。无自动重试。单响应到达上限直接拒绝，不再多读一个字节。429/418停止并保留Retry-After。

全局budget文件已存在即拒绝新启动，不能换输出目录重置。唯一root已存在也拒绝；失败只能交监督处理，不能以修复名义偷偷重跑。局部失败可能已保留raw响应，但永不写source-ready产物。

## QC边界

两种小时源必须逐资产24096行、完整UTC小时/closeTime、唯一连续及OHLC合法，日聚合仅完整24小时。funding保留原eventTime、有符号rate、对应symbol和正associated mark，不挪时、不插零；有界尾页确认不能越授权end。缺associated mark立即失败保留原响应SHA。观测间隔统计与current fundingInfo不证明历史间隔完整；即使结构通过，也保持 `BLOCKED_DATA / historical_interval_evidence=UNKNOWN`，本版不发布可执行source。官方精度未知不阻止获准采集，也不被误报已核验。

17项纯工程测试覆盖跨域/全域/暖启动scope、账变动、首次GET前登记、跨目录预算拒绝、时间/请求/字节上限、429单次失败、redirect拒绝、分页/越界/重复/空包、关联mark缺失、历史间隔未知、CLI manifest漂移和实际capture失败不发布。测试命令：

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --with pytest python -m pytest -q -p no:cacheprovider tests/test_portfolio_source.py
```

实际终态收据在执行后补充；未采集前不声称source可用。下一依赖为源QC证据缺口和最小市场消费者，仍不评分。

## 实际终态

[脱敏终态与37响应SHA](issue119-capture-terminal.json)：`BLOCKED_DATA`，首个BTC funding页1000条事件的markPrice全部为空。BTC trade/mark各24096小时结构通过；ETH历史请求0。37 GET均HTTP200，共7,697,705字节，36.70秒，最小请求间隔1.00146秒，无重试。首次GET前账行176已登记；未写可执行source，native账SHA不变，经济结果NULL。尚余85个采集请求额度不构成失败后自动恢复授权；固定预算/root不重置。

缺失关联mark不能以邻近小时mark或当前mark填补。后续需要官方可核验事件mark来源，或独立审查新的源/日历合同；本次不自行扩大范围或把不完整源称为策略失败。历史interval证据亦仍UNKNOWN。
