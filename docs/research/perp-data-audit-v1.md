# BTC/ETH 永续数据与历史证据核验 v1

本次已拿到单一 Binance USD-M 场所 18 个月完整小时价格主干和逐笔资金费，足以交给原生 Freqtrade 开展新的开发期有限对照。OI 只有最近约 21 天，已开始增量留存；链上日值已真实获取，但没有历史当时版本，只能作为开发诊断。数据工程通过不表示策略盈利。

这是 Issue #162 / `BTC_ETH_PERP_AUTONOMOUS_V1` 的新版本。旧冻结批次不改。仓库起点 `89eaa8f` 已由监督任务核远端；环境和下列实际产物于 2026-09-08 UTC 核验。

## 场所、环境与已知边界

- 研究来源暂定 Binance USD-M，执行场所未确认；没有读取账户或凭据，没有更改交易所或账户风险。研究资金 `1000 USDT`、杠杆 `1x` 均属研究假设。
- 当前 BTCUSDT / ETHUSDT 都是 `PERPETUAL`、quote/margin=`USDT`、`TRADING`。BTC tick=`0.10`、lot=`0.001`、min notional=`50`；ETH tick=`0.01`、lot=`0.001`、min notional=`20`。这些是此次公开 `exchangeInfo` 快照，历史规格/PIT未验证。
- 原生 Python `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python` 实测可用，Python 3.13、Freqtrade `2026.7`、pandas `3.0.3`、pyarrow `25.0.0`。旧说明中的 `site-packages/python3.12` 不适用。源码 `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade` 当前 SHA=`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`。
- 新原生基线的 maintenance tier `0.025` 是 1x 离线引擎假设，未通过账户接口验证历史档位。当前交易精度和Taker成本假设不能被称为历史完美成交；小时内极端价格顺序和真实滑点仍未知。

## 已有合约证据及可复用部分

优先从 `docs/research-knowledge/btc-eth-1000-central-v1.json` 追到 `docs/issue127-diagnostic-summary.json`、#129修复及 `docs/issue131-corrected-terminal.json`，逐个读取仓库外 `corrected-exploration-jobs/01..10/result.json`，10/10 SHA 与终态记录一致。没有重跑旧批次或读取sealed段。

旧统一钱包是日级63日趋势、短期反转及B/C组合，不是本次小时突破的经济结果。2024-08-01—2024-11-01开发比较的实际原生订单驱动模型结果如下，金额单位均为USDT，非真实账户收益：

| 旧对照 | 价格毛现金流 | 模型成本后净额 | 模型观测DD | 订单数 / 持仓周期 |
|---|---:|---:|---:|---:|
| A-trend | 10.382610 | 10.351359 | 1.2091% | 2 / 1 |
| A-reversal | -2.521580 | -3.177898 | 1.5428% | 6 / 3 |
| B | -0.259520 | -0.447992 | 0.5329% | 6 / 3 |
| C | -0.781720 | -0.960045 | 0.4358% | 6 / 3 |
| half-risk-B | -2.096960 | -2.156018 | 0.2506% | 2 / 1 |

分类不能混为“都失败”：

- **技术错误**：旧reserve端点在Decimal精度下误削数量，#129已精确修复，#131实际原生消费者复核后B/C订单发生变化；旧结果保留。
- **成本后不支持**：反转与B/C及half-risk在该已暴露小窗仍为负。不能用修复导致亏损变小证明机制有效。
- **样本不足**：A-trend模型净额为正，但仅一个实际周期/一个可归属自然事件簇。10个base/stress任务不可当10个独立样本。
- **风险信息不足/未独立确认**：模型观测DD低，并不意味着连续风险已验证；旧终态 `continuous_risk_coverage=UNKNOWN`、历史交易规格未证、独立确认未执行。
- **结论**：旧中央试点 `UNDERPOWERED / NO_REAL_ECONOMIC_QUALIFICATION`。不追改为合格，不把净正的一条重新装成未见证据。

复用原生环境、精确资金费/订单审计思路及失败知识。旧输入实际目录 `/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue119-btc-eth-source/continuation-v2/raw` 只读；旧曝光范围2023-11—2024-11与sealed 2024-11—2025-01均保留原标签。本批2025-01—2026-07全部明确为已暴露开发用途，没有独立确认资格。其他旧现货、LINK funding等只属历史索引，不改标成BTC/ETH合约结果。

## 首批真实数据与时点

| 数据 | 每币实际行数 | 实际覆盖 | 质量/用途 |
|---|---:|---|---|
| 合约OHLCV、mark、index、premium，各自 | 13,104 | 2025-01-01 00Z—2026-06-30 23Z | 各0缺小时、0重复、0越界；开发输入 |
| 已结算资金费及当次mark | 1,638 | 首2025-01-01 00:00:00.015Z；末2026-06-30 16:00:00.005Z | mark无缺；保留毫秒时点；开发成本 |
| OI数量/名义值 | 500 | 2026-08-18 20Z—2026-09-08 15Z | 最近窗口；数量单位进一步核验前不进模型；仅前向积累 |
| Coin Metrics TxCnt、AdrActCnt | 546日/指标 | 2025-01-01—2026-06-30 | catalog实证免费1d，0缺值；无历史vintage，仅开发 |

资金费逐相邻事件实际间距 `28,799,984—28,800,016 ms`。本批实见每8小时一个事件，但不把8小时设成跨合同/跨未来的常量；通用缺事件计数仍 `NULL`。主线使用真实事件的正负现金流，不用预计费率替代，不补缺资金费为0，不重复扣费。Binance返回的 `markPrice` 对应当次charge。作为信号，历史最早可用时刻采用结算后1h的保守假设。

K线 `event_time` 为开盘，历史 `available_at` 是收盘+60s；本次小时策略需额外等待一根K线后由native next-bar执行。OI文档时点是统计周期结束，信号假设再滞后1h。链上历史 `available_at=日开始+48h` 只是保守假设，无法补出不存在的历史PIT。

真实增量记录的可用时间还必须不早于 `fetched_at`。首次live采集已单独保存 `observed-availability-v2` 离线更正文件，原始响应/旧receipt不覆盖；只是数据观察，没有生成过去信号。以后采集器直接应用这个实际抓取下界。

## 权限、调用及实际恢复

- 默认sandbox的1次Binance时间探测在DNS层受限，没有HTTP响应；按系统沙箱流程取得本任务公共采集权限后，时间GET为200。未改代理、DNS、账户或网络配置。
- 历史主capture：82 GET，14,699,616 bytes，约31秒；最后Coin Metrics旧catalog参数`assets`返回HTTP400。此永久参数错误没有原样重试。
- 官方文档确认 `/catalog-v2/asset-metrics` 后新补充capture：2 GET / 103,977 bytes，catalog与日值均200。Python3.9不能直接解析提供者9位小数秒，离线修复日期解析并生成新v2收据；0新GET、原失败收据保留。
- 首次增量：15 GET / 1,111,582 bytes；实际窗口2026-09-08 14:00—15:00Z，核心完整，OI每币2行，最近链上每币4日；没有该小时资金费事件，返回空事件数组不是补零。
- 集成审阅发现旧幂等检查仅凭中间`receipt.json`存在会误报成功，已修复：只有原子提交的`update-receipt.json`明确`core_complete=true`且身份一致，才返回`NO_OP_ALREADY_CAPTURED`；完整失败返回`NO_OP_BLOCKED_DATA`和原错误，只有中间收据返回`INTERRUPTED_CAPTURE_RETAINED`。三种情况均0 GET；instrument rules永久熔断也验证为0 GET。没有把部分采集升格为就绪。
- 同小时第二次入口实际返回 `NO_OP_ALREADY_CAPTURED` / **0 GET**。本数据子任务累计100个公共GET（含1次时间GET），低于首批120预算，无市场回测worker。网页文档搜索和pytest依赖安装另属工具/依赖开销，不混入数据GET。
- `tests/test_perp_data.py` 实际19 passed，覆盖纳秒时间、未来K线、OHLCV质量、缺口/重复、禁止重定向、锁、小时幂等、发布缓冲、永久熔断、有限重试、崩溃预留及迟到可用时间及禁止Git内保存原始行情。默认uv缓存/DNS被sandbox阻断后改临时缓存并按沙箱流程安装pytest；未修改native venv。

## 可运行入口与数据索引

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/perp_data.py --incremental \
  --root /Users/shenjianpeng/Documents/freqtrade-lab-local/perp-autonomous-v1/data/incremental
```

该入口给监督调度调用；它本身不是新daemon。整点后10分钟开始，单writer，hourkey目录幂等，最多24 GET/300秒/20MiB、576 GET/日、4032 GET/周，先预留预算再发请求，保留未知中断目录，不重跑未知小时。已完成时间之后最多回填24小时，更长中断记录缺口，不回放交易或信号。OI每小时2行保存重叠vintage、资金费保留过去24h重叠供版本核验、链上每日一次；永久权限/语义错误按endpoint熔断，修复须留版本记录。动态HTTP重定向禁用。小时缺口在数据receipt可见，不能由调度静默补成价格或费用。

- 全部runtime根：`/Users/shenjianpeng/Documents/freqtrade-lab-local/perp-autonomous-v1/data`
- 历史主干：`first-capture-v1/receipt.json` / `requests.jsonl` / `raw/` / `BTCUSDT-ohlcv.jsonl` 等；各JSONL有SHA，8类小时序列SHA实测一致。
- 链上：`cm-supplement-v1/catalog.json`、`coinmetrics-network-normalized-v2.jsonl`、`normalization-receipt-v2.json`。
- 实际增量：`incremental/20260908T150000Z/update-receipt.json`；首次观察时间更正=`observed-availability-v2/receipt.json`。
- 轻量目录：[perp-factor-catalog-v1.json](perp-factor-catalog-v1.json)。记录定义、单位、源字段、频率、真实覆盖、用途、许可边界、延迟与修订。

唯一数据优先方向：维持上述小时增量和OI版本留存，支持首个小时突破对照的真实报告；链上下一步仅在同可用样本对照里检查一项活动因子增量。没有PIT或足够新OI时不自动进入独立确认，不购买数据、不建全链索引器。

## 已核官方语义来源

[Binance USD-M Market Data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data) 当前注明OI只保留最近1个月；funding历史记录携带结算时点和对应mark，间隔调整由实际记录/信息接口决定。

[OKX V5](https://app.okx.com/docs-v5/en/#public-data-rest-api-get-funding-rate-history) 当前历史资金费接口区分`fundingRate`预计值与`realizedRate`实际值，并注明该接口最多回看3个月；OI分别有合约数、币数量、美元名义值。OKX只作为语义备选核验，没有混入本批Binance成交/结算数据。

[Coin Metrics API v4](https://docs.coinmetrics.io/api/v4/) 的catalog-v2实际验证了两链TxCnt/AdrActCnt的community日级覆盖；[TxCnt定义](https://docs.coinmetrics.io/asset-metrics/transactions/txcnt)约定链上交易计数，[Community API说明](https://gitbook-docs.coinmetrics.io/access-our-data/api)说明无key免费非商业community访问。公开接口文档不等于历史当时版本；未购买或使用Glassnode权限。
