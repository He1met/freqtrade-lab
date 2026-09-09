# LINK_NATIVE_ORDERFLOW_G1_V1 — G1 receipt

结论：**BLOCKED_NATIVE_COMPATIBILITY / STOPPED_AT_G1**。本轮未通过整体 G1；另有独立的 **ARCHIVE_SEMANTICS_UNKNOWN** 和 **REAL_HANDLER_ROUNDTRIP_INCOMPLETE**。这不是策略经济失败，也不是策略通过。G2/G3 均未开放。

收据日期：2026-09-04 UTC；执行 task `01a06e51-9548-70e3-8933-c5a8b86a879e`，监督 task `01a05dcc-17fd-7972-9177-9fed95e4b07a`。[Issue #66](https://github.com/He1met/freqtrade-lab/issues/66) 保持 OPEN。证据根目录为本文件所在目录，所有数据均在 Git 外。

## 冻结与资源边界

- 工作预算开始 21:51:03Z，固定截止 2026-09-05 01:51:03Z。实质失败的执行结束于 22:07:56.829397Z，随后仅只读定位、证据整理和授权回执；未增加执行预算、样本或测试案例。
- Issue 创建与原正文更新时间均为 21:57:29Z，唯一实际下载始于 21:58:36.926646Z，冻结在先。完整远端正文回读一致；8 项 preregistration SHA 在最终复核仍全部一致。
- `pre-download-manifest.json` SHA-256：`434bad87d33532c172bd402c50a29d051fe7532a4c662812772fcf9e7e730d23`。原正文 SHA：`4c7de401967e63743545a1e6a6abfb7cb8a9de05db1fbaae170f7e304c3212b4`。
- 下载 HTTP 200，1.910 秒，41,976,244 bytes，未重定向、未换源；压缩上限 67,108,864 bytes。一次完整 CSV 流读取 349,420,198 bytes，声明解压上限 536,870,912 bytes；另有下载后先行 header/首 timestamp 探针，其精确缓冲解压计数未单独保留，故不声称完整扫描计数就是全部探针的精确累计。没有第二次完整解压。
- owned-child watchdog 的正常、超时和低 RSS 终止预检均已完成。它是 20ms RSS 轮询加 `wait4` OS high-water 校验，不是 kernel 硬配额。最终核查没有存活的本轮受控子进程。

| 执行 | 秒 | 采样峰值 RSS bytes | OS 峰值 RSS bytes | 结果 |
| --- | ---: | ---: | ---: | --- |
| 唯一 ZIP 下载 | 1.910 | 7,946,240 | 7,979,008 | HTTP 200 |
| 真实选中记录格式检查 | 11.324 | 567,492,608 | 575,143,936 | 格式检查完成；文件写入接线失败 |
| SYNTHETIC FLOW | 1.376 | 280,363,008 | 281,198,592 | PASS_SYNTHETIC_ONLY |
| SYNTHETIC R1_NORMAL | 1.619 | 294,813,696 | 295,387,136 | 原生订单流完整性失败，停止 |

两次合成执行均受原定单次 300 秒 / 2 GiB 限制，无超限。资源预检中的有意 TIMEOUT/RSS_LIMIT 终止不是研究运行超限。最初 shell 对未引号包围的 `=https` 解析失败发生在发起网络之前，原错保存在 `bootstrap-error-1.json`；修正 shell quoting 后只进行了一个真实 GET。

## 原始暴露与选中语义消费

唯一文件：`LINK-USDT-SWAP-trades-2024-01.zip`，SHA-256 `0a2b7f9ac9658efad371e4949c6e85b7ace647a88edce523c7997b0f630fd988`。唯一 CSV member 为同名 `.csv`，声明与完整流字节数一致，读到 EOF 时 ZIP CRC 检查未报错。

| 证据 | 结果 |
| --- | --- |
| 整包暴露 | 整个原始 ZIP；非选中记录仅解释 timestamp |
| 完整 CSV 行数 | 6,240,962 |
| 整包 timestamp 最小值 | 2023-12-31T16:00:00.152Z |
| 整包 timestamp 最大值（包含） | 2024-01-31T15:59:59.729Z |
| 选中区间 | [2024-01-30T00:00:00Z, 2024-01-31T00:00:00Z) |
| 选中记录 | 169,574 |
| 选中实际最小／最大值（包含） | 2024-01-30T00:00:00.219Z / 2024-01-30T23:59:56.809Z |
| 选中 instrument | 全部等于 LINK-USDT-SWAP |
| 选中重复 trade ID / 原生 timestamp+ID 键 | 未发现 |
| timestamp | 全部为精确 13 位 Unix milliseconds 形式；无倒序步骤 |
| side 字面值 / price、size 格式 | buy/sell；选中数值有限且为正；不输出价格或数量统计 |
| 真实 CCXT parse_trade | 对选中记录条件字段映射通过，ID、timestamp、side 与未缩放 raw size/price 保持 |
| 真实原生 Feather roundtrip | INCOMPLETE：尚未写成文件，不存在持久化选中数据 |

不将文件名视为 UTC 月边界。先按 timestamp 判断成员资格，只有区间内行才检查 instrument、ID、side、price、size。没有真实价格/收益汇总、订单流聚合、信号、OHLCV/mark/funding 下载或回测。

真实 roundtrip 的普通接线错误是输出根目录 `conditional-selected-native-format` 未先创建，原生 `create_dir_if_needed` 创建其 `futures` 子目录时报 FileNotFoundError。进程已退出，选中 DataFrame 未留存；不增加恢复机制、不重扫而突破累计解压预算。这一错误与下面的档案语义未证、原生时间截断是三个独立事实。原始 `selected-format-receipt.json` 保留 FAILED_STOP 原样，不改写成成功。

## 档案语义仍未证

`instrument_name,trade_id,side,price,size,created_time` 列头存在以及 buy/sell 字面值正确，只证明格式。档案 **side 是否为 taker、size 是张数还是 base amount、2024 历史 contractSize** 仍为 UNKNOWN。真实映射只测试 raw size 未缩放的数值兼容性，不能拿去喂经济研究。

官方普通 [history-trades 文档](https://www.okx.com/docs-v5/en/#order-book-trading-market-data-get-trades-history) 的 side=taker、SWAP sz=contracts 不能独立证明旧 CSV 档案语义。Freqtrade 原生 CCXT 路径解析 API 的 sz，随后 Exchange 的 contracts-to-amount 路径会依据 contractSize 换算；当前 instrument 的 ctVal=1 LINK 也不能补证历史档案单位。

监督者本轮有界核验了官方 [Get historical market data](https://www.okx.com/docs-v5/en/#public-data-rest-api-get-historical-market-data)：module 1 是 trade history，modules 1/2/3/11 的目录日期字段按 UTC+8；这支持月档跨 UTC 月份的解释，但不证明 CSV created_time、side、size 的定义。该核验没有新增目录请求或市场数据下载；报告来自监督 task，正文快照 SHA 未提供，保留 UNKNOWN。

## 已冻结合成案例结果与停止原因

原生 Freqtrade 2026.7，源码 SHA `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`；Python 3.13.13、ccxt 4.5.68、pandas 3.0.3、pyarrow 25.0.0、psutil 7.2.2。仅原生 converter、Feather handler、Okx 与 Backtesting，不修改匹配、填单或原生代码。合成进程的网络审计钩子未记录网络调用。

| 冻结案例 | 实际结果 |
| --- | --- |
| FLOW：bid=sell、ask=buy、delta=ask-bid、UTC 5m 边界 | PASS_SYNTHETIC_ONLY；依次 (7,5,-2)、(4,1,-3)、(1,9,8) |
| FLOW：max_candles=2 | PASS_SYNTHETIC_ONLY；完整性检测发现第 0 根缺失，后两根值正确 |
| R1_NORMAL：原生策略订单流路径 | FAIL：84 条合成 trades 的原生 Feather 写读相等先通过，advise_all_indicators 之后订单流非空断言失败 |
| R1_NORMAL：next-open 入、再下一根 open 出、5 分钟 | NOT_RUN_STOP：在调用 native backtest 前已停止 |
| R2_NORMAL / R2_REJECT_BUY_DOMINATED | NOT_RUN_STOP |
| R1_STOP / SYNTHETIC_FORCE_EXIT | NOT_RUN_STOP |
| 原始相邻 entry 与同根 entry/exit 冲突检查 | NOT_RUN_STOP：位于失败断言之后 |
| 真实或合成成交 PnL | 未进入 native backtest，无可据此引用的成交结果 |

直接运行证据是 `AssertionError: Native flow missing`。静态定位显示：

1. `freqtrade/strategy/interface.py:1791-1797` 用第一根开盘至最后一根开盘构造 trades TimeRange。
2. `freqtrade/util/datetime_helpers.py:35-42` 的 dt_ts 返回 UTC milliseconds。
3. `freqtrade/data/history/datahandlers/arrowdatahandler.py:210-217` 的上界筛选为 `timestamp <= stopts`。
4. 冻结样本每根 trades 位于开盘后 +1 / +2ms，因此最后一根的两条必在该上界之外。这是源码与冻结输入推导；本轮未为定位重跑或保存完整失败 DataFrame，不虚报运行时缺失索引列表。

独立 converter 能算对，不能证明 DataProvider→strategy 的整条路径完整。既然原生路径已出现实质边界不一致，按预注册 stop rule 停止，不添加末尾 K 线、不移动成交时刻、不放宽完整性断言、不 bypass DataProvider、不 monkeypatch 原生引擎，也不继续其他案例。

## 隔离、远端状态与最小后续建议

此前 February Search / March Dev / April H 草案已在下载前撤回。保留的未来 **March Search / April Dev / May H 与 Stress、pre-roll 从 2024-02-29 起** 均为未授权 metadata；January 整包暴露记录完整保留，不因本次失败重选窗口。R1/R2 源码与经济门槛未改。

Lab HEAD 与远端 main 均为 `dc82c61fe8a27a654977344755c088412518d858`，Lab 与原生源码 `git status --porcelain` 均为空。没有 Lab 业务代码/schema/数据库/Profile/Candidate/ResearchRun/Search/Development/Holdout/Release 写入，没有凭据、资金、实盘或系统设置操作。#65 CLOSED，#62 OPEN 且本轮未修改。未 commit/push，因为本轮只有 Git 外 G1 证据；#66 不关闭。

**最小 G2 建议：暂不开 G2，先把 G1 blocker 交监督决策。** 若以后单独授权，应先以原冻结合成 fixture 对原生末根 trades 时间范围问题形成最小可复核修复或上游证据；保持 engine 版本与源码绑定，重新完成原冻结执行语义验收。同时需要独立补齐 archive taker/size/历史合约单位证据，以及另行冻结预算下的真实 handler roundtrip。未解决前不接 Lab，不增加 AST 列支持或开真实策略回测。这只是建议，不是执行授权。

## 可复核证据

- `g1-final-evidence.json`：所有已生成输入/原始输出的文件 SHA、资源记录、最终冻结清单校验、远端 Issue 原正文相等、Lab/native clean HEAD、存活进程核查。
- `selected-format-receipt.json` 与 `selected-format.stderr`：真实格式检查与完整原错。
- `synthetic-FLOW.json`、`synthetic-R1_NORMAL.json`、对应 stdout/stderr/resources：合成通过项与实质失败。
- `run_synthetic.py` SHA `7ee0d690516457b19f0425a2cda41f22a0970c89adaa7337af103cec3cad6b7f`。
- R1 SHA `2f53392a04fea4e1131742cadcd5c24b8c4fbe62de79b16a18da16c79ed90640`；R2 SHA `89bf87f7a20e8362ad7e538cdb8d5f63d68ab145b3d4454763995eef4a9ae917`。
