# Issue #109 首切片验收与未执行项

2026-09-07 UTC。范围是元数据准入工程，经济结果 **UNKNOWN**。
父基线及实时远端 main：`07ea2cf4742de3d2473302dc57bf0b2283a5fbf2`。
独立分支 `codex/issue-109-portfolio-preflight`；主 checkout 未跟踪需求文档保持原样。
无原始数据库、凭据、旧服务、行情文件或原生 ZIP 访问。

## 实际状态

| 层 | 证据 | 状态 |
| --- | --- | --- |
| 版本化新合同 | JSON SHA `e664b6447879a350663fa7940036a2682d3970af65f7c218c540e2e62ff28e85`及同提交规则文档 | 工程冻结 |
| 原生预算 | 92固定key+4技术备用；每次两币；旧Search未改 | 计划可运行生成，持久预约待实现 |
| 匿名交易所规则 | 2026-09-07T15:33:33.163057Z 一次exchangeInfo GET | 当前规则已核对 |
| 实际 CLI | 固定协议+上述归一化规则；未绑定registry | `BLOCKED_DATA`，退出2 |
| 合成完整元数据 CLI | 临时registry和exchange快照 | `METADATA_VALIDATED_ONLY`，退出0，执行许可false |
| 训练池 | 未形成完整控制映射/绑定 | BLOCKED_DATA，下一步可依法登记新训练用途 |
| 组合原生/成本/结算 | 未实施 | UNKNOWN，无经济结果 |
| 训练/确认/观察 | 市场原生0、合成原生0、价格/funding请求0 | 未运行；前向start=null |
| 实盘/生产 | 无授权、无动作 | 禁止 |

匿名响应SHA `12112147f32a62d6f7c4b67a3ba25591968d46fbb37bdbc3585190629b1519da`。
此 SHA 记录当次响应身份，响应本身未纳入Git；没有将这次请求声明为完整市场源收据。

| 品种 | 最小名义USDT | MARKET minQty / stepSize / maxQty | PRICE tickSize |
| --- | ---: | --- | --- |
| BTCUSDT | 50 | 0.001 / 0.001 / 120 | 0.10 |
| ETHUSDT | 20 | 0.001 / 0.001 / 2000 | 0.01 |

两者当次PERPETUAL/TRADING、quoteAsset=marginAsset=USDT。账户地区、手续费资格、
结算舍入、历史规则不是该响应证明的内容，均未假装已确认。
[官方过滤器说明](https://developers.binance.com/zh-CN/docs/products/derivatives-trading-usds-futures/common-definition)。

## 仅控制字段的旧窗口映射

全局账快照182823 bytes，166条非空JSON，SHA
`b04a689820be336826c255ee9835b0b1db4c2fcd31bbf8f8a897c5aed9b5f90c`。
只摘控制字段，不发布经济字段、私人路径或原始账。未改写或追加全局账。

| 记录定位 | 已核对的控制内容 | 对新训练的含义 |
| --- | --- | --- |
| 行33、37–43 | BTC informative / ETH primary；2026-04-01—05-01；旧D预留05-01—05-31；随后同范围Search终态；06-01—07-01另有终态 | 已消费/曾预留都需保留来龙去脉；不能靠交易所更名宣称独立；预留是否解除需精确证据 |
| 行56 | `dual-momentum-btc-eth-2024-v1`，NO_FINALIST | 名称只提示2024暴露，不单凭名字猜精确合法日历 |
| 行142、148、150 | BTC现货训练源2024-01-01—12-31，评分01-30—12-31 | 已见学习披露；不是Binance两币永续来源收据 |
| 行155及后续SOL记录 | SOL S/D/H保留及风险拒绝 | 旧值不碰；不将其它资产日期机械扩成BTC/ETH禁区 |
| 早期不完整记录 | `HISTORICAL_DEVELOPMENT`等 | 完整限制范围尚UNKNOWN，不构造假的全局无冲突证明 |

这不是完整全局登记器。当前缺的是**新训练池绑定**，并非用户禁止历史训练。
未登记且未受保护的历史可在本次授权研究域内、首次价格读取前登记为新训练用途，
冻结日历、来源、采集预算和学习偏差。24月是设计建议，不为凑数移动保护窗。
后续应补齐具名限制，然后登记明确窗口；本 Issue 不下载该窗口价格。

## 测试和真实入口

环境：macOS arm64；系统 Python3.9.6入口可用；uv0.11.7；测试 Python3.13.13。

1. `PYTHONDONTWRITEBYTECODE=1 uv run --with pytest python -m pytest -q -p no:cacheprovider tests/test_portfolio_preflight.py`
   → **35 passed**，0.23s。
2. 同命令加 `tests/test_single_baseline.py`
   → **46 passed / 2 skipped / 1 failed**。旧producer导入缺`ccxt`，环境缺依赖，
   不是经济失败；首次失败保留。
3. 固定依赖同范围回归：

   ```sh
   PYTHONDONTWRITEBYTECODE=1 uv run --with pytest --with ccxt==4.5.68 \
     --with pandas==3.0.3 --with pyarrow==25.0.0 python -m pytest \
     -q -p no:cacheprovider tests/test_portfolio_preflight.py tests/test_single_baseline.py
   ```

   → **48 passed / 1 failed**（18.93s）。旧producer另需`freqtrade`导入；仍是环境缺依赖，
   当时已通过新增35项及旧13项，完整旧T2集成未验证。保留失败，不修改测试。
4. 同一命令再加入 `--with freqtrade==2026.7`：**49 passed**，31.43s，12项旧pyarrow弃用警告。
   所有环境依赖在隔离uv环境；无工作区依赖文件修改，无真实原生市场调用。旧T2也通过。

真实CLI检查：读取当次归一化exchange快照、没有registry，返回BLOCKED_DATA及：
REGISTERED_SEEN_TRAINING_POOL_MISSING、SHARED_WALLET_NATIVE_INTEGRATION_REQUIRED、
RAW_SOURCE_QC_REQUIRED、SETTLEMENT_PRECISION_REQUIRED、PERSISTENT_BUDGET_RESERVATION_REQUIRED。
计划92、备用4、最大96；本入口实际调用0，全局已消费数null（没有预算账验证，不编造0）。
`market_data_ready=false`、`market_execution_allowed=false`、经济结果null。
合成集成真实启动CLI证明退出0也不发许可；错误/缺文件不泄漏私有路径，无输入文件变更。

T0/T1新合同、失败边界及相邻预算回归；T2临时控制文件+真实CLI。
未运行全量市场/E2E，因为无native/data/DB/服务变更。本次回归临时SQLite由旧测试工厂建立，
没有使用工作区DB。schema原SHA
`f695ab0e0c778332b6f520bc554c14ab792f16f105fa0b6f6e6d3fb432d249a1`不变。
所有测试值由代码合成，无新市场fixture提交。

## 交接

PR按固定SHA交监督审阅，Issue保持OPEN直到验收。回滚为revert本PR，不改变旧数据或预算。
KEEP六表/原生来源和成本边界；SIMPLIFY薄入口与固定合同；无删除、无通用状态平台。
首切片之后继续受控共享资金模板和原生合成证明，再完成机器成本审计与登记来源；
长时确认只能等待真实日历，不能把工程完成冒充总体研究目标完成。

## 固定SHA监督复查修正

初版a460dea的工程协议SHA为
`4e3d107e3d0533bff1f05df6af893aab477cffbf8b9a8317503e0d7480c2de93`。
监督固定SHA检查独立35项通过，但指出两个研究合同问题，已在首次评分前纠正：

- 最终参数不再要求每折net>=0。每UTC日期对可用训练折日收益等权平均，
  每日期只计一次，复利训练选择净额>=0后按效用排名；来源/因果/成本及各折DD硬门不变。
  这是重叠训练的选择统计量，不是实际共享账户路径。各折亏损与样本保留。
- C必须同时相对原B和半风险B具有正效用增量且各95%区间下界>0；半风险B仅较低风险对照。
  C=B时必因vs原B差0不晋级，不能用胜过0.5B伪造动态能力。

新JSON、文档、源码固定hash与合同防退化回归同步；没有新增市场/统计引擎或扩大96调用。
当前协议SHA见上表，36项新模块/真实CLI回归通过（0.16s）；原相邻SingleBaseline逻辑未再修改。

下一依赖源码定位：官方安装包Freqtrade2026.7，`freqtrade/optimize/backtesting.py`
共享wallet初始化307–308、策略绑定343，position调整715起，stake回调1099起，
`freqtrade/wallets.py`已实现收益汇总118–122、stake权益计算292起。
本地隔离包位置由import只读查得，后续原生执行仍需核对锁定Git源码commit，不用安装包路径冒充Git身份。
这一步仅import/读接口，没有Backtesting实例化或start调用。

## 文件身份（修正后提交前校验）

| 路径 | SHA-256 |
| --- | --- |
| `docs/portfolio-pilot-v1.md` | `3ce2f9647ba970366310a3df24ccdfa4ea874db757b6b7c0a0ab396b3996aa87` |
| `docs/protocols/btc-eth-portfolio-v1.json` | `e664b6447879a350663fa7940036a2682d3970af65f7c218c540e2e62ff28e85` |
| `lab/portfolio_preflight.py` | `06a3288d223c5b5122b9b26af69a48f061ba3cd0efac966ca6b480b6f6be181a` |
| `scripts/check_portfolio_pilot.py` | `a7cfbf0946deca0837d8ad1cebbf31482d254cd6ccb130c5e3f8dd266362b5dc` |
| `tests/test_portfolio_preflight.py` | `7baa05f061bb1a365f92dd99298b030b412bd76c789de29b66a5d79ff1cdd7e2` |
