# Issue 123：唯一V2实际数据续接

依据 [明确授权](https://github.com/He1met/freqtrade-lab/pull/122#issuecomment-5574360226)，实现并执行一次 `[2023-11-01,2025-01-01)` BTC/ETH Binance perpetual采集。原root唯一`continuation-v2`子段；新<=54GET/累计<=91、旧37attempt与7697705bytes计入同一64MiB。父时间130秒是保守收费上界，不是实测执行耗时；V2活跃时间余1670秒。

## 固定入口

`python scripts/capture_portfolio_source_v2.py prepare docs/issue123-launch-manifest.json`只读scope和父预算并生成完整启动清单；推送后原样执行其中command一次。`locked_continuation()`持同父acquisition-budget.json.lock覆盖构造、registry共享锁复核/登记、每个GET和终态写入。构造内部在工厂已持锁时不再嵌套自锁。其他worker拿不到同锁就不激活、不登记、不GET。累计V2文件已存在则永久拒绝重启；原budget原字节不改。

执行顺序为公开元数据2GET、完整BTC funding（原event/signed rate/正associated mark/有界尾页）、完整ETH funding，然后两个资产trade/mark小时源。缺字段/429/418/越界立即停，不获取2025边界事件，不retry/redirect，不第三窗口探测。新raw编号从038开始，父37记录逐字段原样复制到累计预算，原raw不复制/改写。子段只保存新响应。

运行前后复核清单本身、源/代码/解释器以及父预算SHA。此次完整仓库导入清单额外明确包含`lab/__init__.py`、其`database.py`定义；没有调用数据库函数或读取默认DB。collector不导入策略/native消费者：预算从short消费者拆到独立小模块、原API保留转导，避免不必要的研究代码导入。原启动清单与历史SHA不重写。

历史interval证据/资格/精度UNKNOWN仍不能发布source-ready；完整结构只是数据必要条件，不能用认证布尔标签代替来源证据。20native映射不激活、不retire原键，不评分。

## 验证

31项定向测试通过：含全程持锁、第二worker零副作用、父SHA漂移、funding优先缺字段停在第3个新GET、累计40/旧37行不变、成功/失败路径终态身份复核和现有预算上限/分页/半包拒发测试。

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --with pytest python -m pytest -q -p no:cacheprovider tests/test_portfolio_source_v2.py tests/test_portfolio_short.py tests/test_portfolio_source.py
```

真实采集终态随后追加；在实际GET之前不声称字段可用或源完整。

## 实际终态

[脱敏终态与36个新响应SHA](issue123-capture-terminal.json)：新36GET/累计73，全部HTTP200；新6,906,224 bytes/累计14,603,929 bytes；V2活跃35.759秒，另外130秒为原段保守记账。父37attempt及原budget字节/SHA不变，原root不改；新增登记行177在首个新GET前写入，原186369 bytes注册账前缀保持。终态manifest/解释器/父SHA复核PASS。无retry、无native、未retire任何native键。

两币各10248 trade 1h、10248 mark 1h、1281 funding事件，associated mark全部存在且为正。每个名义8h槽恰一条事件，原始时间偏离名义边界0–15 **毫秒**；这与FAQ提到的15 **秒**资格偏差不是一回事。相邻事件间隔因此不是恒定28800000ms，不对齐/重写。该结构统计不推导结算资格，也不作为历史调整日历的权威证明。

终态仍`BLOCKED_DATA / structure=PASS / historical_interval_evidence=UNKNOWN`，source-ready未发布。V2段剩18GET、全局原122门剩49GET，都不是自动恢复授权；没有继续采集。经济结果NULL，官方UI无本研究市场评分可展示。

## 本次只读官方间隔核验与下一依赖

[2023-09-28官方公告](https://www.binance.com/en/support/announcement/detail/98d6b24d3e5c4f84a8ed04087997d8d0)说明2023-10-12部分USD-M合约由8h改4h；所列名单无BTC/ETH，并给出8h的UTC时点及可能后续调整。这是本窗口之前的规则背景，不能证明以后整个427日没有调整。公告关于“不另行公告”的表述针对部分cap变化，不扩大解释为所有interval变化。

[官方FAQ](https://www.binance.com/en/support/faq/detail/360033525031)的默认8h与允许调整说明、当前fundingInfo、此次完整有界分页及名义槽覆盖四者共同支持“官方接口实取事件结构与8h一致”；仍不足以把历史全日历或资格标签标成已认证。未继续泛搜或读取其他样本，保留旧源门UNKNOWN交监督裁定。

下一最小消费者输入应直接绑定本次raw/分页/事件身份与SHA，提供来源证据引用而非手填`verified=true`；按原始fundingTime及associated mark建立唯一事件账。先区分原始事件时间、模型可知时间、实际订单资格与记账时间，再将已发生费用进入风险权益；时间未到不读未来值，到期资格未决阻塞。任何资格保守模型、结算舍入误差界必须版本化审查，不能用这次0–15ms观察替代FAQ资格规则，也不能用后来的真实fill回灌更早决策。本切片不修改该经济语义、不评分。
