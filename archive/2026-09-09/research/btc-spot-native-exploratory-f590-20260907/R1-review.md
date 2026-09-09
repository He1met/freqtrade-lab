# BTC 已见训练探索 R1：通过研究门，尚非 finalist

真实项目状态 **SEARCH_ROUND_READY_FOR_CHILDREN / EXPLORATORY / NOT_INDEPENDENTLY_VALIDATED**。2024 已见训练上的 R1 完成 1 次市场 native，通过冻结的 6 笔/net≥1 USDT/PF≥1.05/native DD≤10%/ROI 0 等研究门；仅选定 parent，未完成两轮，未获得独立验证或盈利资格。剩余框架预算 1 并不构成执行授权，当前剩余获准市场调用为 0。

| 指标 | 实际结果 |
|---|---:|
| 钱包起始 / 结束 | 1000 / 1161.48874086 USDT |
| 价格毛利 / 原生费用代理 / 净利 | 165.887801662 / 4.399060804 / 161.488740860 USDT |
| 钱包净收益率 | 16.148874086% |
| 净利 ÷ 配置 stake250 | 64.595496344%，仅名义投入分母，不是复合/年化回报 |
| 真实每笔 stake | 249.99957474–249.99995031 USDT，原生精度舍入 |
| 成交 / PF / 平均持有 | 7 / 3.186548405 / 39702.857 分钟（约27.57天） |
| 项目采用的 native summary DD | 5.110036498% |
| ZIP 自带 native wallet 日开盘快照 DD | 9.280872038% |
| signal / stop / force / ROI exits | 4 / 3 / 0 / 0 |
| rejected signals | 0 |

**回撤口径不能混用。** 读取实际 ZIP 时发现 native 自带 wallet_stats，因此补充披露9.28%。已读固定原生代码确认它在交易处理前记录USDT余额×1及BTC余额×日open，再按日期汇总；它不是独立复核的日close/盘中最坏MTM。独立MTM仍为UNKNOWN。原冻结门按项目summary DD判断，不事后换指标。

固定季度块按**平仓日期归属已实现净利**：Q1（01-30起）0笔/0 USDT，Q2 2笔/+77.05086530，Q3 3笔/−22.95377807，Q4（至12-31排除）2笔/+107.39165363。这不是MTM分块；Q1没有平仓不表示没有暴露或组合回报为零。7笔已见训练样本不足以推断稳定盈利。

Generation `deb82d87-e88c-41c0-8ad1-0900b308ddaa`；Candidate `f23f7e42-4975-4607-aa37-770fc9139503`；Search `4e5bbbca-0f16-4205-9827-6795a27521f9`。新库六表counts为1/1/1/0/0/0（Profile/Generation/Candidate/ResearchRun/Execution/Release）；R1没有被伪造为MANUAL完整Search终态。Generation按原完整源码SHA匹配后正常APPROVE；工具事件0。

采集1次、5GET、45159 decoded bytes；人工进程2次（第一次启动前失败），合成实际Backtesting.start 1次；市场native 1次；R2/基准/市场smoke/D/H/Stress均0。原synthetic-01、旧源码副本和网络事实勘误全部保留；只补exchange后synthetic-02通过。源是新采集的已见2024训练，不是新独立数据；2025与其它保护窗未读。

证据入口 `R1-final-delivery-receipt.json` SHA `c85699ea1b4a8770a0419454a67cce4e24ac8685658e7e8c05fd3e8b0601bf8a`；原生 ZIP SHA `c4bca56bc68e3560b18181a3257e2be03be3f71a32a5295beedb71d9839f5040`。最终台账 SHA `3af0b9dd57be3336bef6973d26ea24157ca248a9d4f92412f9f976dc6d7c0147`，每次加锁追加且保留原字节前缀。

Console [本机入口](http://127.0.0.1:53251/console) 及 Generation/Search API 均实测200，服务保留供监督只读查看。执行驱动已停止；下一步由root决定是否值得另外冻结验证或授权后续研究，不自动生成R2 child，不借用保护窗，不追加工程。
