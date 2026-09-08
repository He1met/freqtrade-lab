# ISSUE139_SPOT_TSMOM84_V1 — 现货实验合同草案

2026-09-08；上一固定HEAD489433761c68ccef02310551f96ba5cd07c67cbe。本合同是唯一当前现货草案，待监督固定包准入；不是可立即运行的启动manifest。原永续2021–2023路径BLOCKED_DATA并停止同源补救，原文件/账本不改；新假说是现货上涨延续、负方向现金，不含做空及funding。仍属于趋势同族，不与永续结果计作独立重复证据。API137/138暂停。

## 信号、资金、风险

交易所Binance，市场SPOT，BTC/USDT和ETH/USDT，1x，无借贷/质押/现金利息。设计初始共享资金1000USDT。唯一参数84：UTC已闭市日t，`close[t]/close[t-84]-1 > 0` 时long，否则flat。t时冻结方向/ATR/数量上界，最早t+1小时open成交，缺日线不填补，不同close成交。正方向持续时不加仓；3*ATR20固定入场止损或84日持仓上限触发出场，之后等一次非正再转正才重入，不用重复重开制造样本。ATR为过去20个完整日true range均值。止损按已完成小时OHLC/当前已知open观察，下一小时执行，不假设触价成交。

用户明确目标：成本后净不亏、最大DD20%。其余来自旧监督采纳的设计框架：总名义<=80%净值，每币<=40%，A入场止损风险<=1%，B/C每币<=0.5%；10%DD锁存半风险，15%锁存停止新风险，不重置峰值、不经济重启。DD>20%判风险失败，不承诺连续价格覆盖或瞬时止损。数量向下取满足全部step的网格，不加杠杆/本金，不凑最小单。卖出不得超过实际可用币，无法合法清仓保留dust/实际持仓并标记不完整，不能伪造全现金。

B是同一84日规则两币共享钱包；同时入场按相同比例下调到共享现金/风险上限，再各自向下量化，不把A净值相加。A-BTC与A-ETH各自1000仅解释性对照。C仅减少B风险，逐币因子 `min(1, prior252个sigma20中位数/当日已知sigma20)`，持仓期间不增量；half-B固定半风险。C所需至少273闭市日warmup，故不为了减少数据量砍依赖。

## 官方核验、费用和订单规则

新预算实际2/2搜索、4/4页面读取，旧7/6超限记录不变。查询为 `site.binance.com spot trading fee regular user 0.1000%`、`site.developers.binance.com docs binance-spot-api-docs filters LOT_SIZE MIN_NOTIONAL klines`。以下四个页面各读取一次，无展开追加：

1. [官方费率表](https://www.binance.com/en/fee/trading)：Regular User maker/taker为0.100%/0.100%。因此base每边fee10bp+slip6bp，往返32bp；stress每边fee20bp+slip12bp，往返64bp。不给BNB、VIP、促销折扣；适用费率后来证实更高则评分前换版提高。这是公开保守设计假设，不是账户费率/历史真实费率证明。
2. [官方filters原文](https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/filters.md)：数量受LOT_SIZE/MARKET_LOT_SIZE限制，价格受PRICE_FILTER等约束，MIN_NOTIONAL/NOTIONAL可作用于market单。其参考价可能是专用reference或此前均价；小时open不能证明真实订单通过全部动态规则。字段示例不能当BTC/ETH参数。
3. [官方REST原文](https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/rest-api.md)：本次工具返回目录/页面标识，包括Exchange Information与Kline接口；未完整展开参数段，参数上限/历史全覆盖不冒充本轮逐项核实。下述精确请求为待审核拟议合同，响应必须完整通过预定覆盖检查，否则停止，不能临时增加页数。
4. [官方现货手续费FAQ](https://www.binance.com/en-NZ/support/faq/detail/e85d6e703b874674840122196b89780a)：返回页面元数据，正文细节未完整展示；不据此声称核实实际扣费币种/舍入规则。

拟议模拟会计：买入成交数量扣base币手续费后作为实际库存；卖出按实际成交币量扣quote手续费；不得又重复扣等价quote费。slip直接不利调整买卖成交价。手续费扣币及舍入需要adapter固定模型、明确披露不是已验证真实账户结算；真实精度误差、历史filters、动态参考价、地区/账户资格UNKNOWN。只输出模型路径，不认证真实可交易性/PnL下界。采集现用exchangeInfo后才有BTC/ETH具体lot/tick；旧永续50/20USDT值禁止复用。funding在现货无借贷合同中为NOT_APPLICABLE，区别于缺数据填0。

## 训练区间：具体域判定与暴露

唯一拟议训练 `[2021-01-01T00:00:00Z,2023-01-01T00:00:00Z)`；warmup `[2020-04-02T00:00:00Z,2021-01-01T00:00:00Z)`。范围不改成另一个日期凑数据，训练730日，warmup274日；只作EXPLORATORY_EXPOSED_TRAINING，不具独立性。

实时控制账本SHA `692c595eb32e928332d4d7759aabcf726e28f1d5ddda07a74a2a5a3a420d7439`。核对旧59/63 master合同原文：2020-v2 SHA `57a2b350bf240d7769b56f28347802747f85273b511cc2e9056c22f1f567ffc7`；2022-v1 SHA `a36c2598fead6e2cfeef3ac7bc7c578166beb1185caacb814090767206cd90a7`，均指定OKX两币。旧scope snapshot明示EXACT_DOMAIN OKX SPOT，2021与2023 Development仍保护。依据身份匹配，**本Binance SPOT候选与这些具名源不相同**；这是本轮适用同一scope规则的结论，不把过去仅针对perp的准入冒充现货授权。旧68不用于解除任何保护。

已核元数据中没有本候选Binance SPOT同区间明确冲突；2025全局、2026具名和旧perp sealed不重叠。宏观/跨交易所历史暴露仍披露，不能因为换venue宣称独立。当前没有本现货登记；监督需确认上述EXACT_DOMAIN解释并先登记新用途/合同SHA，再有任何市场读取。若scope被判更宽则冲突为旧63的2021范围，明确BLOCKED_CONTROL，不自行改日历。旧OKX原始文件、所有sealed行情均未读取。

## 精确拟议采集，当前授权0

为避免多余小时warmup，warmup取日线、评分期取小时线再因果聚合；不取funding/mark/档案。这改变数据分辨率用途，不缩短信号依赖。拟议单worker，仅HTTPS GET `https://api.binance.com`，无签名/key/redirect/retry，请求间隔>=1秒，单请求<=20秒。响应先按字节上限收费，失败不退已用预算；每次请求前复核登记/控制SHA，所有响应Git外保存及SHA。

| 步骤 | endpoint与参数 | 页数上限 |
| --- | --- | ---: |
| 1 | `/api/v3/exchangeInfo?symbols=["BTCUSDT","ETHUSDT"]`（标准URL编码），身份必须SPOT/TRADING/USDT，两币均存在 | 1 |
| 2–3 | 每币`/api/v3/klines?symbol=S&interval=1d&startTime=1585785600000&endTime=1609459199999&limit=1000` | 各1 |
| 4–39 | 每币`/api/v3/klines?symbol=S&interval=1h&startTime=cursor&endTime=1672531199999&limit=1000`；初cursor1609459200000，随后上一页最后openTime+3600000 | 各18 |

主机/路径/参数即以上白名单，不能用uiKlines。请求limit1000为拟议分页值；不接受隐式默认或服务端截断导致覆盖遗漏。每币精确274日warmup及17520小时评分；时间UTC、严格有序唯一、每行开闭界及正OHLC合法、小时汇日24根完整。第18小时页应只有剩余520根；若较早短页、字段缺失、缺口、乱序、越界、HTTP非200/429/418、响应超限、未知filter/身份或预算漂移，立即终止BLOCKED_DATA/CONTROL，不请求补页或换窗。日线volume及quote volume定义保持原样；不能将warmup计入收益。

拟议新<=39GET、总<=16MiB、单<=1MiB、活跃<=900秒、单请求<=20秒、retry0；最后未读满的响应也不得放松上限。全球累计原73+39<=112/122，余10GET；bytes最多14603929+16777216=31381145<67108864，活跃保守130+35.759+900<1800。父V2自身18剩余不是新段授权；新现货段需监督允许占用原全球余额，旧账本字节不改，不能重启V2。39是完整设计上限而非实际请求保证；一页失败立即止损。没有自动续接/二次root/新预算重置。

## 逐调用与继续规则

均使用一次训练折及同一固定数据绑定、分别独立运行；base/stress不得后处理拼成另外模型。key前缀 `ISSUE139_SPOT_TSMOM84_V1/train-2021-2023/`：

| 顺序及key尾部 | pair | 次数 | 费用/边、滑点/边 |
| --- | --- | ---: | --- |
| B/base, B/stress | BTC+ETH共享钱包 | 2 | 10/6bp；20/12bp |
| A-BTC/base, A-BTC/stress | BTC | 2 | 同上 |
| A-ETH/base, A-ETH/stress | ETH | 2 | 同上 |
| C/base, C/stress | BTC+ETH共享钱包 | 2 | 同上，条件进入 |
| half-B/base, half-B/stress | BTC+ETH共享钱包 | 2 | 同上，条件进入 |

B先行。B有效但净亏保留训练负路径；A不删币、不否决B，只解释。共享技术/模型/完整性缺陷停止依赖调用；模式风险失败记录该模式，不能冒充其他模式失败。只有B base和stress都成本后>=0、DD<=20%、两币有合法完成自然episode且非全现金/零成交、无来源/执行未决项时，才允许同一次已授权批次继续C及half-B；这只是继续诊断依据，不是样本资格门或新finalist。否则不花这4次条件槽，不改参数救结果。A经济亏损不改变该规则。

全球 `28已占+10旧sealed+10本草案+48未分配=96`，失败/重试无新免费槽，本轮占槽0。前向0，训练不足直接UNDERPOWERED，不固定三年、不以84回看等同统计依赖。所有自然episode、同期相关性、成本、dust/拒单、净值与DD一起报告；非负训练不取得独立资格。

## 实际入口与最小缺口

已读 `scripts/run_freqtrade_backtest.py`：当前market allowlist无Binance SPOT，且只允许单pair/5m或1d，不能直接运行本B。`scripts/run_portfolio_observed.py` 已有单策略两币共享账户、离线Binance native、网络拒绝、预算/超时和artifact收据；这是拟复用的执行骨架，但当前绑定perp及observed funding模型，不是现成spot入口。`lab/portfolio_causal.py` 也是旧突破信号，不含本84收益sign。

下一工程仅在本固定合同准入后：给上述共享账户骨架增加明确spot合同分支/long-flat信号及base库存扣费，绑定无funding数据和现货market snapshot，禁止借贷/short；不去扩展单pair通用runner或数据库。collector仅需本39GET白名单/双分辨率覆盖的小入口，不能调用旧fapi硬绑定收集器。实现验证只需合成因果时序、现金库存/fee与lot不足失败、网络拒绝/超额先拒绝、B单钱包和条件C门；无需新表/服务/API平台。

最小下一步是监督对现货身份/区间解释、公开费率和拟议采集及模拟执行边界的固定包裁定，然后才可做有界数据+必要薄实现。当前真实行情完整性、spot filters、实际stake容量、样本及PnL均UNKNOWN；无raw/DB/市场请求/native/付费API。交付为这一份合同，不增加文档架构层。
