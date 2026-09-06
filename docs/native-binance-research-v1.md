# Binance 原生合约研究入口（Issue #94）

范围固定为 `BINANCE_CRYPTO_PERP` / `binance` / `BCH/USDT:USDT` / `1d` / `futures` / `isolated` / 1x / 单仓。沿用六张业务表和现有 Profile、Search、Development、Holdout、Holdout Stress、Console 入口。旧数据库不迁移；从新的临时或个人研究数据库开始，禁止连接交易账户。

## 运行环境与来源

使用 Freqtrade `2026.7`，commit `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`，Python `3.13.13`、ccxt `4.5.68`、pandas `3.0.3`、pyarrow `25.0.0`。设置 `FTLAB_PROFILE_PYTHON` 指向该环境、`FTLAB_NATIVE_SOURCE` 指向干净的原生 checkout；生产采集时通过 `PYTHONPATH="$FTLAB_NATIVE_SOURCE"` 绑定源码。不要借另一个环境的完整 `site-packages` 覆盖这些依赖。

Profile 的交易所、交易对、周期、资金、仓位、费用及门槛必须在结果产生前冻结。窗口 JSON、economic Gate、single-baseline（如使用）的格式及 Console 命令沿用 [Profile Quickstart](../README.md#current-profile-quickstart-search-and-development-in-the-research-console)。Binance 使用以下来源生产器替代 OKX 生产器，其余准备命令不变：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$FTLAB_NATIVE_SOURCE" \
  "$FTLAB_PROFILE_PYTHON" scripts/fetch_binance_profile_data.py \
  --profile-database /absolute/private/new-lab.sqlite \
  --profile-id <frozen-profile-id> \
  --window-spec /absolute/private/frozen-window.json \
  --pre-roll-candles <frozen-positive-integer> \
  --economic-gate /absolute/private/frozen-economic-gate.json \
  --capture-root /absolute/private/new-native-capture \
  --output-root /absolute/private/new-source
```

该命令只调用一次原生 `download-data`。公开请求限制为 `fapi.binance.com` 的 `exchangeInfo`、BCH 日线、小时 mark 和 funding history；在发送前约束 start/end，给缺失的 funding endTime 加上排他上界前一毫秒，并把新交易对 since=0 探测限制到已授权起点。不读取签名接口。最多 2000 次 CCXT fetch、2 GiB 解码响应、5 GiB 捕获目录、2 小时；遇到错误立即停止并保存证据，重试须先核查预算与 Retry-After，不能复用失败目录。

若已有经过登记的原生捕获，使用 `--http-receipts /absolute/http-receipts.jsonl --raw-dir /absolute/raw` 代替 `--capture-root`，无需再次联网。保留文件是 CCXT 解码后的 UTF-8 响应，不能标为原始 wire bytes；传输内部重定向次数为 `UNKNOWN`。全部输出在 Git 外；已存在的目标禁止覆盖，转换或发布失败仅清理本次临时目录。

生产器核验原始响应的 SHA、大小、身份、请求范围、去重及完整性，调用未修改的原生 converter，`fill_missing=False, drop_incomplete=False`。历史末根完整 K 线保留原始真实行，不用插值填补缺口。杠杆档位取锁定原生 dry-run 静态文件，其历史适用性保持 `UNKNOWN`。

输出两个 SHA 后，运行 README 中的 `prepare-search-data` 与 `prepare-development-data`，分别得到 Search-only 和 Development-only 目录。两者必须使用同一原始来源 SHA、Profile、窗口、pre-roll、Gate。启动 Console 时传入这两个独立目录，不能把完整来源目录作为 Search 输入。

## 成本与资金约束

资金事件保持实际 fundingTime；原生时间戳按原生分钟桶映射。评分窗口必须具备完整 8 小时事件日历及每次最终 fundingRate 对应的正数 associated mark。指标预热期不要求 associated mark；它不能进入评分。事件缺失、重复、错币种或不能对账都拒绝。

原生 ZIP 报告、成交与 native funding PnL 不改写。外部审计 `BINANCE_ASSOCIATED_MARK_BOUNDARY_V1` 对每笔真实原生成交执行：

- 确认内部事件用原生和 associated-mark 现金流中更不利者；不补记有利修正。
- 入/出场一分钟边界的不确定付款计入、不确定收款不计入；支持原生同根止损的零 funding。
- 扣减进入净收益、逐笔 PF/亏损笔数、逐时现金与普通 MTM 回撤。普通 MTM 使用确定持有的完整小时收盘和实际成交费用，不宣称连续路径保证。
- 小时高低点先有利后不利的次序压力单独展示，不代替普通 DD，也不代替原生加费 Holdout Stress。
- 相邻持仓与关闭时的 funding 均先检查现金约束，再释放保证金。评分排他终点上的退出需额外边界数据，不能假定已覆盖。

实际样本中曾有 associated mark 落在对应小时高低点之外，因此该高低点不能称为严格资金费用误差上界。费用是 Profile 配置假设，不是个人真实账户费率。

Search 排序及最终资格使用保守净收益/回撤；Development 重新校验逐笔合计与 PF，并同时执行冻结的经济门槛。三场景人工 PASS 不能绕过保守净收益、DD、PF 和现金门槛。主表及 FreqUI 保留原生指标；详情扩展指标显示独立保守投影与局限。缺失值保持 `UNKNOWN`，没有亏损时 PF 不改成零。

## 同一 Run 的后续阶段

只有合法 finalist 的 Development 通过后，才允许获取该 Run 的 H 来源：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$FTLAB_NATIVE_SOURCE" \
  "$FTLAB_PROFILE_PYTHON" scripts/fetch_binance_profile_data.py \
  --profile-database /absolute/private/new-lab.sqlite \
  --authorize-holdout-source <same-research-run-id> \
  --capture-root /absolute/private/new-holdout-capture
```

此模式禁止覆盖 Profile、窗口、输出或 Gate，目标由既有 Run 推导；授权文件在请求前独占创建。H funding 数值封存在单独文件，启动/状态仅检查大小与摘要，不提前读取它；点击既有 `AUTHORIZE_HOLDOUT` 后验证其 SHA、完整性，再交给原生 H/Stress 续跑。失败不制造 later execution 或 Release。三个场景必须绑定同一 `research_run_id`，H 和 H Stress 共享窗口、来源和代码，仅执行已冻结加费倍率。

## 工程验收与研究交接

一次原生技术 smoke 使用固定日历多空信号与 2023-11-06 至 2023-11-13 窗口，产生 2 笔技术交易，通过原生费用对账、保守审计、sanitizer 和独立 Artifact parser。原生 ZIP SHA 为 `a69892a62d8ad0d89e717e7f7600f9013062a75561f2f2ca0c36db99c95cdd7c`。包装器重复 timeout 的失败发生在进程启动前，保留记录；修复后实际原生进程仅一次。没有再跑 smoke、真实 Search 或真实 D/H。

同 Run、HTTP 授权、缺失 associated mark 的原子失败与发布约束使用明确标注的合成 fixtures 验证；它们不等于实际 BCH 的 D/H/Stress 经济结果。该 smoke 已在全局 ledger 登记为技术经济暴露，2023-11-06 至 2023-11-13 不得被后续研究当作未暴露数据。最初建议的 36 周 S 不能直接照搬，须先重新确定合法评分区间与固定分块；不能通过重命名交易所规避同资产暴露。

下一研究任务可以评估中期趋势多空机制，例如先前价格区间突破配合较短退出窗口；这是既有趋势家族假设，不宣称全新独立机制。监督任务在首次评分前冻结具体因果信号、pre-roll、净费用门槛、样本数/风险门槛、独立 S/D/H 区间和有限尝试数；最多两轮、六次，实际支持的流程可能更少。未有合法 finalist 时，D/H/Stress 继续封存；数据不全为 `BLOCKED_DATA`，无 finalist 为诚实终态。本工程交付不授权研究、发布或交易。
