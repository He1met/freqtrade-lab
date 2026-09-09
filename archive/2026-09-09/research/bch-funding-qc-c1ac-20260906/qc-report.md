# BCH-S-FUNDING-QC-202308-V1

已完成一次官方原始样本结构 QC；未获得最终结算语义证明，当前 producer 存在明确时间偏移不相容。此结论只适用于本样本。

- 来源： https://static.okx.com/cdn/okex/traderecords/swaprates/monthly/202308/BCH-USDT-SWAP-fundingrates-2023-08.zip?v=999
- 2026-09-06 06:26:57 UTC 发起唯一 GET，HTTP 200；1 ZIP、无重试/重定向、QC 0.267 秒。使用 stdlib HTTPSConnection 单次 request，不调用带 floor 的 producer。压缩硬上限 10,000,000 字节、总解压 20,000,000 字节、最多 1 个成员；实际 ZIP 1,417 字节、CSV 4,557 字节。路径安全、非目录/非链接/非加密、大小、CRC、UTF-8 与 CSV 结构检查通过。
- ZIP SHA-256：`96a37b7747344d6c8847c6ce8332b132a901c6196a272ea0590aa7172f369eb7`。
- 唯一成员 `BCH-USDT-SWAP-fundingrates-2023-08.csv`；CSV SHA-256：`8ca38a8d7995d48ae8498aad116932db2d3d67489c9deb1285162059b6684e7e`。
- 字段为 `instrument_name,funding_rate,funding_time`。93 行，身份全部 BCH-USDT-SWAP；重复时间与完整重复行均 0，文件时间严格递增。先完整验证身份/时钟，全部位于拟 S `[2023-07-17,2024-07-15)`，随后仅在进程内检查率值有限、Decimal 精确表示及 consumer float 有限性，均通过；不声称二进制 float 精确。未输出率值或分布。
- 原始时间为 13 位毫秒整数：`1690819201000` 至 `1693468802000`；按 Unix 毫秒解释为 UTC `2023-07-31 16:00:01` 至 `2023-08-31 08:00:02`，UTC+08 为 `2023-08-01 00:00:01` 至 `2023-08-31 16:00:02`。全部属于 UTC+08 的 8 月，不能当作 UTC 自然月。
- 相邻观测间隔（毫秒）集合：`28797000,28798000,28799000,28800000,28801000,28803000`。相对 UTC 8h 网格偏移集合：`0,1000,2000,3000,4000` 毫秒。原始时钟未经 floor 或其他改写。

当前代码依据为本地 clean HEAD `9a5c00ba2ad1617645b67c1d0475508ba02c401a`，未查询远端。`scripts/fetch_okx_profile_data.py:61,815-922` 的字段、身份、13 位时间与 UTC+08 月份检查相容；`:51` 的最大偏移为 2,000ms，因此本样本 3,000/4,000ms 记录会触发 `DRIFT_EXCEEDS_LIMIT`。该 parser 会先 floor 时间；本次未调用。`lab/bounded_research.py:1141` 的 funding consumer 使用固定 8h 步长，原始间隔不能作为其严格网格序列直接接入。未执行实际 producer/consumer/native；这是已读代码与原始结构的比较，不是集成测试。不得通过此次 QC 自行放宽偏移或认定 floor 合法。

这些间隔只是样本观测；即使均匀 8h，也不能证明当时应有频率或事件完整性。93 条不证明没有缺失更高频事件。结构不能证明 funding_rate 是最终结算值、funding_time 是结算而非记录/发布时刻，也不能解释秒级偏移、历史调整生效点或开平撞结算归属。

语义引用仅来自已读旧 `bch-feasibility-db32-20260906/decision.md` 最终补证及 `request-receipt.json.final_supplement`：旧官方 API 文档 SHA `89ffb322ec943d6ca67177a7624346b419131241935dcb0d8216978904eff9d4` 的 REST history 使用 realizedRate/fundingTime，历史 archive 映射仍 UNKNOWN；本次没有再访问文档或补采。

账本在现有 sidecar flock 下经 apply_patch 先登记 DATA_QC_ONLY，再追加真实结果；原字节及空行逐字节保留，两次 before/after/prefix 回执见同目录。无 Search 消费，但本样本以后不能声称从未读取。没有策略/收益统计、OHLCV/mark、其他月份、D/H/Stress、Feather、补零、DB/Candidate/ResearchRun 或业务代码修改。执行到此停止；工程、全 S 采集与 Search 均未授权。

## 纯本地原因补充（2026-09-06；一页内）

**结论：2 秒是项目实现门，不是已证交易所规范；不应据 BCH 的 4 秒观测直接放宽。当前最终率与事件语义仍无法证明，暂不值得实施适配。** 基线复核为本地已有 `7ae2b6b6c45cfb57c40a13dccd697ce1c57d08a4` 对象；相关 producer 与 9a5 无差异。native 为 `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`，所读相关文件无本地修改。

1. **根因与来源。** `a8d3d311`（2026-09-05，PR #54 / Issue #52 分支）同时引入 `FLOOR_TO_8H_GRID_V1` 和 `MAX_FUNDING_ARCHIVE_TIMESTAMP_DRIFT_MS=2000`，从“必须精确在网格”改为允许网格后 0–2 秒；合成测试覆盖 0/1/2 秒通过、-1/2001/3000ms 拒绝。`31e481c` 只补诊断，未改变门。已读提交/代码没有交易所标准引用，未找到相关 Issue 正文缓存，因此“用户曾具体授权 2 秒”不能由提交名或测试推定，仍 UNKNOWN。可确认的是：项目固定窄容差假设，被硬编码为通用 archive 规则。
2. **合理配置边界。** 若有可追溯语义，归一化方式、允许偏移、适用资产/时期及事件日历应绑定版本化来源契约，在新读取前固定，并透传 producer/consumer 回执；不宜作为可任意调节的 Profile 策略参数。可复用现有 JSON，不需加表。现在把 2000 改成 4000 是按样本修门，也没有解决 floor 的真实性；固定 8h 本身同样需要证据。
3. **保留原时刻并非现路径直接支持。** `7ae2b6b` producer `:1170–1181` 要求完整固定 8h 序列；lab `bounded_research.py:1145,1876–1884` 要求行数、端点和每步精确连续。另有 native 层：producer `:1219–1225` 调用通用 `ohlcv_to_dataframe(...,"1h")`；native `converter.py:46` 经 `exchange_utils_timeframe.py:32–44` 实际 floor 到 **1min**，仍会去掉秒偏移。即便保留原时刻，native `exchange.py:3926–3929` 默认按 date inner join 整点 mark，偏移事件会丢失；`backtesting.py:453` 正在使用此路径。末端 `calculate_funding_fees:3975–3987` 本身可按细粒度排序时刻求和、不强制 8h，但这不能证明完整输入路径支持。阻碍同时在 lab 网格、converter 和 native mark 配对，不只是 2 秒门。
4. **日线边界与最小范围。** native 区间含开/平两端。若原始时刻真是 00:00:04，00:00 平仓时它在持仓外；floor 为 00:00 后会计入。若原始时刻仅是延后发布、实际结算为整点，直接保留又可能漏计；新仓整点是否有资格同样不能靠代码证明。必须外部证明最终率映射、事件/发布时刻、历史频率和边界归属及配套 mark 含义。若证据证明只是记录延迟，最小改动是来源契约绑定的归一化＋原字节/时刻追溯＋两端合成检查，保留现 native；若证据要求秒级真实事件，则需同时调整 lab 日期契约、绕过 converter floor、明确 mark 配对，已超“配置容限”这一小改。当前不推进任何实现，不提出变频平台或追加目录采集。

本补充无网络、无样本率值重读、无 ledger 修改。范围偏差如实记录：初次源码关键词检索误命中并输出既有测试 fixture 的 provenance 整行，其中混有旧测试结果字段；未用于本结论，随后已收窄为指定源码。未读取其他策略结果文件。
