# 下一对象：仅建议 BNBUSDT 元数据预检

2026-09-07。唯一推荐 **BNB/USDT:USDT 日线简单冲击延续的可用性预检**，未冻结策略/未授权执行。维持现资金合同，不补早期mark。

| 候选 | 值前经济/数据理由 | 决定 |
|---|---|---|
| BNBUSDT | 官方公告注明2020-02-10 08:00 UTC开始永续交易；BNB有链上gas用途及交易生态需求，注意力/信息冲击的延续是假说，也有平台相关集中风险。成熟合约历史长，ledger无具名占用，原native静态tiers已有10档 | 唯一推荐；不按历史收益、波动或触发数筛选 |
| UNIUSDT | 官方公告频道确认UNI USDT永续上市，原native静态tiers已有10档；协议治理代币可研究DeFi信息冲击，但代币价值捕获与协议使用不直接等同。ledger无具名占用 | 不同时预检；本轮优先更广交易生态用途的BNB。未核精确上市时刻，非首选不继续查文献 |

两者实际历史深度、价差、3%自然频率和资金覆盖均UNKNOWN。“成熟”由上市资料支持，“流动性足够”仍待后续冻结代理门验证，不能由名气证明。保留原简单±3%日冲击/48h、两日原始Q抑制作为未冻结家族假说，不因换资产调整阈值；不能称独立alpha或预期盈利。20/40bp往返和原资金合同不变。

**准确三窗（UTC左闭右开）**：S [2023-11-06,2024-11-04)，D [2024-11-04,2025-11-03)，H/Stress [2025-11-03,2026-05-25)。35日预热分别2023-10-02、2024-09-30、2025-09-29。364/364/203评分日，完整三窗用于不同阶段，不重用本币历史保护窗。

ledger现137019bytes、SHA cb1182406832d087aa7beab1711ab4bdaba205cbc151e7532f9ce0a259d11b99。递归字符串与精确资产边界检索BNB/UNI均无具名记录；这只排除已登记冲突，外部UNKNOWN仍保留。BCH现有2023-11至2026-05的S消费+D/H保护连续占用；ADA/DOGE同期间S消费、D保护或消费、H保护，无法提供本轮一年S+一年D+半年H，不能借原D/H开发。2026-05-31至07-31全资产UNKNOWN禁区排除；之后截至现在也不足完整三窗。LTC同币spot旧S到2024-01-01、D2024、H2025至2026-05-31，不能靠转永续声称独立。跨资产同期旧BCH/DOGE/ADA及BTC/ETH等学习污染明确存在，本BNB留出只做到本币未读和时间分离，非统计独立。

**最小工程**：参照已核PR102实际3文件+22/-18；只在lab/futures_costs.py的唯一映射和错误文案添加BNB，tests/test_binance_pair_binding.py及tests/test_profile_holdout.py加BNB参数化覆盖。native锁定源码已有BNB10档，无需新runner或修改Freqtrade。预计0.5–1.5主动小时含producer/consumer错币、缺资金/mark、同Run H绑定定向合成检查；不是重复大套。历史tiers/精度不因此已验证。通过元数据并另授权才建单一Issue、实施/审PR。

**请求下一步（目前未执行）**：最多6匿名GET，总2MiB decoded、单次15秒、总90秒、零重试/重定向/分页。1次exchangeInfo只提取BNBUSDT identity/onboard/status/perpetual/USDT；5次仅BNBUSDT fundingRate各limit10，UTC单日2023-11-06、2024-11-04、2025-11-03、2026-02-09、2026-05-24，各endTime=次日-1ms，资金响应合计<=256KiB。每日期望3事件，核symbol/原timestamp/UTC8h/associated mark有限正值，rates不作经济分析；首失败停其余。仅输出布尔/计数/端点/SHA，原响应Git外；原lock追加一条DATA_METADATA_ONLY、保留前缀。D/H代表日只属有限QC暴露，不执行信号；抽查通过也非全期覆盖。全期QC/行情/Generation/Search/DB仍另等授权。

官方依据：[BNB上市公告的本次官方搜索索引](https://www.binance.com/en/support/announcement/detail/360039190692)（打开正文地域重定向，上市时刻来自该官方索引）；[Binance官方UNI上市消息](https://t.me/s/binance_announcements?before=1698)；[BNB官方用途说明](https://www.bnbchain.org/en/what-is-bnb)。UNI引用为已读取的官方频道历史页；未使用收益排行作选择。
