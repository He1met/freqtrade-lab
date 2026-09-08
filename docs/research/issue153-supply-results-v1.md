# Issue153 最终结果：EXPOSED_DEVELOPMENT_ASSOCIATION

一次21月开发诊断完成，17 SCORED、4 UNKNOWN；EXPAND11、OTHER6。供给扩张组两成本平均净收益为正且高于OTHER，符合冻结的描述性门，因此仅标 **EXPOSED_DEVELOPMENT_ASSOCIATION**，没有独立确认、因果、超价格信息或钱包盈利证据。

扩张组base净均值+4.011307%、stress+3.678691%，但中位数−3.586531%/−3.894850%，只有5/11正收益。可评分OTHER六个月全在2022，时间制度与牛熊市场混杂明显；不能把均值差归因于USDC供给。事前5个最低计数通过不代表功效足够，不再切年份/阈值找更好子组。

所有收益是独立1quote事件往返，未复利/年化/钱包/DD。最大绝对贡献分母为组内绝对收益和，正贡献分母为正收益和；OTHER只有一个正月，正贡献100%不是总体主导利润的证明。供给为Ethereum单链USDC账本存量，迁移、库存、避险/替代均可能驱动，不等于净新美元买入ETH。

|Cost/group|n|Net mean %|Net median %|Positive|Max absolute month/share %|Max positive month/share %|
|---|---:|---:|---:|---:|---|---|
|base/EXPAND|11|4.011307|-3.586531|5|2021-07/15.598648|2021-07/26.502069|
|base/OTHER|6|-13.017191|-18.636573|1|2022-05/27.727847|2022-10/100.000000|
|stress/EXPAND|11|3.678691|-3.894850|5|2021-07/15.449936|2021-07/26.574005|
|stress/OTHER|6|-13.295352|-18.896764|1|2022-05/27.696826|2022-10/100.000000|

base EXPAND minus OTHER net mean: 17.028498 percentage points.


stress EXPAND minus OTHER net mean: 16.974043 percentage points.

|Month|Supply change %|Group|Status|Gross %|Base net %|Stress net %|Bad held hours|
|---|---:|---|---|---:|---:|---:|---:|
|2021-03|53.049183|EXPAND|SCORED|13.997819|13.633495|13.270109|0|
|2021-04|19.703624|EXPAND|UNKNOWN|NULL|NULL|NULL|6|
|2021-05|29.418847|EXPAND|SCORED|-26.512197|-26.747055|-26.981310|0|
|2021-06|57.200652|EXPAND|SCORED|-12.344196|-12.624334|-12.903751|0|
|2021-07|10.521134|EXPAND|SCORED|39.294968|38.849797|38.405772|0|
|2021-08|9.000252|EXPAND|UNKNOWN|NULL|NULL|NULL|5|
|2021-09|-1.491741|OTHER|UNKNOWN|NULL|NULL|NULL|2|
|2021-10|9.874573|EXPAND|SCORED|30.085738|29.669999|29.255330|0|
|2021-11|5.328583|EXPAND|SCORED|-7.678279|-7.973329|-8.267619|0|
|2021-12|14.297721|EXPAND|UNKNOWN|NULL|NULL|NULL|1|
|2022-01|9.130936|EXPAND|SCORED|-3.277417|-3.586531|-3.894850|0|
|2022-02|18.735670|EXPAND|SCORED|-19.503919|-19.761175|-20.017769|0|
|2022-03|7.088139|EXPAND|SCORED|27.771096|27.362755|26.955464|0|
|2022-04|-4.358375|OTHER|SCORED|-18.660122|-18.920075|-19.179359|0|
|2022-05|-5.537520|OTHER|SCORED|-30.711648|-30.933085|-31.153953|0|
|2022-06|5.689291|EXPAND|SCORED|-31.556028|-31.774767|-31.992944|0|
|2022-07|2.293935|EXPAND|SCORED|37.515000|37.075518|36.637167|0|
|2022-08|-2.775694|OTHER|SCORED|-4.655317|-4.960027|-5.263954|0|
|2022-09|-4.625379|OTHER|SCORED|-18.091301|-18.353072|-18.614169|0|
|2022-10|-6.583323|OTHER|SCORED|17.102490|16.728245|16.354961|0|
|2022-11|-3.883223|OTHER|SCORED|-21.413980|-21.665131|-21.915637|0|

4个UNKNOWN为2021-04、08、09、12，全部由既有ETH持有小时缺失/短小时触发，未补取/移位。实际每日供给669行、669唯一UTC日期，22输入月在固定检查下均完整、月末端点有效；这只证明当前响应符合开发检查，不证明历史vintage、首次发布时间或完整供应商方法审计。每月8日缓冲与日标签解释仍是EX_POST设计假设。

## 运行、收据与验证

- 采集前冻结c48d06e，先行评论5584988322；唯一供给GET在2026-09-08T12:16:55UTC返回HTTP200、60830bytes，20秒/1MiB预算内，0retry/redirect。无需离线schema修复。
- 供给response SHA `f945b6f6d9e13d0ffb3294d0f3067407493e3ac75db3f80c08b990a3622cd08a`；check SHA `48ea99f384f5a47868045acfb21ea320a7067edc979006dd955e0c2376695afd`。采集绑定3e70d1f推送并先行评论5584994061后，唯一analysis完成，耗时0.022905秒，21units/0retry。
- events SHA `558f42874c39381e37b4fc2b92e36f8afb8637d0711a82759f038218591ef372`；summary SHA `3778fb6d31fa51ebc4bef161466a50bcd34ff68ef349b96f9c2df9edf28cdffb`。全部attempt/原响应/check/terminal位于Git外`/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue153-usdc-supply-v1`。
- Git内`docs/issue153-diagnostic-result-v1.json`保存全21事件、22月供给端点/检查、公开收据与SHA，不包含原始日率/行情时间序列。7个合成测试、CLI控制检查通过，输出毛净算术核对通过；没有重跑市场分析。
- 本次新增供给时间序列GET1、analysis1，schema离线修复0；累计Coin Metrics metadata2、EFFR macro1、cryptoGET112/native32保持各自账，新增crypto/native/global写0。旧原文、保护窗、forward五文件/manifest/global/grant未变。

本次有限开发工作已完成，交PR验收，不自动进入下一检验、扩大样本或产生策略/前向资格。
