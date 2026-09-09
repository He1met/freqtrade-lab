# 路线 A：两轮探索完成，无 finalist

`EXPLORATORY / NOT_INDEPENDENTLY_VALIDATED`。终态 `SEARCH_TERMINATED_NO_FINALIST`，已消耗唯一 R1/R2 共 2 次真实回测，剩余 0；没有经济重试、门槛调整或后续验证。代码提交 `484960f97d334a152dde30678deb0d707891cec9`，PR #70；Issue #69 等监督完成整体交付验收，未关闭、未合并。

| 指标 | R1 早段方向基线 | R2 入场前半小时同向过滤 |
|---|---:|---:|
| 实际交易数 | 128 | 61 |
| 毛收益，未扣手续费 | -4.118325% | -2.021770% |
| 手续费 / 初始 wallet | 3.195490% | 1.522955% |
| 净收益 | -7.313815% | -3.544725% |
| 净损益，USDT | -146.27630515 | -70.89450440 |
| PF | 0.374046 | 0.332895 |
| 最大回撤 | 7.313815% | 3.544725% |
| 平均持仓，分钟 | 29.4922 | 29.3443 |
| 多 / 空 | 56 / 72 | 23 / 38 |
| signal / stop_loss 退出 | 123 / 5 | 59 / 2 |
| 额外 1 bp/side 滑点敏感性净收益 | -7.952913% | -3.849316% |

两者均满足冻结的 50 笔数量要求及 15% 回撤上限，但净收益和 PF 不通过 ≥1.25% / ≥1.10 门槛。两轮毛收益已为负，不能将失败仅归因于手续费。R2 交易集合是 R1 的严格子集，较少总亏损不能证明有效交易优势。

成本来自实际原生回测逐腿 notional，fee=0.0005/side，1x；各交易 funding_fees 均为明确的 0，并非以 0 代替缺失资金费数据。资金费源有完整 543 条实际费率，时段持仓未跨这些结算时点。真实滑点仍 UNKNOWN；1 bp/side 仅为事前固定的逐腿扣减敏感性，不是实际成交证据。

实际交易全部在纽约工作日 15:30 入场，冬季为20:30 UTC、夏季19:30 UTC；signal exit 均16:00纽约时间，最多每天一笔，无零持仓时长。两轮真实 force_exit/ROI exit 均0；合成原生测试另覆盖末端force_exit。没有运行 Development/Holdout/Stress/Judge/Release/Demo/交易。

数据为 LINK/USDT:USDT 5m，Search `[2024-02-01,2024-07-31)`。OHLCV 52201行（含73根pre-roll，自Jan31 17:55Z），mark 4351行（自Jan31 17Z），funding 543行（Feb1 00Z至Jul30 16Z），无缺口/重复/未闭合。只采集一次公有source。原producer未保留六包原件的缺口曾记UNKNOWN；经监督授权另作6个原URL GET，ZIP/CSV均先核原SHA再只读时间列，恢复原件保留在audit-recovery。546个raw时间全在授权 `[Jan31 16Z,Jul31 16Z)` 内，3个语义外时间为Jan31 16Z、Jul31 00Z、Jul31 08Z。原source、consumer、旧UNKNOWN和失败记录均未覆盖；恢复请求另计账。

已验证实际 Console/API 的 Candidate 生成、批准、R1/R2、两次原生FT ZIP与终态投影。最终六表数量为 `1/4/3/0/0/0`：第四个Generation是合法Search负终态投影，原日期草稿保留未执行；ResearchRun/Execution/Release均0。页面 http://127.0.0.1:8791/console 可查看终态、预算0及禁用的后续验证。FreqUI Webserver未运行，页面总体NOT_READY不代表本次原生Search未执行。

验证证据包括原生合成T2、修正fixture同timestamp随机UUID排序假设后同组96通过、机制标识修复后34通过。监督发现的95通过/1失败原始记录保留。mechanism仅3处切到专用标签正则，文件/路径/业务ID的SAFE_ID未放宽。工作树干净，远端SHA已核。

关键文件：`final-a-evidence.json`（成本/逐笔时钟审计与来源SHA）、`terminal-console-context.json`（实际API终态）、`search-campaign/search-terminal.json`、`search-campaign/trials.jsonl`、两份原生ZIP、`audit-recovery/timestamp-audit.json`、`supervisor-reproduction-failure.json`、`pre-data-test-correction.json`。A已提交无运行中的screen-search/native runner证据给监督，由监督放行B实际执行；B保持独立DB/Profile/campaign，共享同一source，不是独立数据样本。
