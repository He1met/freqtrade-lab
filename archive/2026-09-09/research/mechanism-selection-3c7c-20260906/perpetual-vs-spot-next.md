# 下一方向比较：先评估单品种1倍永续，不默认继续换币现货

Issue93已关闭，失败规则不重开。本比较只用既有论文、本地源码和必要元数据；新增网络请求、市场数值读取、策略注册及回测均0。**建议下一授权优先给“单品种、isolated、1倍永续的中期双向时间序列动量”做有限可执行协议准备；不是直接授权Search。** 与之比较的现货基准为相同经济假设的long/cash版本，避免因页面兼容性把较弱经济理由排到前面。

| 维度 | 优先：单品种1倍永续long/short | 比较：现货long/cash |
|---|---|---|
| 经济假设 | 信息／仓位调整迟缓使正、负价格趋势在日到周尺度延续；正信号做多，负信号做空。期货的价值是能表达负方向，不是杠杆放大回测。 | 同一机制只参与正方向，负方向持现金；免去资金费和合约会计，但不能赚取负价格趋势。 |
| 原始先验 | 既读[Liu–Tsyvinski 2018作者论文](https://www.nber.org/system/files/working_papers/w24877/w24877.pdf)含BTC/XRP/ETH旧日周动量和先用两年确定分位门后的后续样本检验。 | 使用同一依据，是现有资料中较直接的旧加密价格证据；比把CGW旧美股换手率直接外推单交易所基础币量更接近目标市场。 |
| 不能声称什么 | 论文不是当前永续费后交易证据，也没有证明负方向天然更赚钱；强反弹、震荡、资金费和滑点可吞掉信号。曾研究过动量家族，不能将开通short或换资产算作独立新alpha。 | 现货更容易承载，不表示经济证据更强；继续换币复制均线/反弹不是新机制。LTC失败不能通过切成short或改成本复活。 |
| 成本／风险 | 每腿taker费和滑点之外，按真实持仓时刻计signed funding、mark及可能清算；即使1倍也不能把funding填0。单品种单腿，不做跨所或现货对冲组合。 | 每腿费/滑点、现金与MTM即可；仍须有价格收益和独立后续时间证据。 |
| 当前代码与最小代价 | 已有futures/isolated Profile、can_short和原生执行，不需新runner/Schema。但多年futures日窗与同run H/Stress接续有具体缺口，见下。若数据契约成立，有限项目适配估计**1–2主动工作日**，native/六表不改。 | 当前多年spot 1d与同run H/Stress已有路径，Git外固定策略/协议准备约**2–4小时**。较少工时只是交付成本，不是选择其经济机制的理由。 |

**可追溯覆盖已知与未知。** LINK永续既有source receipt实际文件SHA仍为`00223900be7de0731631f1422cb7ab60514480304941211459cf849324c57325`，与全局ledger第83条一致，路径：
`/Users/shenjianpeng/.codex/runs/freqtrade-lab/link-closed-shock-continuation-n-v1-2528-20260905T034227Z/source/retrieval_receipt.json`。
此次只计算该文件字节hash，没有解析资金费或行情值。该登记证明过去一个具体LINK S+D包与消费者曾成功QC；不能把这种历史成功说成新窗口可用。其S `[2024-08-01,2025-01-31)`已消费，D `[2025-01-31,2025-07-31)`仅物化QC且保留封存，H的价格/mark未取、部分rate尾部仅不透明字节接触，均不释放。故它证明**不是全部永续数据都不可行**，并非可直接复用的数据池。

ATOM旧核验仅在指定合约和指定2021H1目录没有链接，不推广到所有合约／年份。LTC现货本次1381行成功也不能证明LTC永续资金费完整。拟选永续资产、新S/D/H、点时身份/流动性和官方结算时刻均 **UNKNOWN、尚未冻结**；当前不凭表现挑币，不查看封存结果补选。不同产品／交易所同币同段不算独立验证。

**具体工程边界。** 当前commit `7ae2b6b6c45cfb57c40a13dccd697ce1c57d08a4`：

- [market_contract.py](/Users/shenjianpeng/.codex/worktrees/3c7c/freqtrade-lab/lab/market_contract.py:7)已接受`futures/isolated`，不用新增业务市场类型。
- [bounded_research.py](/Users/shenjianpeng/.codex/worktrees/3c7c/freqtrade-lab/lab/bounded_research.py:1186)仅给spot1d 1830天上限，其余366天。日周机制要有足够时间事件时，需要有界扩展futures1d资源与行数校验，不能为迁就366天压缩出不足样本。
- [holdout_run.py](/Users/shenjianpeng/.codex/worktrees/3c7c/freqtrade-lab/lab/holdout_run.py:293)的Profile H源入口明确只接受spot1d；[producer入口](/Users/shenjianpeng/.codex/worktrees/3c7c/freqtrade-lab/scripts/fetch_okx_profile_data.py:260)与消费者需补同run futures1d OHLCV/mark/funding绑定。建议只扩一个已确认合约/时窗与同run接续，不建通用多腿平台。
- funding producer现有8h事件网格是有限契约，不可当作所有instrument/年代的事实。若选定样本存在无法追溯的频率或时间戳变化，先按`BLOCKED_DATA`停止该契约；不能改floor规则或造0费率过关。原`lagged_funding_signal_v1`仍是特定LINK 5m exploratory模板，不是任意资金费信号已可正式晋级的证明。

**下一最小授权建议。** 允许一次短的值前协议准备：先按非收益的上市历史、市场身份和官方资料可得性选定一个永续资产及足够长的未消费/未占用窗口，再用有限的**公开元数据**确认funding档案与时刻契约，交付唯一long/short规则、1倍绑定、完整成本及S/D/H日历和最多一次Search预算。若必须做上述适配，提交明确文件范围与1–2日上限供授权，不预先施工；若没有可追溯新窗口，报告这个具体数据阻塞，而不是自动回退换币现货。后续一次采集QC和Search仍各按监督授权执行。

这一步选择的是更完整的交易表达和值得证伪的经济假设，不是找到盈利策略的结论。当前不冻结7日或任意指标参数，不新开Issue、不追加任何新研究消费。
