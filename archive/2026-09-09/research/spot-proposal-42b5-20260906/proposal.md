# TRX_DAILY_PULLBACK_MEAN5_V1 — 值前提案，尚未冻结

**建议执行一个探索性 S：OKX TRX/USDT spot、日线、仅做多。** 现有 Profile→Generation/Candidate→Console批准/Search 可表达，源码静态验证已通过。市场连续性、实际样本和收益均 UNKNOWN。本文件不是采集或回测授权。

## 两规则比较与唯一选择

| 规则 | 经济理由及旧族关系 | 值前成本/容量判断 |
|---|---|---|
| 持续趋势：收盘高于60日均值持有，低于均值退出 | 信息逐步反映；与旧动量/均线族同族，不冒充独立发现 | 目标持仓数周至数月，费用较低，但一年可能只有少数持仓，单资产样本证据薄；本批不执行 |
| **主规则：3日累计价格跌幅≥3%，且低于5日均值时买入；回到5日均值退出** | 暂时卖压后流动性补偿/价格修复；与旧短期反转族同族，区别是spot仅多、跨日冲击与均值退出，不声称独立学术机制 | 研究持仓尺度约2–10日（设计意图，不是观测或保证），一年约36–180个顺序持仓时段的日历容量，实际触发可为0。比趋势更有机会在一年内检验重复事件；仍须成本与样本门 |

3日代表多日卖压，5日代表一周内的短期均衡；3%触发要求价格位移显著大于基准往返摩擦0.3%，只需要其中约十分之一修复才接近收支平衡，但**3%跌幅不是可赚取3%**。8%止损防止无限持有下跌资产；未规定时间止盈，不强造固定持仓次数。每日评价因为市场连续交易且修复并无星期依据；这些参数未由ETC、DOT或本轮价格选取。

依据：[Moskowitz等原论文说明](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)支持传统市场趋势方向；[Nagel原论文](https://www.nber.org/papers/w17653)将股票短期反转联系到流动性供给。这些都不是TRX日线盈利证明，3/5日参数是本提案的经济尺度选择。

## 资产、窗口及残余限制

监督预设资格顺序TRX→XLM→ATOM；三个指定索引完整身份叶投影、现有Issue body/title均无hit。取第一项TRX，不看价格/成交额排行、不再换资产；只称**指定范围内条件性资格**，不称全球未见。旧spot/futures信息不按市场切换释放。

S=[2024-01-01,2025-01-01)，366日；D=[2025-01-01,2026-01-01)，365日；H/Stress仅预留=[2026-01-01,2026-05-31)，150日。S预热10根，从2023-12-22 UTC开始。D/H各使用前10日已结束K线作为固定因果预热；这一**本批预注册阶段交界处仅用于指标初始化的上下文重叠**不评分、不用于调参，S/D/H评分及持仓互不跨界。它不是重用旧cohort；若监督要求连初始化也完全不重叠，必须在读数据前另裁决，不能运行后改日期。

旧#32已hash绑定XRP；#30仅PR31生产合同支持2026-06-01至07-31固定评价，实际receipt/部署SHA/资产仍UNKNOWN。监督接受排除所有资产[2026-05-31,2026-07-31)的保守边界。此前误读及输出截断继续作为残余不确定，不清零；详同目录exposure-note.md和contract-boundary-adjudication.md。本提案不把该代码证据冒充旧terminal来源链。

## 数据及因果执行

OKX `GET /api/v5/market/history-candles`、`1Dutc`、TRX-USDT，confirmed=1、九字段、UTC连续、base-volume语义；沿用已合并spot raw→CCXT→Feather校验，mark/funding N/A。官方合同见[OKX文档](https://app.okx.com/docs-v5/en/)。授权后先核公开instrument listing/state/spot身份，上市时间必须覆盖2023-12-22；失败STOP，不切XLM。

K线标记为开盘时间t，指标使用完整[t,t+1日)收盘，最早t+1日开盘执行；不额外shift整个信号造成双重延迟。无ROI、无做空/杠杆/加仓。止损采用native日内low触发、跳空按native开盘规则；OHLC日线内路径无法实证，记录其限制。期末按native强平并单独列出，不能靠强平收益通过门。每个阶段空仓起步。

## 仓位、成本与值前收支

Profile: domain=OKX_CRYPTO_SPOT，pair=[TRX/USDT]，trading_mode=spot，margin_mode为空，timeframe=1d，detail_timeframe=null；starting_balance=1000 USDT，固定stake_amount=500，max_open_trades=1，tradable_balance_ratio=0.99，無复利扩仓。8%价格止损约对应初始账户4%损失，跳空可更大；研究账户DD预算10%并非用户真实资金偏好。

基础taker_fee_rate=0.001/边；参考[OKX公开费率说明](https://www.okx.com/en-gb/help/what-are-the-new-trading-fees-for-eea-users)，仅为本研究费用假设，不是用户账户费率核定。另加不利滑点0.0005/边，基准往返摩擦约0.30%。500名义本金每次约1.50 USDT，12/24/36次约18/36/54 USDT；对应账户1.8%/3.6%/5.4%的毛收益需求，均是算术情景，不是预估盈利。设计若平均毛收益只有0.2%/笔，仍会成本负。

唯一native S使用基础费。所有成本重计保持原ZIP的实际amount、时点、价格及交易路径不变，不按500预算重新计算策略数量。每笔基准PnL = native净PnL − amount × (open_rate + close_rate) × 0.0005。高成本PnL = native净PnL − amount × (open_rate + close_rate) × (0.001 + 0.0005)，前项为高滑点，后项为相对原费率的增量费用。增量费按原始成交名义计算，fee×slip交叉项明确取0；原native费用仍完整保留。期末force_exit完全同计。仅原ZIP只读会计重计，不再调用策略/回测，不验证成本引发的交易路径变化。现金逐次扣除这些额外费用，若发生负现金则资金容量门失败，不隐式借贷。

BH的500 USDT是含entry费滑点总预算（数量=500/[entry_price×(1+fee+s)]），余500现金；策略500固定stake沿用native原数量，费用可能另占现金，因此两者资金利用略不同，分别报告entry名义与总现金支出。BH出场按原价减exit滑点和费用，无fee×slip交叉项，现金不借贷。

## 值前评价门（均为AND；未知不视为通过）

既有Profile字段取 min_development_trades=12、min_holdout_trades=6、min_profit_factor=1.15、max_drawdown_pct=10。既有 economic_gate 配置为 `{ "name": "PROFILE_DRIVEN_ECONOMIC_GATE_V1", "version": 1, "minimum_net_profit_after_base_fees_pct": 0, "minimum_average_holding_period_minutes": 1440, "maximum_roi_exit_count": 0 }`；源码ROI为空，零阈值按严格正净利润解释，附加门在同一ZIP审计中全部AND判定。

S及D每阶段：

- 基础费后及基准滑点后净利润均严格>0；基准滑点后PF≥1.15；上述高成本敏感性后净利润仍>0。
- 账户DD硬门：native报告账户DD与基准成本后每日close权益DD各≤10%。每日low只报告保守压力指标，不作为新增/替代硬门，不称真实MTM。日初open已退出的仓位不承受此后low；日内stop退出后不再用当日low扣损。对日内止损前是否先到low无法定位时，只报告“假设存续期间到达low”的独立最坏路径压力值，不把它再扣进已包含stop损失的权益。
- 至少12笔完整退出交易（不含期末force_exit），分布在至少3个季度，每个已覆盖季度≥2笔；至少2季度净正；持仓平均≥1440分钟，且≥80%完整交易持仓≥1日。最多60笔/年，超过说明低换手前提不成立。
- 去掉最大单笔盈利后仍净正；最大盈利笔占总正PnL≤35%，最大盈利季度占总正季度PnL≤70%；期末force_exit利润移除后仍净正。零亏损导致PF不可有限估计时标UNDERPOWERED，不拿无穷值当稳健证据。
- 日线次开盘和stop/force_exit语义、订单容量失败、资金不足拒单都需明细解释；出现零时长主导、非预期退出/复用数据/指标非因果则INVALID，不救策略。

12笔是季度重复性底线，不是统计显著性证明；可能仍UNDERPOWERED。S仅探索性通过，不要求S置信下界正，也不据S调参。统计口径唯一固定：E0=1000；每天UTC日终E_t=现金+尚未平仓原amount×当日close，含已发生原费用及已发生增量费/滑点；期末force_exit及其全部成本先入账再记录末日E_t。首日之前E_0=1000且空仓。日收益r_t=(E_t−E_(t−1))/1000，使用固定初始资本，不除以前日权益。季度/月PnL按边界日close权益之差归属，不按出场日期归属整笔盈亏。非环绕moving-block bootstrap：N个r_t，合法起点0至N−10含端点，每次等概率有放回抽ceil(N/10)个完整连续10日块，拼接后截断为前N项，计算算术平均；numpy.random.default_rng(seed=20260906)，10000次；np.quantile(method="linear")取5%/95%为90%双侧区间。只重采统计序列，不生成交易变体。报告约N/10个时段的相关性限制，不能把12笔视为独立证据。D须在上述门外满足其区间下界>0，才申请H。

H尚不执行：同成本/收益/PF/DD门，完整交易≥6且至少3个不同月份有完整退出，至少2月净正；单笔正PnL占比≤50%，去最好一笔及force_exit仍净正，高成本仍正。H同10日block方法90%区间下界>0；D+H完整交易合计≥18，且两阶段各自通过，不能靠合并均值救失败。H只有150日，无法满足即UNDERPOWERED。H/Stress另需用户授权，同research_run_id；上述固定账本成本敏感性不冒充正式Holdout Stress。

现金对照：1000 USDT不计利息，净0。BH对照：相同500初始头寸+500现金、同进出费/滑点、阶段首个可交易open买入至期末卖出，报告净收益与同定义close DD。除严格胜现金，策略须满足「基准净收益≥BH」或「DD≤BH的75%且策略净收益/DD≥BH净收益/DD」之一；DD为0的比率UNKNOWN，不能走比率分支。BH绝不跨S去读D/H。

## 一次采集、一次S与交付

监督已批准工程准备：唯一Issue #87与codex/issue-87-trx-daily-pullback-v1分支、独立DB/Profile及真实Generation。正式冻结账本、数据采集和S仍等待最终绑定确认。当前HEAD与live main均f3ada868；native固定52bc96f4480b1a0da6a9b455bd00b17fbb6786a5，指定venv与显式PYTHONPATH，不修改native/venv。

一次新root采集S+D原始OHLCV（2023-12-22至2026-01-01，共741日，8页×最多100根），D仅producer QC、物理隔离，模型不得看D值；H不采集。公开instrument/market元数据与OHLCV合计最多20次HTTP、15分钟墙钟、零重试/零重采；既有producer按原合同请求，不能拼接或把失败根恢复为成功。完整性/身份失败即BLOCKED_DATA并停止，不计策略失败。公开接口历史可达与上市连续性此时仍UNKNOWN。

真实Generation产出必须与此源码逐字节一致并绑定现有Candidate；不允许Generation自行改规则。Console批准→唯一native S，1 candidate/1 attempt/1 round；经济smoke、提前小窗回测同样占唯一S。静态/合成测试不读取市场，测试仅必要范围。额外覆盖/集中度/统计计算为本次ZIP的只读审计，存existing generation_runs JSON+Git外ZIP/receipt，不新建表/服务/runner；不得让项目基础门先行通过替代全部附加门。

若采集技术失败、S不全门通过或样本不足：保存明确终态/原因，停止，不换币、不改参数、不重跑，无finalist不造ResearchRun。S全门通过才报告监督申请D；D/H持仓和评分独立，同一ResearchRun承接D及获准H/Stress。无Release/交易权限。

源码文件：TrxDailyPullbackV1.py；SHA256=0ca82cbc0f395ff3bb650702b3e70d2be5fc74a3df0376376abf5964d0f3a1d8。已通过当前bounded AST与spot source静态校验，max_lookback=5，startup=10；没有native回测。当前没有设置fast/priority的工具，服务速度层未核定未修改。

## 完整源码

```python
import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy


class TrxDailyPullbackV1(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False
    startup_candle_count = 10
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.08

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["mean5"] = dataframe["close"].rolling(5).mean()
        dataframe["return3"] = dataframe["close"] / dataframe["close"].shift(3) - 1
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["return3"] <= -0.03)
            & (dataframe["close"] < dataframe["mean5"])
            & (dataframe["volume"] > 0),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] >= dataframe["mean5"])
            & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1
        return dataframe
```
