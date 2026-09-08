# B V3 固定候选索引

状态：FROZEN_RESEARCH_CANDIDATE_NOT_QUALIFIED；冻结 2026-09-08T06:29:26Z，代码基点 `f3ba7849cd1f522d13d9b238a2644ea3837c8931`。唯一方案 `docs/protocols/issue139-forward-observation-v1.md` SHA `ba9f3d313ff829cee4782652213dcde19028b456d8c080df3e98a2dfe640e69a`。本文件只是必要代码/证据索引，不是可授权市场执行的 manifest。

## 可携带代码包

下列15个文件以及本索引和前向方案组成17文件代码包。导出包不包含 raw、runtime、数据库、凭据、旧采集器、旧launch/grant。固定策略代码与已消费历史复算入口保留原样；native外部依赖不复制进包。迁移到其他目录可运行纯合成检查，不能直接启动前向。

|文件|SHA-256|
|---|---|
|`lab/spot139_model.py`|`fec7ca77813ae7d526765a549fe785fe3ab95d6e66369b06205f2f81e53d8c83`|
|`lab/spot139_residual_v3.py`|`1027365f693fee313b54f2db9906e52a7692caa60f56d59e06de83a84037f9be`|
|`lab/spot139_binding.py`|`5fbca87d93b3180be355c3d02c580e2b8a0c134a26e987fe9ece77f4e62c89e0`|
|`lab/spot139_feed.py`|`cd1185b821c526e2122822aaa465f91fb85a67dba731bd89ab147beeafd7dd62`|
|`lab/spot139_report_v3.py`|`18b94f95a7772c7224fdd8aaeb7b8526c49567a24394bdfd492365da8ef3c48c`|
|`lab/Spot139Native.py`|`b7d5bee4b886b1c9730989321c43156b847d6c657cb57c94ab920a451fcc9dec`|
|`lab/spot139_native_bridge.py`|`e7a1feefe8def154b97c3c08ecfba634853a1f3ce94aa7eb1d4b6f10472dfd00`|
|`lab/spot139_native_v3.py`|`0f89b3d17f2d26395c5276c861fee595d0beb7c8baeaf4e2d7590fd88606eb0b`|
|`lab/spot139_precision_v3.py`|`9a53bf8924fa7b917578cf708f6d633e03bd1078cd040ec5b11cb92c6582501f`|
|`lab/spot139_reconcile_v3.py`|`6c1f8d18c9019b7d92d4cd6b4cbec70a34100a1321f25523595ec02cf164f5e6`|
|`scripts/run_spot139_v3.py`|`597e7067c5624092a002b7b499bea3791bca5f168ae1147d6d701534810daddb`|
|`scripts/analyze_spot139_attribution.py`|`dda1c9ccce11997e299b1d50d3ef76867dcaa422e1d3065a8ececf2e2cd53ab9`|
|`tests/test_spot139_residual_v3.py`|`b3804241713a660134d3879bfb10a4e969e9dc04506fd35ee1bfefa281e398b6`|
|`tests/test_spot139_v3_entry.py`|`f52d308e133063bb74602b343d28f0a28ee75bce7f2b71cd5ca708e12be0b378`|
|`tests/test_spot139_attribution.py`|`259e456cb401df8c1f610341f6e03854b06ed2b891e20b8175f6953cb8f15389`|

冻结实现的唯一策略类是 `lab.spot139_residual_v3.SpotResidualV3`，它依赖 `spot139_model` 的数据类型、Wallet、signal和舍入函数；该被复用模块仍含旧模式代码，但未纳入候选选择。报告 loop 调用现有 `on_hour`，不依赖 capture/continuation/source 下载模块。`Spot139Native` 是原生订单桥接占位策略，不能单独运行就宣称执行了 B 信号。

复算来源：`scripts/run_spot139_v3.py` 记录原历史单循环/预算拒绝入口，已消费不可重跑；`scripts/analyze_spot139_attribution.py` 记录已完成的归因/基准方法，固定输出目录已存在不可重复。本轮不附 grant、不调用 --execute/--run。原39源和外部环境仍是历史复算依赖，禁止移植时删门禁绕过授权。

在解包根目录可运行以下合成入口（Python>=3.10，已核验3.13.13；需要pytest；不导入/实例化Freqtrade、不读历史价格）：

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --with pytest python -m pytest -q -p no:cacheprovider tests/test_spot139_residual_v3.py tests/test_spot139_v3_entry.py tests/test_spot139_attribution.py
PYTHONDONTWRITEBYTECODE=1 uv run python scripts/run_spot139_v3.py --help
```

合成测试覆盖因果85日依赖、缺open、残余合并/再卖、10/15锁存、共享资金、精度拒绝、账本漂移、跨writer锁、超时耐久计数、重复/错误grant/worker拒绝、单循环报告、午夜归因和固定基准算术。基准算术只用人工价格，不是新增历史经济计算。本轮实际运行25个合成测试全部通过（0.14秒）；--help成功；构造错误protocol并调用真实CLI，已在validate_sources前拒绝，市场读取/native/预约均0。旧V3原manifest因终态global漂移不可再报告check-ready。

## native与源依赖

Freqtrade 2026.7，源码commit `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`；CCXT4.5.68；原已核Python3.13.13。以下代码字节在本轮只读重新核SHA，无engine启动。

|外部依赖相对位置|SHA-256|
|---|---|
|`freqtrade/freqtrade/optimize/backtesting.py`|`7afec2d7c6f924642d410ff3974bf9932982bc9cf2f8c194b266a0b8c77ebf55`|
|`freqtrade/freqtrade/persistence/trade_model.py`|`e38684b50d63f27ad68de5745bbb21756b4a7de164c7befc704bdce8befbace3`|
|`freqtrade/freqtrade/wallets.py`|`625e02dfbef5ec04137f54e697f8e1f2a79203d08a124758083159701221265e`|
|`freqtrade/freqtrade/exchange/binance.py`|`1d786db40fb8993d22345c77e6c8045fbbc602e5daaae7580dc71c90ffddeefe`|
|`freqtrade/freqtrade/util/ft_precise.py`|`0338b928d761ad076f79ce6cb49a4894723170f79d7894212504e248de6fee07`|
|`venv/lib/python3.13/site-packages/ccxt/__init__.py`|`4a04bc1da6d82c4a8249437e3680f88280e6b5065edfd06efd50d4fab82ba06c`|
|`venv/lib/python3.13/site-packages/ccxt/base/precise.py`|`8201200d010fc5dc92e6a2cc48fed22d08273e9551fd1776f6c415dcab5e5cb0`|
|`venv/lib/python3.13/site-packages/ccxt/base/decimal_to_precision.py`|`dd7237d2ef58b9d1db4c0e37f37f7bbb9ae47655daddab71c1911f52eb370b89`|

原价源身份为 Binance SPOT BTCUSDT/ETHUSDT；39源路径/请求/字节SHA的权威索引 `docs/issue139-source-inventory-v3-terminal.json`，SHA `a98336481fadd5e2a79694f8a4929f6340a36b17184e576dca99cc18e70d4552`。历史metadata源SHA `39b1adcf5d167250083ebb5eb7ad4dca59026c765989716dc4a0ceef58fe28e8`。本轮仅引用控制索引，没有读取/重新hash价格raw；39源未变的最近实际验证见已提交归因终态，不冒充本轮新QC。前向数据、未来规则snapshot的实际SHA尚不存在，必须首次获准采集后绑定，不能用旧SHA代替未来来源。

## 保留终态与控制证据

|路径|SHA-256|
|---|---|
|`docs/issue139-spot-first-batch-terminal.json`|`5a05b13f85768d05c34ddf7fc5bea542093fc746edf7e1d7adc97456e7436474`|
|`docs/issue139-v3-diagnostics-terminal.json`|`77ca44692e2b42f7cbacfd0f75d5179d625d182c86f7b0c3353db28cda048068`|
|`docs/issue139-attribution-v1-terminal.json`|`8a3b11fb284bcbefec389cb24ba5eddf4f8d9910542fb9c2d1b9a50ba95af13c`|
|`docs/issue139-v3-first-diagnostics-manifest.json`|`63c34e6d64c545ba34abaf7f05737d86087dc9fdbff3c2bb5bc9f90c4827bb10`|
|`docs/issue139-attribution-v1-manifest.json`|`c4b155afcb34b9eaf471b28838afede94e88405e8c943c3fec01a0f465a948e3`|
|`docs/issue121-scope-snapshot.json`|`4514729c0a2210f596d21572ba4acdf9bb5055c29c9883f346fd4261b829f799`|

本轮当前global SHA `f98fcacfe8a189138c5b0a98f23536aa0ed2225442ffcfd21ab96064f9a767ee`；32 consumed +10 old sealed +6 pending +48 unallocated=96。旧调用账本/结果不变，本次不追加窗口或执行记录。完整月度/经济解释在 `docs/research/issue139-attribution-v1-results.md`，本索引不重复编造评分。

本轮仅新增两份Markdown，未改候选代码、native库、结果或状态文件；可携带tar在Git外生成并核对每个成员字节。包SHA和本索引/方案最终SHA写入GitHub里程碑（避免文件自哈希循环），不是增加一层manifest。PR140仍draft/open，Issue139仍open，未merge/close。

首次独立解包检查失败于 lab/__init__.py 隐式导入未打包的 lab.database，发生于测试收集阶段，无市场/native调用。修订导出时明确省去该仓库级初始化文件，由Python命名空间包加载lab模块；不修改任何冻结策略代码，不携带无关数据库模块。初版失败tar保留，修订包另名，不掩盖该失败。
