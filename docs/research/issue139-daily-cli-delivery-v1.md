# Issue139 离线日增量 CLI 交付 V1

授权：[纯合成实现裁定](https://github.com/He1met/freqtrade-lab/issues/139#issuecomment-5580463458)。本轮新增一个入口 `scripts/spot139_daily.py`、一个模块 `lab/spot139_daily.py` 和定向测试；不改冻结 B V3 代码、信号/成本/风险/dust 语义，不读市场价格，不创建真实前向运行根或窗口登记。本入口仅接受 `SYNTHETIC_ONLY`，不提供真实网络或 native 执行模式；人工示例不是前向结果或盈利证明。

## 可运行入口

```sh
# 首次使用一个不存在的新目录；目录已存在时拒绝覆盖。
PYTHONDONTWRITEBYTECODE=1 uv run python scripts/spot139_daily.py demo --root /tmp/issue139-daily-synthetic-v1

# 只验证初始完整状态及已验收人工日包，不创建输出、不推进模型。
PYTHONDONTWRITEBYTECODE=1 uv run python scripts/spot139_daily.py check --state /tmp/issue139-daily-synthetic-v1/initial.json --day /tmp/issue139-daily-synthetic-v1/fixture-85.json

# 相同已提交 key：NO_OP_COMMITTED，不重算，不调用 transport。
PYTHONDONTWRITEBYTECODE=1 uv run python scripts/spot139_daily.py apply --root /tmp/issue139-daily-synthetic-v1 --state /tmp/issue139-daily-synthetic-v1/initial.json --day /tmp/issue139-daily-synthetic-v1/fixture-85.json
```

`demo` 生成85个人工warmup日及4个人工观察日，独立推进base/stress共享两币的钱包。它还给出真实输出路径；不指定root时只使用临时目录。手动增量用 `init --state <人工初态文件> --root <新目录>` 初始化，再用 `apply --state <上一已提交state.json> --day <下一人工日包> --root <同目录>`。`check` 是明确的check-only子命令；入口没有可切换成真实前向的参数。将kind改成REAL_FORWARD会在创建目录/读日包之前拒绝。

日包固定两币、UTC日号、小时open/high/low/close的Decimal字符串、full标记、收到小时及候选SHA；缺小时可以显式不存在，不补齐价格。received_at_hour必须晚于该日闭市；重复/越日小时、未来或未闭日、坏OHLC、候选不符先拒绝。实际computed_at_utc保存在每日receipt，attempt另记实际UTC；结果注明event时点、接收时点和 `DELAYED_OBSERVATION_SYNTHETIC`。人工日号不是登记过的市场日期。

## 完整状态与提交语义

以可审查的JSON标签保存Decimal、tuple、set、保留整数键的dict及仅四种白名单dataclass（Wallet/Rule/Episode/SpotResidualV3），不用pickle。保存完整模型的所有dataclass字段：现金/库存/费用、peak和10/15锁存、basis及累计成本/释放/收入/realized、armed/active、residual、pending/exits、seen_nonpositive、warning_pending、started/stops、marks/age、block/execution_error、全量fills/events、last_hour。还保存两币完整指标日历、前一日小时条（跨午夜completed-low）、warmup/评分/外部终点/下一日和共同停止原因。反序列化不调用会重置episode的`__post_init__`；版本/候选SHA、字段缺失、未来日历、规则/成本、钱包不守恒先拒绝，写新状态前再验证一次。

候选SHA由旧model与residual代码的固定文件SHA生成；启动先对照冻结字节。wrapper新版本为 `SPOT139_DAILY_SYNTHETIC_V1`。两个成本共用唯一日输入SHA，各自钱包/订单/风险状态独立。85连续完整日依赖就绪后才建立score_start；不足时不交易、terminal为null。外部终点仍为warmup_start+265日，延迟就绪会缩短评分期，不延长或筛选窗口；180天不是样本充分性承诺。

单writer锁内验证完整提交链，按候选/上一状态/日输入身份提交。每个attempt在模型前耐久记账，保存输入原始JSON；完整`input/result/state/receipt`写入attempt目录并fsync，随后单次rename到`commits/<day>`，不存在可见的半天结果。所有历史输入和失败目录保留。提交前中断只允许从同一上一状态、完全相同输入恢复；提交后中断，commit目录已是权威，重复命令校验SHA后no-op，不因缺尾部COMMITTED事件重复记成交。收到另一版本（包括改变received_at）不能覆盖已提交日，也不能换输入来救未提交批。

每个正常有评分日最多base/stress各一次；warmup只写指标，0个COST_STARTED。记录RESERVED与COST_STARTED分别说明预算保留和实际模型调用；未提交批每次恢复保守保留2个成本槽，总额6（最多3次双成本恢复），失败不退。会计/控制错误记FATAL，停止共同观察，不能当普通技术恢复绕过；任一成本观测DD>20%时两条成本在同一个小时完成后共同停止，不挑另一成本继续。10/15规则原样保持。终点不虚构卖出，保留库存与估算退出费。

## 可注入离线请求计划与单桶计数

`request_plan(first_missing,target_day)`只生成旧合同的GET api.binance.com exchangeInfo及两币1h klines请求（精确日start/end、limit24）；包含当前目标日在内的待收日必须1–3个。它不是下载器或网页核接口工具。`offline_request`只允许明确offline的注入transport，且安装既有网络拒绝audit hook；无默认HTTP实现。

每个真实调用**离线transport**前append一个ATTEMPT，键含固定请求及数据日。目标当日的首次请求属于normal；较早缺日、或同key首次失败后的重试属于recovery；同一次尝试绝不进入两桶。旧缺日当天未用的normal份额不回填。状态SUCCEEDED/FAILED不是第二次计数；失败不退额。normal总上限795、recovery总上限12，metadata不获得同key重试；缓存字节/SHA有效则不再调用transport，漂移/无完成收据则拒绝。当前目标日只能在有限日历内，first_missing必须等于当前next_day；不能滚动改名绕过三个待收日界。

256KiB metadata/64KiB klines响应上限和固定请求校验已在离线transport路径检查。**20秒HTTP超时、180秒真实任务超时、HTTP状态/真实交易所规则语义校验及跨真实授权登记的绑定仍没有网络实现**；本轮以抛TimeoutError的离线transport检查失败收费。807 GET/100.125MiB/47700秒仍是未授权提案，不能凭这些离线接口启动采集。以后只有监督裁定实际日历/登记/有限采集后，才可补上针对该授权的薄source准入，不能让kind开关自行授予权限。

## 验证与失败披露

42项定向测试通过：新17项，既有V3/归因25项。包括独立的原始连续小时循环与本日适配器分日重启精确比较全部模型字段/订单/现金/库存/成本/风险；再比较每日日志和完整状态。覆盖85日缺依赖后延迟就绪、午夜00信号到01成交、跨午夜上一小时low、待退出无open到下一小时、全缺日与迟到拒绝、dust再入、10/15锁存、单成本20%共同停止、终点库存、提交前/后故障、恢复同输入和6槽上限、会计破坏/FATAL、跨writer锁、版本/SHA/字段漂移、输出篡改、重复no-op、12次源恢复和每attempt单桶归属。

真实CLI合成demo/check/apply-no-op均运行成功；check/no-op前后根目录全部文件SHA一致，REAL_FORWARD输入被拒且目标目录不存在。首轮测试有一处人工预期错误：把两币各一笔买入计成一个时间项，实际应有两个同小时项；修正测试断言，未改候选行为。后续42项全部通过。测试/demo全部使用人工数字及临时路径，不实例化Freqtrade、不访问真实数据或DB。

本轮旧global/所有旧调用账本SHA保持；32native、112既有采集GET、旧封存和API暂停不变。新增市场计算/native实例/来源GET/文献检索/付费/真实交易/自动化均0；合成模型调用和离线transport尝试明确属于工程测试，不冒充市场证据。

## 下一机制的历史去重结论

只读核对 `docs/discovery/issue135-batch-v1.json`（SHA `eb9fc1c4c0f3dcb9aa0277c55b7f2baeceabb13e9f734fc6f19826d69b74b26a`）、`docs/issue135-delivery-receipt.json`，以及已关闭Issue135/已合并PR136。现有两张卡为crypto-basis-carry与cross-venue价差；实际知识卡2、当前执行兼容0、收益/样本未知。carry需现货/期货双腿、融资保证金；cross-venue需双场所库存、同步成交、转移/提现约束。

前向方案第6节提出的“跨场所现货价差收敛/预置库存换仓”与既有cross-venue卡同族、同执行阻塞，不是新信息。**撤回其作为下一文献切片的建议**；旧冻结方案文件不覆盖，本交付记录该纠错。不要重新研究已知多所/低延迟障碍，也不凭“套利”二字称天然互补。本轮只附去重结论，未另选/研究新机制、未查互联网/新Issue；B前向依赖验收后，下一域须先排除既有机制指纹且适合单场所小时/日级个人维护，再由监督冻结唯一发现切片。

本切片的下一依赖已交监督：审阅固定代码/检查结果后裁定真实日历、窗口登记和有限采集；当前只支持人工合成输入，不将工程PASS或预算上限当独立资格。PR140继续draft，Issue139继续open，不自行merge/close。
