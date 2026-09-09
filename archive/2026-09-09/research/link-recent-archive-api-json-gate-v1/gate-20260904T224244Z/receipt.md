# LINK_RECENT_ARCHIVE_API_JSON_GATE_V1 — bounded receipt

**本 Gate 三项局部通过，等待监督验收；不构成全窗口 READY 或策略研究通过。** [Issue #67](https://github.com/He1met/freqtrade-lab/issues/67) 保持 OPEN。证据仅在本 Git 外 private root（0700）；最终只读核验时间 2026-09-04T22:54:21Z。

| 范围 | 实际状态与证据 |
| --- | --- |
| SAMPLE_BRIDGE | PASS_SAMPLE_BRIDGE_ONLY。固定官方 API 的 100 个唯一原始 trade IDs，在唯一日档中各出现一次；instrument、毫秒 timestamp、buy/sell、精确 Decimal price/size 全等。只证明这 100 行的同 ID taker-side/合约数量字段对应。 |
| REAL_FORMAT | PASS_REAL_FORMAT_ONLY。选中 100 行已先持久保存原始/规范化材料；原生 JSON store/load 精确 DataFrame 与原始 Decimal 比较通过。仅合约数量格式，历史 contractSize / base amount 换算 UNPROVEN。 |
| SYNTHETIC_COMPATIBILITY | PASS_SYNTHETIC_ONLY。FLOW 和原五个执行案例各一次。全部 42 根 flow 完整，原始 84 条含每根 +1/+2ms，末根未丢失；五例真实调用原生 Backtesting，成交结果已持久保存并只读回核。 |

合成实际结果：FLOW 的 bid=sell、ask=buy、delta、UTC 5m 边界及 max_candles 尾截断检测均通过。R1_NORMAL/R2_NORMAL 原生成交 index 33 open 入、34 open 出，5分钟，成交价均与合成开盘价相等；R2_REJECT_BUY_DOMINATED 为零单；R1_STOP 在33止损；SYNTHETIC_FORCE_EXIT 在41强制退出。相邻 entry 与同根 entry/exit 冲突检查通过。网络调用记录为空。所有成交和潜在 PnL 均 SYNTHETIC_TEST_ONLY；没有真实策略/OHLCV/flow/信号/PnL。

一次请求与曝光边界：catalog/API/ZIP 各1次、无重定向/重试；响应分别488 / 12,156 / 1,774,123 bytes。目录初始正文回读22:46:49早于catalog22:46:55，目录URL增补全文回读22:47:54早于API22:47:59；ZIP22:48:43。唯一完整扫描291,794行，累计解压15,944,105 bytes（header/首行同一计数流），单一正规CSV、EOF CRC通过。整档实际UTC为 **2026-06-07T16:00:00.985Z 至 2026-06-08T15:59:59.079Z（包含）**，均在冻结raw日内。整ZIP已获取；全档只解释timestamp/ID，其他字段仅解释匹配100行；API样本实际UTC为2026-06-08T07:59:21.126Z至07:59:56.548Z。未重扫旧January或本日ZIP。

资源：开始2026-09-04T22:42:44Z，活跃/墙钟共同截止2026-09-05T00:42:44Z；最终合成执行于22:52:37Z结束，最终只读核验22:54:21Z，均在两小时内。独立活跃计时未设置，实际活跃时间上界为墙钟耗时。所有实质执行子树采样RSS峰值≤291,356,672 bytes，OS child high-water≤292,175,872 bytes；单个case最长1.528秒，未触及2GiB/300秒上限。normal/timeout/低RSS终止预检通过，最终owned child存活数0。20ms RSS轮询+wait4 high-water是观测及越限终止机制，**不是kernel硬配额**；服务档位API未暴露，UNKNOWN，未改配置。

唯一普通路径修正：初始真实JSON打开输出文件前因缺失 data/futures 父目录报 FileNotFoundError，尚未序列化或比较。原脚本、FAILED_STOP收据及stderr保留。一次修正仅补真实及尚未运行合成案例的 futures 父目录，真实attempt2写独立收据；未改断言/时间/fixture/策略/原生撮合，也未增加HTTP或扫描次数。
- 合成预冻结脚本SHA `f0226fe8f6f223f2969d468cc75289a57d946c50d168e1f7def4630d7df17753` 保存在 `run_synthetic_frozen.py`；当前执行脚本 `run_synthetic.py` SHA `c7a8237c2e33e7786804de15753ac067b29b542c4aa85c6f0837c779ff2fbe46`。**二者不同，不能称全部当前文件与freeze manifest相等。**
- 真实原脚本SHA `52b1b46ef96346c1b589b075b885f054568617cbbd1c0c3eac0c93f90288335c`；attempt2 SHA `581f14714113d585f61edbddcaf374c15bcd817bcd2a7f9ac2460e119a095e13`。完整old/new文件与原错误已入SHA索引。
- R1/R2/fixture原SHA全部保持；native为干净2026.7/`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`。

JSON handler 忽略 TimeRange、整文件读入，所以本次真实100行与各合成案例物理分文件/目录；未来任何研究必须物理分阶段隔离，不能先读sealed数据再过滤。历史contractSize、跨文件schema适用性、全研究窗口完整性/JSON资源、funding与因果availability仍UNKNOWN。未运行G2、Search、Dev、H/Stress或其他真实研究；2024预留及2026例示日历均仅未授权metadata。先前索引未见LINK冲突不等于全市场独立时期。

Lab当前HEAD和实时remote main为 `dc82c61fe8a27a654977344755c088412518d858`，Lab/native均clean，原checkout未跟踪docs保留。#62/#66保持旧OPEN/BLOCKED，#65 CLOSED；旧#66收据/索引SHA复核未变。无Lab/native代码变更、DB/资金/凭据/实盘/系统设置操作，无commit/push/PR。本 Gate在此结束，仅交监督验收，不自动开G2。

必要证据索引：`final-evidence.json`，SHA-256 **1bf70b9a9d2aefb063757c34789b7e88a588696f718fed1d8f36a8a1cc96ef0e**。它列出全部原始响应/样本/脚本/合成原生成交与资源SHA，冻结内容以保留文件校验，当前文件另列实际SHA；无真实市场值汇总。
