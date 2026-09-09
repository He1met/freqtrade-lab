BCH_EXACT_GRID_DUAL_SMA_10_30_V1 已完成授权范围：两次实际 Search，合法 finalist 一次独立 Development；最终 **REJECTED**。不是数据/技术阻塞，而是独立 Development 经济 Gate 未通过。Issue 保持 OPEN，交监督验收决定关闭。

| 阶段 | 交易数 | 净收益 | PF | 最大回撤 | 平均持仓 | 判定 |
|---|---:|---:|---:|---:|---:|---|
| Search R1，stoploss −20% | 7 | +5.1305% | 2.3863 | 3.3663% | 27.00 天 | VALID，Gate 通过，排名第1 |
| Search R2，stoploss −10% | 11 | +4.7901% | 1.8817 | 4.8772% | 16.82 天 | VALID，Gate 通过，排名第2 |
| Development，仅 R1 | 8 | −0.4441% | 0.9221 | 3.7992% | 27.88 天 | engine SUCCEEDED；REJECTED |

Search=[2024-02-01,2025-02-01)，Dev=[2025-02-01,2026-02-01)。三次ROI退出均0。Dev失败项：strict net>0、net>=1.25%、PF>=1.10；交易数>=5、持仓>=7天、DD<=15%均通过。不改阈值、不补跑R2 Dev、不再Search。交易数达到冻结门槛，但独立 Development 窗口经济表现未达标。净损益为 −4.44077628 USDT；funding_fees 合计 +1.3588392277144117，为资金费净收款，不能将失败归因为资金费拖累。退出构成为7次 exit_signal、1次 stop_loss；未证明特定市场状态或参数导致失败。 跨资产同时改变信号尺度，不能由与LTC的比较声称10/30普遍优于28/84。

数据与核对：冻结后获取；25档资金费2193/2193原始零偏移8h事件，首档86、末档1；正式原生重取25档的ZIP/CSV SHA逐一与本root预检相同。Source价格851/mark20424行连续；Search切片486/11664/1098，Dev485/11640/1095，均含120d warmup并通过当前consumer。R1/R2实际源码与冻结参考AST/字段一致，R2通过原生单因素verifier，仅class和stoploss变化。三个真实ZIP与API/DB/source/code/cost字段对账通过，fee_open/close=.0005、1x、long-only，funding进入engine；ZIP funding_fees合计依次−8.11156439、−8.57196245、+1.35883923（原始字段符号）。slippage=UNKNOWN；精确grid只排除归整偏移，不证明逐秒结算/成交保真。

六表 counts：research_profiles=1，generation_runs=3（CODEX2+MANUAL Search终态1），candidates=2，research_runs=1，backtest_executions=1，releases=0。verify_search_terminal_projection、同campaign terminal/attempts/两Search ZIP、finalist到Dev绑定与唯一Dev ZIP对账通过，foreign_key_check为空。真实Console页面显示SEARCH_FINALIST_FROZEN及REJECTED；H/Stress封存/0执行，授权按钮禁用。通用R2 Development READY是已知展示局限，后台finalist Gate为准；FreqUI UNAVAILABLE。

标识：
- Profile：bch-exact-grid-dual-sma-10-30-v1
- Search campaign：4450b329-5a76-414e-bcdc-3fa8a0303d7b
- R1 generation/candidate：b8e2c64f-b369-4f17-9082-625f2126d6c4 / 21bb1bb6-c1ab-4376-a4ee-cc6c774053e3
- R2 generation/candidate：abf51419-4535-45dd-b8fe-3bb6f483727a / 96f4740b-0ec6-42d5-9020-7822640b1dc7
- ResearchRun/Execution：c27c4704-6846-4903-a612-f8d07d4ad36e / a03c4f93-e5e8-4299-a04e-2c1e8cae3769

完整 SHA-256（raw25档明细另存source-verification.json）：
```text
source_provenance 1a220f8ef21e8dbc3c8ee2c721cb3564c6c5db35dc4f4ca793fe60dd179358e4
source_receipt ef5220ab1f78767ab984df515fbfb2add62fda1cca6e95ee43b168d84c79faab
R1_code e95ea86b03bc7cd8aef60d6576debb973dde768e9dfc1650c8daf3300894f979
R2_code 7fd6fce55b39d855668c4e9a7b50e92dc4dcf4ea7a18712be77f6f9b4f0a1837
R1_Search_ZIP 6817ea63745cb61b2dbb705400edeac5a7eabd968a6fc506534dfadc5672d06b
R2_Search_ZIP e65a154fb5e45d7a8f734f9439a61f0bf3cce83d6538816b08bb16875eb048c9
R1_Development_ZIP f8e1ed9a4c634f0eb5b6c82d106c6ef1dd456d5f699d9bf1fbc685dfe74d076f
Search_terminal 1fba6ac59b81be44eb1b4c9da667a2a3473258c7be79e94b1bf59603f9f7cab4
trials 24f69d115ee04b0fc172ea33b95393035fe639f8793fdcd3c8fd3ff249ea63c0
final_audit 5a28a020b2bb9f257037e4ebf1717a128a8ab5d528baa1bba5b6319e93e4d43f
```

证据root（0700，Git外）：`/Users/shenjianpeng/.codex/runs/freqtrade-lab/bch-exact-grid-dual-sma-10-30-v1/cohort-v1._ryz88c7`。细节：`final-audit.json`、`source-verification.json`、`evidence-hashes.json`。Console：http://127.0.0.1:49240/console 。

Holdout/Stress=[2026-02-01,2026-07-31)仅metadata，SEALED_UNREAD，未读取或执行；Release/Demo/live未执行。实际service tier=UNKNOWN，CLI调用固定gpt-6-astra/high/default，无全局改动。工作树干净，HEAD/live main均dc82c61fe8a27a654977344755c088412518d858；业务代码/schema无改动，无PR或伪commit。#62/#63未修改。证据只支持本次历史研究终态，不支持盈利或交易资格。
