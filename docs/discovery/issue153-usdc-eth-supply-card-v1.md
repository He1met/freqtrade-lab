# Issue153 单链USDC供给与ETH月度关联

**推荐一次小规模开发诊断；PROPOSAL_ONLY。** 同切片完成机制/字段/免费目录核查，未获取市场时间序列或运行实验。main基点99ca7f01ee0676c8ad18c988d713443e0c4ccf5e。

## 问题、机制与局限

Ethereum链USDC供给增长，是否与随后ETH/USDT现货月度成本后收益改善相关？可证伪解释是链上结算/抵押购买力增加与未来风险资产需求相关；这是推论，不能把增发等同资金已买ETH或新美元进入整个市场。单链迁移、赎回、稳定币替代、避险需求和发行库存都可能改变该量，方向与滞后未获证明。

[Fed原始研究2024-02-23](https://www.federalreserve.gov/econres/notes/feds-notes/primary-and-secondary-markets-for-stablecoins-20240223.html)区分一级发行和二级交易，并分析USDC等稳定币的发行/赎回与受压市场。它支撑链上发行有可观察经济内容，也显示一级操作与二级需求并非一一对应；未据其引用文献声称本文月频策略盈利。没有购买稳定币/兑换/套利/多腿；只把公开单链供给作为ETH现货开发输入。

本地去重未发现同题；它不同于151美元融资率、149执行销毁、141/143/145/147价格/风险问题。不承诺全球新颖、因果、超价格信息或统计独立，21月使用已暴露历史须公开。

## 唯一字段与数据路径（已检查静态定义及metadata）

[Coin Metrics Current Supply定义](https://gitbook-docs.coinmetrics.io/network-data/network-data-overview/supply/current-supply)：`SplyCur`是当日账本可见已发行原生单位存量，账户制按余额汇总。它是存量，不是mint交易金额、交易所净流入或扣除发行人库存的自由流通量。

[官方USDC ticker变更公告](https://www.talos.com/insights/usdc-ticker-update-for-network-data-pro-and-atlas)明确USDC从2025-09-08成为受支持链聚合，USDC_ETH保持Ethereum专属。本题固定`usdc_eth`，不读取聚合`usdc`来冒充单链；单链缩减可以是迁往其他链，不能称全体系流出。旧标签及历史重算风险保留。

唯一目录请求：`https://community-api.coinmetrics.io/v4/catalog-v2/asset-metrics?assets=usdc_eth&metrics=SplyCur`。这个catalog-v2入口此前已从官方API文档核实，本轮没有猜数据接口。一次20秒/1MiB/0retry免账户GET返回HTTP200，`asset=usdc_eth, metric=SplyCur, frequency=1d, community=true`，目录范围2018-08-03至2026-09-07。收据见`docs/issue153-catalog-receipt-v1.json`；未访问timeseries。

A开发准入：字段、单链身份、免费日频及覆盖在目录层面具备，足以建议一次受限获取/诊断；不是保证实际响应/完整性。B点时：供应商历史首发/vintage、链重组/回填、实际发布时间UNKNOWN；允许RECONSTRUCTED_EX_POST，不能把当前目录或lag当可交易证明。无需追求完整历史证书后才开发。供给time按官方1d标签的当日存量解释，记录解释及未知，不声称拥有首发时间。历史修订/缺日要留收据，不据回填追认过去可得。

维护与范围：现有HTTP/JSON与单次本地诊断足够，不建节点/数据库/服务/新框架、不新增账户或付费；Community是非商业免费用途，引用来源。风险来自供给代理指标的含义与单链偏差，不是工具运行成本。成本量级每往返约32/64bp（实际用乘法费滑式），月频依然需检验成本覆盖；现金不赚未实际取得的稳定币收益。

## 一次可审查试验草案（未授权执行）

保持研究问题单一：2021-03至2022-11共21个预定开发单元，沿用月8日00UTC决定、01UTC至次月8日01UTC，避免据新输入/输出另选日期。前两个完整UTC日历月均需每天有一个有限正数SplyCur：若任一日缺失/重复/不合法则该信号UNKNOWN。不是从文件行数自定义日历；日链存量应有每天标签，不套美国假日。供给长期不变的合法重复数值不是缺失。

变量固定为前一月末SplyCur/再前一月末SplyCur−1；>0为EXPAND，≤0为OTHER。不是对每一天增长求和；不USD换算/市值归一化/换阈值。时间序列结束标记不等于发布时刻，月8缓冲只设计假设；已知迟发至决定后须UNKNOWN。以最终历史版本开发并保留PIT未知。

唯一建议获取目标：`https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=usdc_eth&metrics=SplyCur&frequency=1d&start_time=2021-01-01&end_time=2022-10-31&page_size=10000`。使用此前官方API已读的参数/接口形式，不是本轮实测请求。预期JSON data各行asset/time/SplyCur；具体数值类型可用明确有限数值转Decimal并合成验证，不隐式多字段兜底。若接口边界少一天、多日/错误身份/分页或非JSON，不追加请求；缺少的输入月份UNKNOWN，错误资产/根本结构不符则BLOCKED_DATA。本次**不执行该URL**。

一次获取上限20秒/1MiB/0retry/不跟重定向，0新cryptoGET；响应SHA/URL/首次接收时间及未知保存在Git外。通过后原39源中仅ETHUSDT 1h，价格解析范围2021-03-08 00至2022-12-08 01UTC含退出开价，SHA及旧异常inventory预后核验，持有小时任一缺/短整月UNKNOWN，退出只需正开价。一个worker180秒、一次invocation、21units、0retry；无native/global写/钱包。域已暴露，不能挪用封存/forward。

所有21月各做相同1quote假想ETH往返。原base fee=.001/slippage=.0006，stress .002/.0012，净值倍率(Pout/Pin)*(1-s)/(1+s)*(1-f)^2；两组不是不同交易资产。报告全部输入/组别/未知理由/毛净，组n、均值中位数/正数、最大月绝对贡献，组差EXPAND−OTHER。任一组有效<5优先UNDERPOWERED，不延窗；否则任一成本差≤0为STOP_RULE_NOT_SUPPORTED；方向成立但任一EXPAND净均值≤0为NO_LONG_COST_SUPPORT；否则仅EXPOSED_DEVELOPMENT_ASSOCIATION。即使过门也不声称功效、因果/独立或钱包资格。供给增长可能占绝大多数月份，组不足是可接受终态，不能改阈值凑组。

## 本轮收束和记账

授权151#issuecomment-5584882594，12:07UTC起，实际3搜索/6页面尝试：Current Supply、Fed研究、API页两次错误、FAQ路径已移动、官方USDC标签公告。旧FAQ搜索摘要仅辅助定位，不视作成功读正文；失败计预算，未继续追页或执行网页指令。查询是CM供给字段、Fed发行需求研究、CM USDC聚合语义。

新增1次Coin Metrics catalog metadata，0时间序列/行情GET、0统计/代码实现/native/global写。累计Coin Metrics metadata2、EFFR macro1、原crypto112/native32，各自独立不重置。无新市场结果，forward/manifest/global/grant保持不变。

只交这一推荐供监督一次决定是否冻结并执行上述获取/诊断；无需追加纯文档卡。若不接受单链供给代理的识别局限，则停止此问题，不改为全链汇总、另一个稳定币、付费标签或发行事件巡搜。
