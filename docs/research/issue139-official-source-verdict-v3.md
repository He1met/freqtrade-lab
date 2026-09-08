# Issue139 官方来源有限核验 v3

结论：`BLOCKED_DATA`，停止继续修复当前2021–2023 Binance USDT永续同源路径。此结论只限所核证据链及本次有限官方核验，不证明所有来源不存在，也不是84日动量假说的经济否定。不再重复请求旧失败页面，不提出缺乏新可用性证据的可执行诊断合同。

## 事前预算与实际消耗

监督为本切片另授2次搜索、4次官方页面读取尝试；展开/失败计数。旧v1的7/6超限不变，没有追认扩额。

搜索恰2次：

1. `site.developers.binance.com funding rate history markPrice historical`
2. `site.github.com/binance/binance-public-data fundingRate funding rate data fields`

网页读取恰4次（2026-09-08 UTC）：

| 次序 | 官方目标 | 实际可见证据及限制 |
| --- | --- | --- |
| 1 | [USD-M Funding Rate History文档](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History) | 跳转到综合market-data页，首次输出未展开funding段 |
| 2 | [binance-public-data README](https://github.com/binance/binance-public-data/blob/master/README.md) | 工具返回页面元数据/296行标识，未展示可核对的档案字段正文；不声称读到了schema |
| 3 | [官方仓库Issue44](https://github.com/binance/binance-public-data/issues/44) | 工具返回页面元数据/213行标识；搜索摘要是社区请求线索，不是维护者对历史完整性的承诺 |
| 4 | 对第1页执行find展开 `## Get Funding Rate History` | 读取该节参数、响应字段、示例；按一次页面尝试收费 |

没有追加第五次展开、raw GitHub抓取或其他检索；没有市场API请求、历史档案下载、raw行情读取、付费源、凭据、DB或native。页面响应字节未留存，不编造内容SHA。此文件固定提交保存核验过程，官方页面本身可变。

## 支持边界

[官方Funding Rate History节](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data) 明确 `GET /fapi/v1/fundingRate`，可传symbol与包含端点的startTime/endTime，limit最大1000、按时间升序。响应定义symbol、fundingRate、fundingTime、markPrice、rateType；markPrice语义是特定资金费事件对应的mark。它建立字段语义，**未在本次可见段落建立2021–2023两币字段保留范围、缺失补齐或全历史完整保证**。示例即使含早期时间和非空mark，也不能证明目标区间每个事件均有值。

同页当前mark接口和mark K线定义也未建立小时OHLC与资金费事件关联mark的等价关系；不得用插值/附近小时价替代。官方档案字段及目标历史覆盖本次没有取得可核原文，保留UNKNOWN，不推导“不提供”。因此没有新证据推翻v2绑定的旧1000事件缺mark/ETH未采事实；2023-11之后的完整收据仍不补旧窗口。

## 请求预算措辞更正

v2的122（从零）/88（复用旧BTC小时）是采用最多每小时一条事件等假设的**保守完整请求上界**，不是实际必要数量或下界。上界高于剩49GET，只说明该保守全量预留不能装入当前余额，**不能证明实际采集超过49或不可能完成**。真正阻塞是同事件mark来源未建立；不要以预算算术代替数据结论。原全局请求/字节/时间与96 native余额不变。

## 唯一最小下一研究建议，尚未授权执行

建议监督考虑独立登记的 **BTC/ETH现货 long/flat 动量可行性切片**：正向84日收益持有、否则现金，两个资产都保留，日线决策/下一小时执行、1000USDT和现有成本/风险框架不降低。它与当前双向永续的区别是去掉做空及funding暴露，检验的是现货上涨延续；仍属趋势同族，不是独立新机制，更不是本Issue偷偷改市场身份或将旧策略判为成功。当前永续候选公式、两币、84日与日期不修改。

选择这个建议是为了下一步先解决能否进入最小实验，而不是继续扩展同源修复工程。最小依赖为：先仅核现有登记中两币现货的合法训练域及OHLCV来源合同、历史/现用lot规则与费用适用性；若无合法域或可执行小单则立即停止。现货不需要funding并不证明数据已可用、策略能盈利或交易次数足够。窗口必须由监督另行冻结，不借旧OKX现货保护区或任何已暴露结果充独立确认，不自动采集、写adapter或开新Issue。未来独立资格仍需有依据的统计合同和未消费证据。

若监督不采纳此明确不同的市场/方向假说，当前路径保持阻塞终态即可；不列多个架构备选、不追加平台、不无限循环准入。
