# ATOM_REGIME_PULLBACK_V1 — 待授权草案

2026-09-06；代码基线 `0e4d8e9d33b806239bb13d618b4db2881a892ac3`。**唯一推荐：OKX ATOM/USDT 现货日线，上升状态中的回撤回归；一次固定基线 Search，1 轮/1 attempt。** 本文件不是采集或执行授权。本轮仅 3 次官方文档/身份请求，全部成功、无重试；没有市场值、策略入库、项目代码/数据库修改或 native 调用。

## 为什么选它

| 本轮仅比较两个方向 | 数据与经济理由 | 决定 |
|---|---|---|
| A：OKX ATOM 现货回撤回归 | 日线历史 API 与 spot 阶段入口已存在，资金费/mark 不适用；买入低于短期均值的回撤，期望局部卖压消退后的价格回归。长期状态过滤用于避免持续下跌中的反复接盘，不能预设过滤有效。 | 推荐一次可证伪检验；不是因为代码可跑就认为盈利。 |
| B：Binance ATOM 现货 20 日价格突破、10 日通道退出 | 毛收益来自方向延续，较慢交易给费用留下空间，假突破和震荡受损。[官方档案说明](https://github.com/binance/binance-public-data)支持月度文件、CHECKSUM，但“All symbols”不证明选定月份存在；本轮未查目录或数据。 | 不选。现工作台 Profile、producer、provenance、Search/D/H、wrapper 多处绑定 OKX，可信接入预计 2–3 个工作日，超过一天；不会把 Binance 数据伪装成 OKX。 |

B 若以后单独研究，需保留官方 CHECKSUM、本地 SHA、取得时间及修订身份；2025-01-01 起 spot 档案时间戳为微秒，前段按官方格式验证。跨交易所同币价格高度相关，不能因此重用已暴露同币同时间段作为独立验证。它仍属趋势家族；本轮没有选择第三方向。

A 与旧 TRX 规则的区别来自已读**源码**，没有回看旧 PnL：旧规则以三日跌幅≤−3%、低于五日均值入场，没有长期状态过滤；本规则不用三日收益，改为相对二十日均值的价格折让、二百日长期状态和相应退出。仍是回撤家族扩展，换资产不证明独立因子。若均值固定、在其 96% 买入并回到均值，毛空间约 4.17%；基本双边成本预算约 0.4%，但均值下移、跳空、入场延迟和止损会破坏这个示意。以约 4.17% 赢幅/8% 亏幅及每次约 0.4% 成本粗算，盈亏平衡胜率约 69%，要求并不轻松；该算术不是预测。

## 唯一规则与配置

每天 UTC 日线完全收盘后，计算含当前完整 bar 的 `mean20=close.rolling(20).mean()`、`mean200=close.rolling(200).mean()`。

- 入场：`close <= 0.96*mean20 AND close > mean200 AND volume > 0`。
- 信号退出：`(close >= mean20 OR close < mean200) AND volume > 0`。信号按原生规则下一根开盘执行；8% 价格止损独立遵循 native 日线止损语义。无每月强制平开、加仓或人为制造交易。
- `INTERFACE_VERSION=3, timeframe="1d", can_short=False, startup_candle_count=200, process_only_new_candles=True, minimal_roi={}, stoploss=-0.08`；无 trailing、自定义杠杆/止损/仓位回调。ROI 退出应为 0。
- 原生配置由 `profile_search_config` 生成：`exchange.name="okx"`, pair `ATOM/USDT`, `trading_mode="spot"`, `margin_mode=""`, `dry_run=True`, `dry_run_wallet=1000`, `stake_amount=500`, `max_open_trades=1`, `tradable_balance_ratio=0.99`, `fee=0.001`, `detail_timeframe=None`, `backtest_cache="none"`, `StaticPairList`。每阶段从现金开始，固定 stake；不足完整 stake 即风险失败，不缩仓或复利补救。native 固定为 Freqtrade 2026.7 / `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`。

内存源码的本地静态分析已通过，lookback=200；S/D/H 的 spot 1d 资源边界也通过。未把静态通过称为已执行。源码检查 SHA 见 `static-capacity.json`，正式注册前冻结最终完全一致的源字节及协议 SHA。

**消融决定：本轮不做。** 原生引擎能执行两臂，但当前 Search Round 1 要求不同 `MECHANISM_SEED`，同机制消融不能忠实登记；普通双种子必须进入 Round 2，终态按排名选择，缺少“仅完整规则可晋级、消融仅诊断”的字段。`SINGLE_BASELINE_V1` 又严格只有一臂一轮。不能把消融假称独立机制或让它成为备胎，也不为此次比较扩建筛选协议。故只检验完整规则的净经济资格，**不声称证明 200 日过滤改善预测或优于无过滤**。若另行授权消融设计，须在取得 S 值前改变此协议；本草案执行后不得补做救援消融。

## 来源、窗口与容量

[OKX 官方日线历史接口](https://app.okx.com/docs-v5/en/#order-book-trading-market-data-get-candlesticks-history)支持 `history-candles`、`1Dutc`、分页、完成标志及现货基础币成交量。当前 [ATOM-USDT 身份](https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId=ATOM-USDT)为 live，`listTime=2021-01-29 08:08:06 UTC`，早于前史；响应 SHA `5bbbb3f7401970dc10f15ad6716e1a1e5eeee40b0d7c79f71e0baec2d9e0d72a`。官方“近年历史”不是逐行覆盖承诺，实际可得首行、缺口及质量留给**一次正式采集 QC**。

| 阶段，UTC 左闭右开 | 200 日前史起点 | 评分日数 / 含前史行数 | 完整 30 日历块，仅容量参考 |
|---|---|---:|---:|
| S `[2021-09-01 00:00, 2023-09-01 00:00)` | 2021-02-13 00:00 | 730 / 930 | 24 |
| D `[2023-09-01 00:00, 2025-01-01 00:00)` | 2023-02-13 00:00 | 488 / 688 | 16 |
| H `[2025-01-01 00:00, 2026-05-31 00:00)` | 2024-06-15 00:00 | 515 / 715 | 17 |

已有有限身份/窗口投影未发现 ATOM 经济暴露；上轮 ATOM 永续检查只接触身份与空目录，未消费市场数据。XLM 已消费 S、其 D/H 阶段保留与 BTC/ETH 历史暴露不被重新声明独立，也不泛化为所有资产全历史禁用。监督指定 UNKNOWN 尾窗 `[2026-05-31,2026-07-31)` 已排除。本方案按目前有限账本覆盖提出，若登记时出现具体身份冲突则停止，不重划窗口。前史只初始化，评分窗口不重叠。

日历块不是独立样本。200 日状态、持仓跨块及成簇回撤会让有效事件数大幅减少；实际合格交易数、持仓时长和样本容量均 **UNKNOWN**。较短的均值回归目标使其有机会比 12 个月动量产生更多自然完成事件，但不能事前保证达到下列门槛。

## 值前资格门及失败规则

所有门在采集前冻结，S/D/H 分别判定，不按某阶段结果调整：

1. **经济：**基本费率每腿 0.001；每腿另外按实际成交名义额扣 0.001 滑点预算。成本后净收益严格 >0，native 费后 PF≥1.0，ROI 退出=0。另报告毛价格 PnL、进出费、滑点、换手额，不能用少交易直接推断价格预测改善。费用是假设预算，不冒充账户费率。
2. **成本承受：**每腿 fee=0.002、slippage=0.002 的敏感性净收益也须 >0。S/D 是原路径逐腿算术敏感性，必须重建现金可执行性；若更高成本使任一完整 500 stake 无法成交，判失败，不报告成真实回放。H Stress 只有单独授权后才调用原生双倍 fee，再扣滑点，不能用 S 敏感性冒充 H Stress。
3. **风险：**native DD≤20%，同时按每日持仓盯市、实际费用与上述成本计算的峰值相对 DD≤20%。日线风险估计保留无法重建日内成交路径的局限；不能把价格止损当亏损上限。不能核对账务/现金则技术阻塞，不填零。
4. **样本/集中度：**每阶段至少 12 个自然完成交易；S 至少 8 个、D/H 各至少 6 个完整 30 日暴露组。从首个入场起连续 30 日归组，其内入场归同组；跨组持仓全部归原组，不拆单凑数，末尾未满 30 日组不计完整组，末端强平不计自然交易。移除收益最高组后阶段成本后净收益仍 >0。组数不是 IID 证明；即使全过，也只称本协议研究通过，不称长期盈利已证明。净正但样本不足为 `UNDERPOWERED`，不得降门。

任一决定性失败即终止：经济失败为 `SEARCH_TERMINATED_NO_FINALIST`；数据缺口/接口失败为 `BLOCKED_DATA`；技术或会计不一致明确记为技术阻塞。无补跑、参数调整、资产替换、窗口移动或失败后解封后续阶段。

## 一次采集、一次 Search 与现有入口

首次采集只取 `[2021-02-13,2025-01-01)` 的 spot 1Dutc，共应有 **1418 行**；D 仅 producer/QC 物化，模型不读取 D 值，H 不采集。现 producer 每页 100 行，预期 15 次行情分页＋1 次身份＝16 次 HTTP；硬上限 **24 次实际请求/30 分钟/零自动重试**，失败计数，超限前拒绝。复用既有请求计数保护及 `fetch_okx_profile_data.py`，只允许身份和该 spot 历史端点；不请求资金费、mark 或其他市场。验证 UTC 精确连续、confirm=1、有限有效 OHLCV、无重复/填补、基础币 volume、文件与 provenance SHA；任一不符停止。档案有无完整行不是本轮预设事实。

授权后在新 Git 外目录及非敏感独立 SQLite，复用现有 connection factory、Profile 和 Generation 注册路径，不新增表/字段。Profile：`history_start_date=2021-02-13`, `holdout_days=515`, `min_development_trades=min_holdout_trades=12`, `max_drawdown_pct=20`, `min_profit_factor=1`, `stress_fee_multiplier=2`。现无 Profile 写页面，使用已有注册 API/同结构一次性脚本；禁止为本方案加页面。

实际顺序：`scripts/fetch_okx_profile_data.py --profile-database … --profile-id … --window-spec … --pre-roll-candles 200 --single-baseline … --output-root …` → `scripts/run_bounded_research_pilot.py prepare-search-data`（绑定 source receipt/provenance SHA、`--search-timerange 20210901-20230901`、pre-roll 200）→ 同 CLI `screen-search --campaign-root … --freqtrade-python … --freqtrade-source …`。冻结 `SINGLE_BASELINE_V1`，最多 **1 轮/1 attempt**，没有第二个候选或预留救援轮次；一次原生失败也不自动重跑。

结果在现有 Research Console 的新 campaign 展示；运行时另择空闲端口，不覆盖已完成任务。补充成本/样本审计写 Git 外 receipt 并绑定原生 ZIP、协议及源 SHA，沿用已有终态投影方式。只有完整规则所有 S 门都通过，才允许 finalist 导入和 ResearchRun；否则 ResearchRun 保持不存在。D 通过现有 `prepare-development-data`、Console Development/`run_development_candidate.py` 承载，后续须另行授权。H-only source 与 H/Stress 沿现有 spot 1d 同 run 入口；未来若放行 H，预期 9 次 HTTP、硬上限 16 次，仍零重试；不会在本次首次采集中提前取得。

**工程预计：项目文件修改 0。** Git 外注册/预算绑定及逐腿、每日盯市、分组审计约 3–6 小时规划量，复用已有脚本，无新 runner/native/数据库结构。若正式准备发现必须修改业务入口，先停止该项并回报具体缺口，不扩建。尚未验证的实际 API 覆盖、真实 QC、交易数、收益、审计运行结果均 UNKNOWN；下一步是审核此固定草案后授权上述一次采集与 Search，而不是再开一轮概念审查。
