# V3首批诊断入口交付

本轮新增独立`run_spot139_v3.py`和单循环报告器，未改已审V3模型/映射、V2入口或历史结果。市场执行仍未授权；没有grant、V3运行目录、预约、原生实例或新增GET。

固定manifest：`docs/issue139-v3-first-diagnostics-manifest.json`，SHA256 `63c34e6d64c545ba34abaf7f05737d86087dc9fdbff3c2bb5bc9f90c4827bb10`。实际执行并通过的两个check-only命令（工作目录为本隔离checkout）：

```
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_spot139_v3.py docs/issue139-v3-first-diagnostics-manifest.json --manifest-sha256 63c34e6d64c545ba34abaf7f05737d86087dc9fdbff3c2bb5bc9f90c4827bb10 --cost base
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_spot139_v3.py docs/issue139-v3-first-diagnostics-manifest.json --manifest-sha256 63c34e6d64c545ba34abaf7f05737d86087dc9fdbff3c2bb5bc9f90c4827bb10 --cost stress
```

两者返回`source_integrity=PASS`、实际祖先占槽30、V3预约0、模型`SpotResidualV3`/映射`ReconcilerV3`，经济结果NULL。base仍须外部grant，stress先须base成功。实际检查收据`docs/issue139-v3-runner-check-receipt.json` SHA `0ce80638716c83cc84657b440ee6a38f97bf22c5aee5169aca29e17c26efcfe5`。

只在监督下一份明确执行授权之后，上述命令才追加`--execute --grant <Git外JSON> --grant-sha256 <固定SHA>`。grant必须绑定这个manifest SHA、`market_execution_authorized=true`、`costs=["base","stress"]`、以下keys和新的市场授权评论URL作为`authorization_reference`：

```
ISSUE139_B_RESIDUAL_V3/development-2021-2023/base
ISSUE139_B_RESIDUAL_V3/development-2021-2023/stress
```

入口跨旧native writer、V2 writer、global writer和V3 suffix writer持非阻塞锁，在锁内从实际28+2终态/全局关联checkpoint核对30，不只信硬编码数值。39源、模型/报告/runner、固定native/CCXT精度代码和三份祖先账本SHA均冻结。V3 hash-chain保留每cost的RESERVED→终态；先fsync预约再spawn，worker须继承4个锁并找到自身pending key。缺失/未决/失败/重复/已完成结果篡改拒绝；base技术成功才stress；180秒/0retry，任一技术或会计越界失败占槽并停止，普通经济亏损不触发改规则或免费重跑。

正常单次小时循环中流式写入带SHA的hourly状态，直接统计逐笔订单/episode起止和退出原因、active/residual quantity及basis、现金NAV、latch/DD/STALE、缺数据日、block原因时长、每币贡献及月度/cycle集中度；原生gross统计和逐笔数值界另列。不事后补跑，不将episode结束当清仓或独立样本。详情见`docs/protocols/issue139-v3-runner-binding.md`。

40项合成定向测试通过：新入口/报告10项、V3模型12项、旧相关18项。入口测试模拟子进程而不加载/启动native，覆盖精确与失效grant、cost/model选择、实际账本漂移和未决、跨writer锁、超时先记槽后失败、base先行、负结果保留、结果SHA篡改和禁止重试；单循环报告用合成控制器检查episode/贡献/原因/快照，未冒充原生撮合测试。没有增加此前4个原生合成实例。

两次最初check-only因旧全局JSONL第95/98行空白分隔解析失败，均发生在预约/native前。已只允许全局控制账本的空白行，调用账本仍严格解析；所有原始字节SHA不变，失败历史在收据中保留。修复后测试与实际两cost检查均通过。

本轮不改任何市场账本。当前30占槽+10旧sealed+8待定+48未分配=96；最多两次V3若另获准并实际消耗，32+10+6+48=96。旧V2收益不能充当V3准入/通过理由，同历史仅为已暴露开发诊断。PR140 draft、Issue139 open，不merge/close、不恢复候选或启动A/C/half-B。
