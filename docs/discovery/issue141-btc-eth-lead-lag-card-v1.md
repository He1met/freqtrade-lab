# Issue141：BTC→ETH小时级信息扩散机制卡

唯一判定：`UNKNOWN — INSUFFICIENT_READABLE_TARGET_EVIDENCE`。当前不推进市场探索或实现，但没有证伪所有BTC→ETH条件优势。本次目标域论文正文不可读；唯一可读正文的主要对象是跨市场BTC、亚秒级微观结构，不能据此支持单一Binance现货、小时信号、下一小时执行的两币多头。不会为这个未知优势建低延迟平台。

[Issue141事前合同](https://github.com/He1met/freqtrade-lab/issues/141)：2026-09-08 09:58UTC起30分钟，最多3搜索+6原作者/原始论文/官方页面读取尝试。实际3搜索、6读取（1正文成功、5失败），约5分钟内停止。失败包括访问限制和安全拒绝，没有绕过或额外补抓。搜索的摘要/片段只定位研究，不升级为正文结果。

## 去重及经济问题

已只读核repo状态、同范围Issue及现有机制卡。Issue137是通用发现工程，不匹配本域；Issue139是固定前向观察，另有反转、跨场所、日历卡。本次创建独立Issue141，仅在原worktree新建 `codex/btc-eth-lead-lag-discovery` 分支，无pull/rebase或冻结文件修改。

与B自身84日收益不同，这里问的是另一资产的已完成价格变化是否包含目标资产自身历史以外的信息。与旧反转不同，它不必反向买入本资产；与跨场所卡不同，不是同一资产两处价格收敛；与日历卡不同，不由固定时钟触发。但如果仅用BTC上涨作为ETH多头市场方向过滤，仍可能只是共同动量/市场暴露，不能自动称独立或互补。

可能的经济摩擦是注意力分配、交易者分群或调整成本：共同信息先在一币形成价格，另一币延迟反应。这只是解释假说。BTC规模或关注度较高不能推出它每次领先，也不能推出延迟持续到下一小时。资金轮动还可能产生相反符号；不能看本项目行情再选择先后方向。方向、预测对象和延迟应在任何未来读取前固定，不用结果决定叙事。不要求完美知道交易者动机，允许概率性条件；当前缺的是可读、相关的证据与可检验条件。

## 原始来源及可读性

唯一可读：[Albers、Cucuringu、Howison、Shestopaloff（2021），Fragmentation, Price Formation, and Cross-Impact in Bitcoin Markets](https://arxiv.org/pdf/2108.09750)。已读正文§1–2前部（PDF页2–6），未逐页审计62页。正文研究交易场所碎片化、BTC市场间传递及微观特征；交易费用影响预测转成策略的结果，高taker费市场的策略表现较弱。其跨场所背景及亚秒级对象与本域不同。**本卡判断**：这是“时间尺度/成本不能跳过”的边界证据，不是BTC→ETH小时优势证据；未读后部的样本外、延迟或实盘数值不在本卡宣称。

其余原始候选：

|研究|读取情况|本卡可作何种使用|
|---|---|---|
|Sifat等（2019），[Lead-Lag relationship between Bitcoin and Ethereum](https://www.sciencedirect.com/science/article/pii/S0275531919300522)|出版页403；[作者机构PDF](https://irep.iium.edu.my/73405/1/Imtiaz%2C%20Azhar%2C%20Syazwan%20%282019%29%20RIBAF.pdf)安全拒绝，未尝试绕过|找到直接相关小时/日级文献线索，但完整方法、结论、同步处理、成本、样本外均未核；不能凭摘要宣告可交易或无效。|
|Jia等，[*A Seesaw Effect*作者稿](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID4458636_code2728738.pdf?abstractid=3465924&mirid=1&type=2)|403|摘要方向与单向扩散叙事可能不同；实际币种组合、持有期、费用与样本外UNKNOWN，不用声称利润。|
|[Bitcoin, Ethereum, and the Ambiguity of Price Discovery](https://www.mdpi.com/1911-8074/19/9/678)|429|没有正文或当前可核发表内容；滚动指标、极端事件局部投影及是否可交易均UNKNOWN。|
|[Cross-cryptocurrency return predictability](https://www.sciencedirect.com/science/article/pii/S0165188924000551)|403|未核正文；搜索中的Binance/分钟级及收益描述不构成本目标策略的证据。|

因此不把论文标题里的“小时”、搜索中的“显著利润”，或Granger/相关性字样当作已通过本范围经济检验；也不把5次不可读当作5个负结果。

## 小时源、时间因果与成本边界

下列为设计审查，不是执行授权：

- 若未来研究的是**已闭BTC小时变化预测后续ETH收益**，同场所两币小时OHLC在字段层面可以构造基础条件，未必需要订单簿。但小时源无法证明小时内谁先动、排除所有异步末笔成交、验证报价响应或发现亚秒级优势。不能因粒度不够就悄悄升级平台。
- 必须以两币共同已闭时间段定义输入，保留缺口，不把某币旧价前填造成的假滞后当信号。同timestamp也不等于同一时刻成交；同步价格受共同信息驱动，可能没有任何剩余可交易延迟。
- 必须将信号已可得、决策完成、下一小时可执行价格分开；时间段标签不能把ETH已发生变化挪到未来。若信息在本小时内完成传递，下一小时入场就已错过。现在B日后收件的前向包不是这条策略的实时入口，不能改label复用。
- 样本内统计显著不足以说明扣费优势。应问BTC变量相对ETH自身信息是否增加预测/经济价值，方向和时窗是否事前固定、样本外是否保持、成本及延迟是否抹掉效果。本次未算任何统计，不新增阈值或样本门。
- 已有设计参考每边base16bp/stress32bp，往返线性约32/64bp，不是账户实测费率。没有正文确认本目标规则可执行收益幅度，故无法做有效的净收益比较。1000 USDT本金不降低百分比成本；最小单、仓位、退出及dust仍未验证。

当前不提供伪装成有证据的参数规则，也不申请新窗口。可以改变本判定的信息是：可核正文确实覆盖目标时间尺度，说明异步/延迟处理与可得性，并支持某个可因果定义的条件，且成本后或明确收益幅度足以支撑小规模探索。无需事先证明确定盈利；但不能仅凭亚秒论文或摘要就启动行情试验。是否再给文献可读性复核预算由监督裁定，不自动重试或转新域。

## 全部尝试账

|序号|操作|结果|
|---|---|---|
|Q1|`Bitcoin Ethereum lead lag hourly trading transaction costs out of sample paper`，限定arxiv.org/ssrn.com/sciencedirect.com/edu|完成。|
|R1|Sifat ScienceDirect上列URL|403，计1。|
|R2|Seesaw SSRN上列URL|403，计1。|
|R3|`https://arxiv.org/pdf/2108.09750`|62页文本返回，阅读正文前部，计1。|
|Q2|`"A seesaw effect" Jia Wu Yan pdf`|完成，与Q3在同一工具请求内，但各计1搜索。|
|Q3|`"Lead-Lag relationship between Bitcoin and Ethereum" pdf Sifat`|完成。|
|R4|Sifat机构PDF上列URL|non-retryable安全拒绝，计1。|
|R5|MDPI上列URL|429，计1。|
|R6|Cross-cryptocurrency ScienceDirect上列URL|403，计1。|

只新增本MD；0市场数据读取/市场GET/回测/统计/native/全局登记/付费/新API/代码实现/automation。前向冻结manifest `7576da10d07642d3e4e791492514bc1e84b89b9746b608cdbd91c2a6471522e1`、global `fe34ac57e25416a674110cb8c132168c33fd9ccd17749e640ef6686293ae778f`、grant `2e5d633efa123c95a3b1857515a0d35ba979d3b7601e02fde3ac5f4ab145d4e5`保持。Issue139前向仍等待09-10 00:10UTC，研究不因此整体暂停。本切片交监督安排有限队列，当前不自动跳下一域、不合并或关闭Issue141。
