# Issue139 REAL_FORWARD 来源/准入交付 V1

授权：[实现与离线验证](https://github.com/He1met/freqtrade-lab/issues/139#issuecomment-5580709977)。本轮只实现固定包，未登记、未发真实来源GET、未初始化真实运行根、未计算市场前向收益。旧32 native/112 GET、封存及API暂停保留。外部grant模板`authorized=false`；提交代码或check通过均不授予运行权。

## 固定包与第一段

- Manifest：`docs/issue139-forward-v1-manifest.json`，SHA `7576da10d07642d3e4e791492514bc1e84b89b9746b608cdbd91c2a6471522e1`。文件采用canonical JSON字节，文件SHA与grant使用的canonical manifest SHA一致。
- 首7日模板：`docs/issue139-forward-first7-grant-template.json`。监督另在Git外形成真实grant，提供其文件SHA；模板不可执行，不自授权。
- 固定W=2026-09-09 00UTC（日号20705），S0=2026-12-03 00UTC（20790），E=2027-06-01 00UTC（20970）。唯一run_root为manifest所列`issue139-forward-v1`，本轮不存在。首次init必须真实发生于W之前，授权及登记时间也须早于W；错过则拒绝，须监督在未读价格前公布新日历，代码不从当天滚动推算日期。已初始化后的后续grant不改W/S0/E、候选、成本、metadata/rules SHA或根目录。
- 第一段数据区间`[2026-09-09,2026-09-16)`，最多21 normal GET、0 recovery GET、0评分/恢复成本更新、7数据日、2752512预留字节、1260预留活跃秒。首日只在09-10 00UTC闭市以后处理，建议00:10（北京08:10）；第7日09-15在09-16处理。init不额外取metadata，第一日的1次metadata同时承担启动规则绑定。
- 全期硬上限795 normal+12 recovery=807 GET、104988672字节（100.125MiB）、265数据日、47700秒（265×180）、360正常成本日更新+6恢复成本更新。grant可以更窄，全部字段是**累计上限**；扩到前14日应扩大累计额度而不是重置账本。若恢复获准，单独增加recovery子额且仍从总12扣。按响应上限保守预留全部字节、每实际日任务保守预留180秒，失败/中断不退；另记实际读取字节与耗时，不把预留量冒充实耗。

## 实际命令

现在可执行check-only；只读代码绑定、manifest中的控制元数据，若传grant还只读精确登记记录；不读运行状态/新价格、不建根、不登记、不联网：

```sh
PYTHONDONTWRITEBYTECODE=1 uv run python scripts/spot139_forward.py check --manifest docs/issue139-forward-v1-manifest.json --manifest-sha256 7576da10d07642d3e4e791492514bc1e84b89b9746b608cdbd91c2a6471522e1
```

以下是监督**随后**启用的命令结构，本轮没有执行真实init/daily。`GRANT_PATH`/`GRANT_SHA`必须替换为监督实际发布的Git外授权文件和SHA，不能使用false模板：

```sh
PYTHONDONTWRITEBYTECODE=1 uv run python scripts/spot139_forward.py init --manifest docs/issue139-forward-v1-manifest.json --manifest-sha256 7576da10d07642d3e4e791492514bc1e84b89b9746b608cdbd91c2a6471522e1 --grant GRANT_PATH --grant-sha256 GRANT_SHA

# 2026-09-10 00UTC之后，处理此前已闭的09-09数据日。
PYTHONDONTWRITEBYTECODE=1 uv run python scripts/spot139_forward.py daily --manifest docs/issue139-forward-v1-manifest.json --manifest-sha256 7576da10d07642d3e4e791492514bc1e84b89b9746b608cdbd91c2a6471522e1 --grant GRANT_PATH --grant-sha256 GRANT_SHA --data-day 2026-09-09
```

`check`不带grant返回`PACKAGE_CHECK_PASS_EXTERNAL_GRANT_AND_REGISTRATION_REQUIRED_NO_IO`；带有效grant返回`GRANTED_PACKAGE_CHECK_PASS_NO_ROOT_OR_SOURCE_READ`。init以临时目录完整构造，再原子rename成固定根；同合同已有根只校验并no-op，不重置钱包/预算。真正每日运行复用已有`spot139_daily`状态/小时计算/原子日提交，不复制策略引擎。

## 外部授权/登记结构

监督提供的grant至少绑定：authorized=true、实际GitHub授权评论、authorized_at_utc、manifest_sha256、candidate_sha256、rules_sha256、精确run_root、start_day/end_day、cumulative_caps全部字段、registration_path及其精确SHA。首次start/end与caps使用首7日模板；后续仍是同manifest同root累计计数。模板保留`resume_stop_sha256=null`。

外部控制账本必须已有且只有一条精确匹配的JSONL登记：record_type=`ISSUE139_REAL_FORWARD_REGISTERED`，campaign=`ISSUE139_B_V3_FORWARD_20260909`，manifest_sha256、window={W:20705,S0:20790,E:20970}、candidate_sha256、rules_sha256与manifest一致，registered_at_utc为W之前的真实登记时刻。代码仅核验这条登记，绝不自行写全局账本。账本SHA漂移先拒绝；监督续授时可绑定最新账本SHA，但重复登记、倒填时间或新目录不提供预算重置权。

## 来源与真实/合成隔离

旧合成V1默认入口仍仅收SYNTHETIC_ONLY。真实状态使用`SPOT139_DAILY_REAL_V1`、REAL_FORWARD及source_contract_sha256；真实日包还带两币和metadata的原始响应收据。声明类型或合同SHA不匹配先拒绝，不把真数据改label送入合成入口。内部共用同一Decimal模型、完整状态与原子提交；两种输入的存储版本/来源边界分开。

只用Python标准库公开GET `https://api.binance.com/api/v3/exchangeInfo`（两币）和`/api/v3/klines`（每币前一完整UTC日、1h、limit24、精确start/end）。无key、cookie、认证、账户API、其他host、重定向或SDK；空proxy映射不继承环境代理凭据，TLS使用标准验证。没有启动旧collector或修改系统网络。HTTP总墙钟20秒、整个日作业180秒，以嵌套SIGALRM/setitimer强deadline覆盖阻塞open/read；单writer、每次新attempt前至少sleep1秒（含跨进程，避免墙钟校正缩短间隔）。本实现依赖macOS/Unix主线程信号，非后台线程/Windows服务。

每次GET前fsync预记ATTEMPT及其单一预算桶/最大字节预留，失败不退。metadata≤256KiB、klines≤64KiB，Content-Length超限在读body前拒绝，流式读取到上限即停止，不为判断超限再读额外字节。301不跟随，429/418及所有非200/压缩编码/坏结构/超额/实质规则变化停止。临时网络/Timeout结束本次任务并保留计数；同日同grant已STARTED且未完成的再次heartbeat返回`NO_OP_ALREADY_ATTEMPTED_TODAY`，不重试HTTP或模型。下一闭日只有包括当前目标在内最多3待收日、仍获准的recovery额才可恢复。超过3日快速拒绝，不无限补历史。

成功的source body/receipt成组原子提交并保留原版本；缓存命中核SHA，不下载。metadata每个实际任务先验证，忽略serverTime/rateLimits等非订单身份字段，只比两币交易状态、SPOT身份、精度、orderTypes和全部订单filters语义；数值字符串规范化，不因尾零误判。metadata预期来自已获准历史metadata控制源（001-exchangeInfo，未读任何kline）；与模型使用的lot/tick/min/max/commission假设一起冻结。第一份新metadata必须匹配，先原子写新观察期baseline及该原始响应SHA，再发第一笔价格请求。规则变化不能静默迁移，即便导致启动BLOCKED_CONTROL也保留；不能把模型假设说成真实账户费率或保证订单实际可接受。

缺一币响应就不生成/提交该日双成本包；已收到的另一币原始响应留cache。HTTP200但缺/短小时显式作为缺口进入完整日门，不填价、不压缩85日。接受日包也原子落盘，恢复必须核对原始响应/解析出的bars/合同并使用原有接收版本；不替换已提交轨迹。warmup仅构造日历/指标，0交易调用、0成本更新；准备完85连续完整日后下一数据日才从1000/flat/无旧pending/峰值1000开始score。首次评分日的计算仍发生在次日收件后，是DELAYED_OBSERVATION_REAL，不证明实时01点成交或实时stop。

普通有评分日最多两成本更新，恢复仍同输入/同上次状态、共6成本槽。修正了旧合成wrapper对warmup恢复也预留2成本槽的过度收费：现在warmup恢复0交易调用/0成本槽，仍受任务、请求和日历上限约束，不需为0评分的首7日偷开交易额度。15%锁存仍禁新买；任一成本>20%停止共同观察；E不顺延、不强制清仓，预算和180天不提供统计资格。

预算耗尽造成的停止需要监督新grant明确绑定`resume_stop_sha256`并给出仍在总上限内的累计额度才可解除，旧停止文件按SHA留档；metadata/来源实质错误不可用此字段自动恢复。模型共同风险或有限日历停止也不可恢复。不会因收到另一份grant就清掉历史账本。

## 离线证据与当前阶段

63项定向测试通过（新来源21项、既有daily/V3/归因42项）。注入离线HTTP或本地人工OHLC，真实网络0。覆盖301、429/418/500、流式/Content-Length超限、实际信号deadline中断与attempt收费、deadline已到时0attempt、missing ETH双轨迹不提交、metadata变化/缺字段、W前/E后与子段外拒绝、过W不能init、版本/来源混用拒绝、85 warmup日0交易及首次score00→01、睡眠3日延迟/4日拒绝、单桶计数、重复no-op及累计grant不重置。原17项daily与25项V3/归因回归保持通过。

实际check-only已运行，返回包检查PASS；随后检查固定真实root不存在。false grant模板也会在任何根创建或价格读取前拒绝。初轮一个离线metadata变化fixture因浅拷贝意外同时改了manifest，被合同SHA门正确挡住；已改为深拷贝响应以单独测试metadata漂移，未放宽任何规则。旧核心及所有调用/global账本SHA核对保持；本轮市场GET、native、真实前向经济计算、登记、实盘/付费/新automation均0。

下一项交监督审阅该固定包，然后由监督选择是否在W前登记并启用首7日。现有30分钟heartbeat可每日调用一次，已提交日及同日重复唤醒no-op；不另建automation。PR140仍draft，Issue139open，不自行merge/close。
