# NEXT_MECHANISM_DISCOVERY_V1 — 只读选型结论

状态：**DESIGN_READY_FOR_SUPERVISOR**。推荐方向为 **LINK_TAKER_ABSORPTION_5M_V1**，但当前 **不可批准直接 Search**：原生功能存在，Lab 接入未完成，档案内容及经济假设尚未验证。建议先决定是否值得一项有上限的原生接入 Gate；不以寻找策略为由无限开发。

本轮 worktree 干净，HEAD 与实时 main 均为 `dc82c61fe8a27a654977344755c088412518d858`；#65 已 CLOSED / DEVELOPMENT_REJECTED，#62 OPEN 不动。简单双均线、旧 ETH 五日反转，以及持久归档中的 XRP 单根/量价反转、AVAX 区间扩张延续均保留负面终态。

| 比较的机制 | 信息、理论与可执行性判断 |
|---|---|
| 高相对成交量后的价格恢复 | 无符号 OHLCV；[Campbell/Grossman/Wang](https://www.nber.org/papers/w4193)提供流动性压力解释，但旧 XRP 已测试单根反转与 volume-shock 增量。日线/阈值替换不能冒充新机制，淘汰。短持仓费用敏感，容量未知。 |
| **主动卖出占优但价格转涨的承接** | 使用真实 taker side，区别于旧 signed range-volume 蜡烛代理。单资产、5m、一根正常持仓；原生可以聚合 trades。它是可证伪的薄弱假设：主动卖压没有压低价格，可能表示被动需求，下一根仍能否延续未知。[Cont等](https://arxiv.org/abs/1011.6402)研究股票短时同时间冲击，**既不证明次根预测，也不是本提案的成交不平衡指标**；订单簿 OFI 含挂撤单，本提案没有。费用/滑点很敏感，必须接受负终态。 |
| 外部关注度冲击 | [Liu/Tsyvinski](https://www.nber.org/papers/w24877)报告关注度的预测关联，信息与 OHLCV 不同；但 LINK 历史 point-in-time 指数、修订及发布时间均未证实。预计日/周尺度，样本更少；需另一套数据接入。本轮不选。 |

数据可得性：OKX [history-trades](https://www.okx.com/docs-v5/en/#order-book-trading-market-data-get-trades-history)只支持最近三个月；[官方历史页面](https://www.okx.com/en-gb/historical-data)另列自 2021-09 起逐笔档案。本轮目录确实列出 LINK 2024-01—2026-01 共25月（约1621.28 MB压缩），不是已验收数据。API文档明确 side 为 taker、sz 在SWAP是合约数、ts是成交毫秒；档案UI列 side/created_time，**档案字段的实际语义、连续性及值仍 UNKNOWN**。

原生执行：固定 Freqtrade 2026.7/`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5` 干净。[`use_public_trades`、`--dl-trades`](https://www.freqtrade.io/en/stable/advanced-orderflow/)及离线 trades 加载已存在；源码 bid=sum(sell amount)、ask=sum(buy amount)。不造 runner、撮合或外部聚合替代原生。需要 Lab 源/消费验证、配置和 AST 的窄接入。默认 max_candles=1500 只覆盖尾部，且保存逐笔字典和 footprint；一到两个月也必须实测资源，不能称轻量已证实。

标的：AVAX 已排除。当前持久归档证实旧 Search 为 [2026-07-31,2026-08-30)，原始暴露从2026-06-30 22:00起，拟H包含旧源范围及Search末2小时预热；记忆中的七月Search日期不准确。监督在未读新价格前授权唯一改选 LINK；其 linear/live、2020-02-28上市已核对。109条近期消费元数据加旧77条ledger没有LINK记录；GitHub文本命中只是普通“link”。范围外未登记运行仍 UNKNOWN，不能宣称全球未消费。

下一 Gate：仅在监督接受假设强度、以下窄扩展及资源上限后，才新建唯一 Issue 预注册；本轮停止。未创建Issue/Profile/DB/Candidate，未读新价格、flow、funding、H/Stress，未跑实验、未改业务代码。论文只能提供研究动机；[Hudson/Urquhart](https://link.springer.com/article/10.1007/s10479-019-03357-1)的样本外与多重检验讨论也不验证LINK或以下参数。Anghel论文官方正文不可访问，本轮不依赖其全文结论。

---

## 拟冻结合同（尚未获准实施）

- 标识：`LINK_TAKER_ABSORPTION_5M_V1`；pair `LINK/USDT:USDT` / `LINK-USDT-SWAP`，OKX futures/isolated，long-only，1x，wallet1000、stake100、maxopen1，每边fee0.0005、actual native funding、slippage UNKNOWN、minimal_roi={}、ROI退出0、stoploss=-0.03。不调上述参数。
- **尺度与窗口提案**：日线缺少预测尺度支持，故不采用两年日线方案。5m仅是接近短时微观结构的操作化假设，仍不是论文复现。Search [2024-02-01,2024-03-01)；唯一Dev [2024-03-01,2024-04-01)；H/Stress [2024-04-01,2024-05-01)，UTC、左闭右开，完全封存。pre-roll=288根/1天，source起点2024-01-31 00:00，startup=30。Search输入8640根、Dev输入9216根（均含pre-roll），真实评价机会8352/8928根。缩短窗口在任何新行情前提出，目的是限制逐笔资源及保持一bar尺度，不因结果改窗；监督尚未批准该日历。
- **R1 对照**：t收盘，C[t]>C[t-1] 且 C[t-1]<=C[t-2] 且 volume[t]>0 时 enter_long=1。它只是价格转涨对照，不作为新的动量发现。exit_long[t]=1 当原始 enter_long[t-1]=1。
- **R2 唯一信息增量**：完全相同，唯独入场还需 bid[t]/(bid[t]+ask[t])>=0.60。bid/ask必须来自已闭合t内全部真实主动成交；数据门事先保证总量>0、有限且无缺失。缺失不填0、不从蜡烛方向猜side、不丢弃不利成交。
- **实际时序**：原生整体shift1使t信号在t+1开盘进，t+1的退出信号在t+2开盘出，正常持仓5分钟。R1触发不可能相邻两根同时真：t真意味着C[t]>C[t-1]，而t+1真反要求C[t]<=C[t-1]；R2是其子集。因此不能被相邻enter/exit冲突拖成多bar。stop_loss、窗口末force_exit保留；必须用原生实际逐笔验证，当前仅源码/逻辑证据。不得为过Gate强制延长持仓。
- **冻结 Gate**：每次Search和Dev独立要求至少30笔、net>0、净收益>=1.25%（分母wallet）、PF>=1.10、DD<=15%、平均真实持仓>=5分钟、ROI退出0，门槛字段UNKNOWN失败。平均5分钟是对“一bar正常周期”的严格检查，提前stop/force_exit可能导致失败，不能结果后放宽。高频信号有数千决策点，30只是筛选底线而非统计功效；实际事件量未知，少于30即样本不足。0.1%往返费（约每100USDT仓位0.10USDT）已是强负担，slippage未建模不等于0。
- **预算/选择**：最多2次真实Search，R1技术VALID则R2必跑；不额外预筛。保持原生 net desc / DD asc / candidate_id asc 排名及唯一finalist。只有原生唯一finalist为R2、通过全Gate、且R2净收益严格高于R1，才最多1次Dev；R1胜出或仅tie时可保留原生终态但研究增量为“不支持”，不冒称NO_FINALIST，也不把纯价格对照继续当新机制。Dev失败即终止；通过才等待用户一次性H/Stress授权。H拟最低30笔、Stress fee×2，均只登记，不执行。
- **数据 Gate 优先**：官方逐笔档案完整列名/类型/side语义、instrument、ID去重、timestamp先筛选、时区/区间/闭合、数量单位、selected行有限正量、与原生OHLCV成交量的同单位对账、无缺月/截断、源/转换文件SHA；流数据严格隔离Search/Dev/H。目录25月可列不替代内容检验。UTF/压缩边界和UTC+8跨月文件先按时间筛选，绝不解释边界后的受保护价格或flow。价格/mark/funding沿当前生产消费合同，funding exact-zero 8h完整性失败即停；不得弱化旧#62容差或用最近三个月API冒充2024档案。
- **原生配置拟值**：exchange.use_public_trades=true；orderflow.max_candles=10000（覆盖完整单窗加warmup）；cache_size=1000、scale=0.01、stacked_imbalance_range=3、imbalance_volume=1、imbalance_ratio=3；只使用bid/ask总量，footprint参数不是搜索因素。这些是原生既有内部设置，不新增Lab缓存/服务。应验证每根有效窗都有flow，不能默认tail过滤安全。
- **资源/停止**：Jan—Apr2024目录约172.95MB压缩，实际下载内容及解压峰值未知；Apr只有UTC边界所需selected前缀可读。拟给单次引擎15分钟、peak RSS8GiB上限（须确认已有受控执行器能落实）；数据或技术失败立即停止不重试/换标的/换窗/补第三次。跨币同日历和累积多轮选择不构成独立统计重复，基础Gate通过也不证明显著性。

## 最小能力差距及投入边界

**提交监督的当前决策：推荐先做下面G1小Gate；不推荐现在批准完整接入或正式真实策略回测。** 理由是目录与原生组件已有具体证据，少量检查可以低成本否定不可用的数据/执行路径；预测优势仍薄弱，不值得越过此门直接投入开发。

| 分段 | 精确范围与停止条件 | 估时及授权状态 |
|---|---|---|
| G1 小数据与原生兼容 Gate | 如获监督另行授权，先在唯一Issue冻结G1范围与SHA，再只获取官方2024-01 LINK逐笔档案一份（目录40.03MB），只解释2024-01-30 UTC的行作为格式兼容样本。该日位于正式pre-roll之前且避开UTC+8月档尾界，不属于Search评价。整份原始档案曝光范围及selected语义消费范围分别登记，不能以后冒充未暴露资料。不获取Search/Dev/H或funding。核对列名、side、时间/单位及原生trade格式；在Git外用极小合成trades/蜡烛验证原生bid/ask、tail覆盖和互斥信号的一bar时序，不用真实行情计算策略收益。不写Lab业务代码、Profile/DB/Candidate，不建runner或修改引擎。任一格式/隔离/兼容失败即停，不能换日、换币、换源或追加真实试跑。 | 活跃工作硬上限半天（4小时）；单次下载超15分钟或合成执行超5分钟、peak RSS超2GiB则停止，未能落实这些边界也停止。当前仅提案，尚未授权执行。 |
| G2 最小Lab接入 | 仅G1通过且监督再次明确批准后，才处理下面第2项配置/provenance/AST/单因素接入；六表不变，不增加服务或自制撮合。G1通过仅表示可进入范围决策，不自动授权G2。 | 约1—2天；超过两天或需改原生引擎则停止回监督。当前不批准、不实施。 |
| G3 有限研究 | 仅接入验收完成、精确最终契约及远端Issue/SHA在事前冻结后，才按本文最多2Search/1Dev执行。G1/G2的合成结果没有经济含义。 | 真实下载/执行时间UNKNOWN，受本文资源上限约束。当前不批准、不实施。 |

G1交付只需一份小receipt：档案/selected范围、SHA、格式/方向/时间核对、原生合成结果、资源实测和未解问题。失败为具体BLOCKED_DATA/BLOCKED_CAPABILITY；通过只称“小Gate通过，等待G2范围决定”，不得称策略可行、数据全窗PASS或研究已启动。真实源内容、全窗完整性、执行性能等现阶段UNKNOWN保持原样。

1. **数据先行**：把官方档案的真实trade映射到原生 trades schema/handler，并验证完整性与side/timestamp，绑定现有JSON provenance。不能改原生撮合、伪造OHLCV volume或写自制回测。原生 --dl-trades 存在并不解除OKX三个月API限制；2024数据必须有档案入口。合约数量与原生amount的换算须对账。
2. **Lab窄接入**：源/consumer允许且校验一项trade文件类别与既有orderflow配置；AST只在有完整trade合同的profile允许原生bid/ask数字列；R2 verifier只增加精确定义的单个taker_sell_absorption_60_v1条件（并保留相同退出引用），禁止任意新表达式/读取文件。六张业务表不加字段/索引，使用既有JSON字段。安全隔离/生成模板/实际Candidate hash一并绑定。
3. **先合成后真实**：几条方向相反的synthetic trades检验原生bid/ask/UTC分桶、max_candles覆盖、非相邻触发与一bar进出、越界/缺失失败；不用新价格作smoke。本阶段未运行这些。随后只有冻结R1承担首个真实兼容性执行。
4. **成本预估**：数据合同与方向/单位离线验证约半天，窄接入与针对性测试约1—2天；这是条件估计，尚未bench。真实下载/单次引擎耗时UNKNOWN，受上述硬预算约束。若需要修改Freqtrade引擎、通用订单流平台，或两天内仍不能证明闭合输入/隔离，停止并回监督，不扩为无限项目。日线预测优势无足够证据，本提案只值得一项有界信息试验，不建议现在直接投入完整研究运行。

## 静态源检查证据

仅在内存中调用现有validator/单因素函数，没有创建Candidate或运行策略。

- R1：ACCEPTED，max_lookback=4，SHA256 2f53392a04fea4e1131742cadcd5c24b8c4fbe62de79b16a18da16c79ed90640
- R2：REJECTED / UNBOUND_DATAFRAME_COLUMN（bid未绑定），SHA256 89bf87f7a20e8362ad7e538cdb8d5f63d68ab145b3d4454763995eef4a9ae917
- 当前原生Lab单因素verifier：false。因此**当前代码不接受整个研究合同**，不能给出虚假的“零工程可跑”结论。

R1精确参考文本：
```python
import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy

class LinkTakerAbsorptionControlR1(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = False
    startup_candle_count = 30
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.03

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["prior_close"] = dataframe["close"].shift(1)
        dataframe["prior_close_2"] = dataframe["close"].shift(2)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe["close"] > dataframe["prior_close"]) & (dataframe["prior_close"] <= dataframe["prior_close_2"]) & (dataframe["volume"] > 0), "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["enter_long"].shift(1) > 0, "exit_long"] = 1
        return dataframe
```

R2精确参考文本：
```python
import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib
from freqtrade.strategy import IStrategy

class LinkTakerAbsorptionR2(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = False
    startup_candle_count = 30
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -0.03

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["prior_close"] = dataframe["close"].shift(1)
        dataframe["prior_close_2"] = dataframe["close"].shift(2)
        dataframe["sell_share"] = dataframe["bid"] / (dataframe["bid"] + dataframe["ask"])
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe["close"] > dataframe["prior_close"]) & (dataframe["prior_close"] <= dataframe["prior_close_2"]) & (dataframe["volume"] > 0) & (dataframe["sell_share"] >= 0.60), "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["enter_long"].shift(1) > 0, "exit_long"] = 1
        return dataframe
```

## 本轮可复用证据

- [消费元数据及目录响应](consumption-metadata.json)：引用#63/#64/#65旧小索引；增补#65的11项元数据，以及现存旧AVAX/XRP prereg、source、search及terminal。没有全量扫描/重新hash行情。
- 旧持久归档：`/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902`。
- AVAX prereg SHA `df480c586191baa3120f32fcc52e3a14b2aa3ec867176042ed6273902a6ee0e1`；source provenance `970d3bb757d8c58149b24f66203d2533f03404b7b9cfed26d5309b89151147d4`；Search provenance `d84fc38a1ba35329ac5e74a70f589ff5428941d5ecec248dccccb1bbeeda5fed`；terminal `f0cd3a4a47e0142208904dc4aa5b3c1c26d70a528c5257c1ec232a64cfc50f98`。
- #65报告及final-audit SHA与监督给定值一致，远端关闭已实时确认。
- 目录曾因日期参数超过六个月返回50077，修正为UI的UTC+8月首选择后取得25月清单；这是未冻结设计阶段的元数据查询纠正，零ZIP下载。首个成功六个月响应未保留原始body SHA，明确UNKNOWN；后续四响应SHA存入索引。
- 执行threadId=`01a06e51-9548-70e3-8933-c5a8b86a879e`；cwd=`/Users/shenjianpeng/.codex/worktrees/dfd5/freqtrade-lab`；模型/effort遵循任务gpt-6-astra/high；实际service_tier API未暴露=UNKNOWN，未改全局配置。
