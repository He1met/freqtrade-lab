# LINK_NATIVE_JSON_SCALE_FEASIBILITY_V1

**NO_GO_WITH_CONCRETE_REASON：固定合成规模在 4 GiB owned-child RSS 合同下失败。** [Issue #68](https://github.com/He1met/freqtrade-lab/issues/68) 保持 OPEN，交监督验收。本任务在失败处终止，不自动实施 G2 或进入 Search。

| 项目 | 已观测结果 |
| --- | --- |
| 小样本 schema/roundtrip | 新生成器的 2 根、2028 条纯合成数据通过原生 futures JSON 精确写读；没有重跑 #67。 |
| 唯一大样本生成 | 9,337,408 条，32 天 / 9216 根 5m，2001-01-01 至 2001-02-02 UTC（右开），每根内部 +1..+299999ms、唯一 ID、双方 amount=1、price=100。JSON 489,106,619 bytes；SHA `eb5790c55ee05408367b5aacc7a87e469ad9966ed6c6111cc2bd86cf07592de4`。 |
| 生成资源 | 12.081736 秒；采样 RSS 21,790,720 bytes，wait4 OS high-water 21,889,024 bytes；PASS。 |
| 唯一完整链路尝试 | 原 R2 advise_all_indicators → 原生 DataProvider → JSON handler 已进入并返回，再进入原生 populate_dataframe_with_trades；104.122458 秒时 RSS_LIMIT。 |
| 处理资源失败 | 采样及 OS high-water 均 4,296,343,552 bytes，大于冻结 4,294,967,296 bytes 上限。身份核验后的 owned process group 74848 被 SIGTERM，exit=-15；最终 owned child 存活数 0。 |
| 完整性/耗时 | advise_all_indicators 没有返回；9216 根全部 flow 与末根的完成核验 UNKNOWN，完整 native 耗时与后续核验耗时 NULL。没有 process-result.json/all-flow-rows.json；SIGTERM 不产生 Python finally 完成收据，以外层 process.resources.json 为终止证据。 |

JSON handler 返回事件距链路开始约 9.717 秒，DataProvider 返回约 11.744 秒；这只定位失败发生于后续 orderflow 处理，不能当作完整链路通过。20ms 休眠轮询加进程查询、wait4 高水位是观测与越限终止机制，不是 kernel 硬配额，存在采样间隔超调；此次超调已按失败计入。未达到 600 秒超时，不重试、不换格式/参数/规模、不分段或抽样制造通过。

初始 RAM=16 GiB、free=48%；生成前 free=50%，处理前=49%，满足 >=40% 启动门槛；结束后=49%。Git 外 root 权限0700，索引前总量489,369,386 bytes，连同本收据/索引远低于2GiB。开始2026-09-04T23:00:55Z，共同活跃/墙钟截止2026-09-05T00:30:55Z（北京时间08:30:55）；失败23:08:26Z、证据核验23:09:15Z，约8分20秒内完成核心工作。独立活跃计时未设，墙钟为保守上界。早前 commentary 的09:30:55误写已更正，UTC预算从未改变。

执行前唯一 Issue 已精确查重、创建并全文回读一致，generator/源代码/参数/期望/资源已冻结。监督指出的 futures 三参和 native/核验耗时分项在任何 small/大样本之前修正并纳入冻结 SHA；冻结后修正0次。normal/timeout/低RSS守护预检通过。新 root 的 guard 仅将旧审计版本的共同截止改为本90分钟截止，原文件另存；原 R1/R2/fixture、#67收据/索引及关键 native 源 SHA 最后复核不变。

**结论范围仅是这个代表性合成密度、窗口与4GiB资源合同失败。** 291794来自一个诊断日，不是真实长期平均密度保证；本结果不能证明真实月档必然失败，也不能证明整个原生引擎不支持。未取得 full-window READY、真实研究或经济证据。

按冻结条件，规模未通过，所以额外20分钟 Lab source/profile/executor/AST/factor/artifact/Console 最小接入分析 **NOT_RUN_SCALE_FAILED**，工程/测试/实际run估算未作。先前已核对的 JSON 忽略 TimeRange 仍要求调用前物理分阶段隔离；历史 contractSize/base amount、跨文件字段语义、funding/因果可用性仍 UNKNOWN，本次未新增这类证据。比率尺度不变不能补上单位证据；本次没有据此更改既定字段语义。

当前 Lab HEAD/实时 remote main=`dc82c61fe8a27a654977344755c088412518d858`，native=`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`，均保持 clean。#62/#66 OPEN，#65/#67 CLOSED。无业务/原生代码修改、原checkout访问、runtime业务DB/Profile/Generation/Candidate/Search/Dev/H/Stress/Release操作、行情/交易API或任何新历史/封存市场值读取；没有资金/凭据/系统设置操作、commit/push/PR。全部新市场数据 SYNTHETIC_TEST_ONLY。监督已于实质失败后立即获通知。模型/推理由监督核验gpt-6-astra/high，实际服务档位UNKNOWN，未切换Fast/priority或修改全局设置。

必要证据索引：同目录 `final-evidence.json`；索引包含全部冻结源、合成文件、资源证据 SHA，以及一次生成/一次实质处理、NULL完成证据与停止状态。
