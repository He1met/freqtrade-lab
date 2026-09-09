# 初次采集、隔离与仅S容量计划（尚未授权执行）

本计划只针对本批新DB `/Users/shenjianpeng/.codex/runs/freqtrade-lab/xrp-weekly-persistence-d699-20260907/lab.sqlite`。当前只生成Git外计划/冻结文件，未创建DB、Profile、Generation、source或capture目录。Profile定义时间已写在预览中，批准后按原字段登记，不能为了已取得结果改Profile。若名称/id冲突或对应DB已经有未知内容，先报告，不覆盖。

## 前置与命令

在root核验包并明确授权后：初始化该全新sanitized DB，按 `profile-preview.json` 写唯一Profile；真实项目Generation使用 `generation-request-preview.json` 及唯一固定源码，审批前核实际code SHA等于协议。保存实际调用和审批回执，不把人工拼接JSON说成一次真实模型调用。若Generation改写源码，停止报告，不改协议SHA或重试优化。

随后使用 `capture-command.json` 的精确argv/cwd（同内容在 `capture-command.sh`），只有一次既有 `scripts/fetch_binance_profile_data.py --capture-root .../capture-sd-01 --output-root .../source-sd-01`，SINGLE_BASELINE/economic/window均从本包提供。命令显式绑定安装的2026.7 Python/source路径，不调用系统旧Python；自身worktree使用合并SHA `07ea2cf4742de3d2473302dc57bf0b2283a5fbf2`。该脚本不会自动运行主策略或基准。

采集前只核控制面：所有包SHA、Profile快照、git代码SHA、source/capture输出不存在、现有全局台账SHA及窗口没有新冲突、没有本币并发采集、最近已知418/429禁令已过期。出现冲突/禁令就BLOCKED_DATA或BLOCKED_AUTHORIZATION，不探测/换网。原全局台账路径 `/Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902/global-research-ledger.jsonl`，沿原 `.lock` 追加，保留旧字节；每次数据暴露、S容量、native调用都有单独事实回执。这里不提前追加“已执行”。

## 资源及HTTP失败

沿现有capture硬实现：最多2000次受控fetch调用、decoded响应累计2GiB停止阈值、capture根磁盘5GiB停止阈值、进程7200秒SIGALRM上限。decoded/disk检查发生在保存本次响应后，所以是越阈停止而非提前分配上限；底层wire_attempt_count保持UNKNOWN，受控fetch不是wire次数。原始响应/headers只本地私有保留，不将D价格/费率正文打印到监督报告。

任一HTTP错误（含418/429）、超时、数据断裂或资源阈值均停止；stopped使之后的受控fetch在发请求前拒绝。零自动重试、零自动新capture目录重采、零代理/网络切换；失败目录原样保留。对于下载器已消费的无效结果不补造成功收据。单请求超时沿固定2026.7/CCXT实现，不将进程7200s误称每请求timeout。CLI进程可后台运行并以短poll观察状态，不能让root一次阻塞等待7200秒。

采集数据范围 `[2023-10-23,2025-11-03)`：742日K、17808小时mark、2226个8h资金事件（含S warmup）。这是理论日历行数，非已经观测到的数量。原生端点仅 fapi.binance.com：exchangeInfo元数据，以及XRPUSDT 1d klines、1h markPriceKlines、fundingRate。官方inclusive endTime由既有边界函数限制至2025-11-02T23:59:59.999Z；不请求H评分值。

## 机械QC与物理隔离

既有compile_source从保留响应转换，使用native converter且fill_missing=False/drop_incomplete=False；不为修齐最后K补抓新来源或生成平K。先验证symbol/UTC/原始响应bytes/SHA、完全连续日K和小时mark、funding原timestamp按现分钟桶的完整8h日历、所有S/D评分事件正associated mark、有限值与OHLC约束、XRP market identity及锁定native tiers。当前dry-run精度/tiers只是有SHA的模型快照，historical_exchange_tiers保持UNKNOWN，不冒称逐历史日真实档位。任何不满足保存BLOCKED_DATA并停止，不能放宽合同。

来源成功后保存CLI返回的 `provenance_sha256` / `retrieval_receipt_sha256`，人工只读确认它们与实际文件一致。该两SHA现在尚不存在，不预填虚构值。用既有 `scripts/run_bounded_research_pilot.py` 的 `prepare-search-data` 与 `prepare-development-data`，共同传：

- `--source-root <batch>/source-sd-01`、从实际receipt读取的两个source SHA；
- `--database <batch>/lab.sqlite --profile-id issue107-xrp-weekly-persistent-v1`；
- `--search-timerange 20231106-20241104 --development-timerange 20241104-20251103 --pre-roll-candles 14`；
- 本包 `--economic-gate economic-gate.json --single-baseline single-baseline.json`；
- 两个分别独占的新 `--output-root <batch>/search-campaign` 与 `<batch>/development-pilot`。

只对已分离的D执行现 `check-development-data --pilot-root <batch>/development-pilot` 的机械QC；不评估D策略、不调用D原生或容量。保留原始S+D获取根的原SHA与派生根关系。S/D各自来源含378日K、9072小时mark、1134个8h资金事件；评分各364日/1092事件，预热14日不计评分。D warmup始于2024-10-21。对隔离目录只检查允许文件列表、hash和日期边界：S进程以后只挂载S必要文件，不能读取aggregate S+D根或D根；H保持未采集/未打开。

## 容量只读预筛（仅在root授权之后）

只读取隔离S日K与14日预热，调用冻结源码的相同因果 `close/shift(7)` 与UTC星期定义，计算周目标正/负/零序列。这里只统计日历和信号容量，不读D/H，不读资金收益、mark收益或运行任何撮合/回测/PnL。必须标 `S_SIGNAL_EXPOSED`，不能因只是capacity就声称S未读。

可执行周目标从2023-11-13至2024-10-28，最多51个。相同非零周目标合并，反向或cash完成episode；最后未完成方向censored，不计完成数。没有模拟止损、实际现金或成交，因此计算的是完整方向episode、long/short样本及敞口周数的理论上界。若任何上界小于已冻结12个完整episode、long>=4/short>=4、26个有敞口周，则终态UNDERPOWERED：没有资格进入市场S，不改变周期/窗口/门，也不自动再起新币。若上界通过，只称CAPACITY_NOT_DISPROVED；实际trade/episode持仓、成本/现金、PF、MTM、时间块和收益仍UNKNOWN。

容量回执必须包含source/策略/协议SHA、固定边界、输入行数、可执行决策数、目标0/long/short数、完成/截断episode数、每方向上界、active-week上界和固定阈值，以及 `native_calls=0`、`PnL_computed=false`、D/H读取为false。不得输出择优子窗口或按信号结果改变已冻结设置。任何后续市场S仍须root另一次明确授权；通过容量不是8次native总预算的自动支出许可。

## 交付root的下一回执

一次源采集/机械QC、分离源SHA和行数、S容量结果、实际HTTP受控调用/decoded/disk/耗时、完整失败或成功状态、台账追加SHA、真实Profile/Generation/Candidate与code binding、所有未执行slot。H/Stress仍未采、D仍仅机械QC，市场native仍0。root据此决定是否放行S的主1+基准1；失败则如实终止，不制造ResearchRun。
