# R：1m 跨资产可得性与最小接线

结论：**`BLOCKED_REFERENCE_ELIGIBILITY_AND_SPOT_SCHEMA_SCOPE`**。这是本次审计标签，不是 native 终态。**资料层**：便宜的历史输入路径存在；**窗口层**：所查 S→D→H 路径未取得双资产资格；**实现层**：当前 lab 的 SQL CHECK 也不允许 spot Profile。因此本次不发 `GO_TO_PROTOCOL`，不先投入开发。这个结论不否定 1m 领先—滞后假说，也不把缺 BBO 单独当作 OHLC 有限否证的禁令。

只保留目标 **GNO/USDT** 和参考 **BTC/USDT**。依据是 P 所引论文 §3.2 明确列名 GNO 为研究对象、BTC 为参考；没有查看新成交量、价格或收益，也没有挑表现最好的论文资产。GNO 是这次普通配置选择，不声称优于其他论文资产或现在仍低流动性。未比较第二目标。P 两文件 SHA-256 已核相符，未重复其经济综述。[论文方法](https://link.springer.com/article/10.1007/s10690-026-09589-z)

| 元信息核验 | 实际结果与限度 |
|---|---|
| OKX GNO-USDT spot、GNO-USDT-SWAP、BTC-USDT spot | 纯 `/api/v5/public/instruments` 各一次 HTTP 请求均 403。不能推出未上市、已下架或历史无数据；目标/参考的 OKX 上市与共同覆盖均 UNKNOWN。此前 web 打开该 instrument URL 亦失败。 |
| 唯一备用：Binance 官方 spot 归档 | GNOUSDT、BTCUSDT 的 2026-01、02、03 月 `1m` ZIP，六次 HEAD 均 200，总压缩长度 9,279,074 bytes；仅响应头，无 ZIP body。历史文件存在不证明每分钟连续、历史可交易资格、当前市场 active 或实际可成交。精确 URL/长度/Last-Modified 在 metadata.json。 |
| 低成本交易/报价证据 | GNO March spot trades ZIP HEAD 200，1,680,442 bytes；同月指定 spot bookTicker ZIP 路径 404。只说明此路径无对象，不宣布全世界没有 BBO。未搜索第二归档供应商、未下载 trades，历史 arrival/报价/容量/价差仍 UNKNOWN。 |
| 市场类型 | 本次备用明确是 Binance spot，不能拿它充当 OKX perpetual。论文正文只写 Binance API，脚注链接交易所主页；未得到作者 endpoint/完整源清单，故“与论文完全相同的 spot 产品”仍属推断。Binance 官方月报有 GNO 历史上市描述，但未据其确定精确首日。 |
| mark/funding | 选定 spot 路径不适用，不填零；若改回永续，需要另核其 mark/funding 同窗、结算与发布时间，当前均 UNKNOWN。 |

归档 [官方说明](https://raw.githubusercontent.com/binance/binance-public-data/master/README.md) 支持 spot `1m`，daily 次日发布、monthly 月初首个周一发布，2025 起 spot 时间戳改为微秒，并可能更正归档。源格式有 open time 与 close time；不能把对象 Last-Modified 当历史信号到达时间。[REST 文档](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market) 按 open time 标识 K 线，UTC 为默认；[WS 文档](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/ws-streams/~) 提供 closed 标记与 event time，1m 更新间隔标为 2000ms，这不是到达延迟上界。必须在两资产均 closed 且已到达后决策；月度 CSV 不保存历史接收时点。此次未连接行情 WS/REST。上市辅助来源：[Binance 2021 年 9 月月报](https://www.binance.com/en-AU/blog/community/421499824684902835)。

**只检验一条路径**：两资产共同 S `[2026-01-01,2026-02-01)`、D `[2026-02-01,2026-03-01)`、H `[2026-03-01,2026-04-01)`，UTC、右端开。这只是元信息碰撞探针，不是冻结实验、不涉及新读值许可，训练/preroll 尚未获资格。

| 输入/阶段 | 已知交集 |
|---|---|
| GNO，S/D/H | 所查有限 ledger/index 的资产元字段未发现 GNO 记录；外部未登记 UNKNOWN，不能宣称全球未见。LINK/SOL 等别的币同日期保护不机械扩展给 GNO。 |
| BTC，S | ledger 第 49/51/52 行给出 BTC lagged-pressure 的 S `[2026-01-01,2026-02-01)`，已执行消费，与本探针 S 全交。ledger 此记录未完整列 venue/market，不能谎称就是 Binance spot 同文件。 |
| BTC，D | 同 cohort 保留 D `[2026-02-01,2026-03-01)`，全交。另经 LTC consumption index 元信息确认旧 Issue #45 BTC-USDT-SWAP D `[2025-09-01,2026-03-01)` 已物化/保留，覆盖本 S+D；本次只读索引和其 window-spec，不读源数据或结果。 |
| BTC，H | ledger 第 48 行记录 `[2026-03-01,2026-04-01)` 已做 source coverage/continuity、未做信号/经济研究。不是新盲 H；接触层需由原保护合同界定，不将 QC 等同经济消费。 |

BTC spot 与旧 swap 的产品不同，但不能据此自动重置同一 BTC 信息过程的研究接触或旧保护。**精确证明的是时间/资产接触交集；Binance spot 的字节同一性与跨市场资格尚未清除**，故没有合格共同路径。本结论未穷尽所有历史/未来窗口，也未证明不存在其他合法路径。BTC/ETH 2020–2024 探索及 2025 外层封存仍保留；未改用它们的 1m 或其他交易所来制造独立。H 若改为未来，不因尚未完整而否决可合法开展的历史 S/D，但必须在值前封存、单独授权。当前不另提新窗口。

实际代码盘点（全部静态）：新工作树 detached、干净，HEAD 和 `git ls-remote origin refs/heads/main` 均 `0ace04b7c10ea35fb8ce6f25e043ac78be87c19e`；指定 native HEAD `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`。无活动 Issue 开发，本次没有 GitHub 写入。

原生下载/格式能力与 lab 分开：native `freqtrade/exchange/binance_public_data.py:40–96,203–213,275–292` 已有 spot `daily/klines` 下载、UTC 日期转换及微秒转毫秒，输出标准 date/OHLCV DataFrame。因此不用自制回测 runner 或改 native；但本次 HEAD 核的是 monthly ZIP，未核每个 daily 对象，也未运行下载/格式消费，native 官方入口真正的 end-to-end 成功仍 UNKNOWN。

- **1m/市场契约**：`lab/bounded_strategy.py:66`、`lab/bounded_research.py:177,616`、`lab/codex_generation.py:511`、`scripts/run_freqtrade_backtest.py:584,844,907,1111` 的周期、步长、OKX futures/linear swap 约束都要贯通。现有 producer 是 OKX 路径，不能直接塞 Binance CSV 或伪装 swap。spot 应明确取消不适用的 mark/funding/tier 要求而保留来源/市场真实性验证，不是删除校验。
- **确有 schema 范围阻碍**：`sql/schema_v1.sql:4` 将 domain 限定为 `OKX_CRYPTO_PERP/OKX_STOCK_PERP`，`:6` 强制 `trading_mode = 'futures'`。timeframe 是自由 TEXT，exchange 仅默认 okx，单加 1m 本身不需迁移；双源/校准证据可复用现有 JSON。但诚实保存 Binance spot Profile 必须改变已有 CHECK、处理现有数据库 schema 兼容，不能仅靠应用枚举或 JSON 绕过。也涉及 `lab/search_campaign.py:576`、`lab/backtest_artifact.py:39–42,680,1199` 的验证及 native 工件导入。当前禁止 schema/migration，故此最短完整 lab 路径在本授权内不成立；无须改 native 或建设通用市场引擎，但需要另行明确的产品范围变更。
- **单参考**：native `informative_pairs`/DataProvider/同周期 merge 能复用；但 lab runner `:1469–1479` 仅恢复一个 OKX 市场且强制市场集合等于交易 pair，参考市场尚未接入。需要只允许一交易资产+一非交易参考，双源 hash/周期/窗口/closed/缺失/陈旧检查，拒绝无限 ffill，确保基线与增量使用相同有效时点。native 同周期按 open time 合并、信号后移一根并不证明网络到达可成交。
- **一分钟退出**：`bounded_strategy.py:245–251` 接受有限负 ROI；native `backtesting.py:666–671` 对 `roi == -1` 且 minute key 是 timeframe 整倍数使用当根 open。故 1m 下 `{"1": -1}` 是可复用候选，不需新 trade-age/custom_exit。`interface.py:1712` 仍要求利润大于 -1；`:1458` 的 `ignore_roi_if_entry_signal` 可抑制 ROI，`:1493` 起 exit-signal/stoploss 优先于 ROI，native entry `backtesting.py:1313` 排除同侧 entry+exit 冲突。协议要冻结开关、止损、再入场和非到期退出规则；正常正价 spot 在 minute 1 到期退出是静态推论，未跑原生验证。不能用 `{"0":0}` 造成即入即出，也不称所有交易必定恰好 60 秒。
- **估计器是真实缺口**：模板只允许三个 populate、少量 ta/rolling/shift 和算术，不能运行 LightGBM fit、导入模型或任意训练循环。忠实论文交易模型仍需固定特征/标签、按时间训练与模型冻结/预测接线；不因 native 有 ML 功能就宣称 lab 已支持。若选滚动线性投影，自身收益基线与加入 BTC 的嵌套回归可保留条件增量问题，但这是新推论；部分均值/乘积运算已有能力，尚需核奇异矩阵、缺失、样本不足、标签成熟、512 lookback 上限与 AST 预算，不能为了省事选择 512 或用任意同向阈值冒充模型。
- **更轻的可行能力方向**：独立校准窗只拟合一个预注册小模型，导出固定系数为 series×有限 numeric literal 的表达式；`bounded_strategy.py:607–630` 已允许这一算术形状。这样 native 预测无需 fit、模型服务或 ML 平台；校准窗可以长于预测时的 512 lookback，因为固定后的预测仅需规定 lag。但仍要在 S 之前单独取得双资产校准值资格、记录准确校准窗口/标签成熟 cutoff/purge、数据和拟合代码 hash、数值条件/失败规则、每个基线与增量的拟合次数、导出系数和源码 hash；不能先用 S/D 拟合再声称它们独立。该方向保留自身历史条件下的 BTC 增量问题，是新模型推论，不是论文 LightGBM 复现。本次只评估能力，未创建模型提案、参数、拟合或源码。

**收窄的工作量判断**：取消“必须新退出回调”这一项，固定系数预测也不需训练平台。若以后先清除双资产资格且另行授权 spot schema 范围，1m+双源约 6–10 小时、spot producer/consumer/市场恢复约 6–10 小时、一次校准与 literal 导出约 2–4 小时、因果/失败/native 入口验证约 4–6 小时，**已识别工程子项合计 18–30 主动小时**。现有 DB schema 兼容/迁移另属未授权范围，代价 UNKNOWN，不能把这个小计说成完整交付承诺。坚持 LightGBM 还会增加训练/绑定工作；没必要先走这条。数据 QC、计算和日历等待均单列 UNKNOWN。当前可执行下一门是监督在值前裁定 BTC 跨市场接触合同与是否将真实 spot schema 支持纳入后续独立 Issue 范围，再决定是否写固定系数模型协议，约 1–2 小时审阅工作；本任务不新建 Issue/协议/模型，也不主动迁移、解封或另找币。若不接受 schema 范围，本候选在当前 lab 边界内停放。

若该门以后清除，协议仍须补齐：目标/参考 venue/product/资格与原始来源快照；共同 S/D/H 和双资产训练/preroll、清洗/缺失策略；一个估计器及全部固定超参数、自身基线和仅增加 BTC 的嵌套特征；标签相对 closed/arrival/首个可成交时间的位置、训练 cutoff/purge、持仓/再入场/止损；名义额、费用等级假设、每边滑点、日界限、最小样本/增量判据及停止规则。所有字段要值前约定，不在这里编造无依据参数。

成本/延迟敏感性应作为**事前固定诊断**：一个主要假设成本场景和一个更严格的单因素成本场景可在同一冻结成交序列上做成本重计；该重计仅为诊断，若费用会改变交易/容量/退出就不能代替新 native。额外一根 1m 信号延迟会改变成交，应单独占执行预算；若预算总共只有一基线+一增量两次，则先选定一个保守延迟作为主实验，其余延迟不在本轮执行。不能用“2 次”包装 16 格模型/lag/费率搜索。小于一分钟的真实延迟无法由 1m open 精确重放；OHLC 的冻结假设成本实验可有限否证，正结果仍需报价/arrival/容量补证，不能称实际可成交或 DATA_READY。

接触与操作：仅仓库/native 静态文本、P、列明元索引与一个 window-spec、官方说明/搜索/HEAD/instrument 请求；JSON 在内存解析后按显式元字段投影，未输出 results、limited_mechanism_diagnostic、trades 或绩效。网页工具返回过文档示例和不相关搜索摘录，未把其中行情数字当实测或筛选依据。未请求任何行情 REST/WS、未下载市场文件、未打开任何 DB/保护行情/结果、未创建 Candidate/ResearchRun/配置/runner/服务，未运行测试或 native，未更改 ledger/GitHub/代码。只写本 Git 外 0700 目录两文件。原 checkout 和 Freqtrade Ai 未触碰。model/reasoning/Fast 为委托要求，实际服务档位未回传，保留 UNKNOWN。
