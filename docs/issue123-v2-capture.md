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
