# Issue92：SOURCE READY / consumer QC READY

一次采集与 QC 完成，**Search 未授权、未运行**。[Issue92](https://github.com/He1met/freqtrade-lab/issues/92)保持开放；项目代码/native/Schema无修改。

- cohort：`/Users/shenjianpeng/.codex/runs/freqtrade-lab/atom-regime-pullback-v1/cohort-20260906-0413`
- 实际 HTTP **16/24**，全部200，失败0、重试0；guard无网络stub证明第25次在网络前拒绝，计时上限1800秒。源 1418 行、S切片930行，均 UTC 日线连续，全部源SHA在consumer与Console之后保持一致。D仅producer/QC，H未采集。
- Profile `20a412a7-fea0-47a6-8209-50659243c6ff`；Generation `499d1f04-f716-4460-8ad7-db72663767b3`；Candidate `232031bf-5e0b-44ff-82be-8b7e30afaa38`。三者各1；ResearchRun/Execution/Release均0。Search campaign尚未创建，意图ID不冒充实际ID。
- [实际Console](http://127.0.0.1:50783/console) / [只读QC context](http://127.0.0.1:50783/api/search/context)：`SEARCH_READY`，1轮/1attempt、used=0。界面的通用hard maximum=6不扩大本cohort的active limit=1。现只执行过GET，没有启动动作。

绑定SHA：

| 证据 | SHA-256 |
|---|---|
| 协议 | `d514b1cb5eafeb880de65f941f2f5ed1863c84adad81016757d2b77db9dce9b4` |
| 最终策略字节 | `4144bf038bc9c529bd291dc0d99f9a8f043bfc46525837ff95102f13ebad0923` |
| 原冻结回执 | `13ad1faaab7d4de7a27e7dca3d88cc99d384df314966de4ca0063e770b10a5b9` |
| DB逻辑绑定补充 | `078cd89f371e8718e945388d6832fa3376fb4c4b7f82f6b2ae35dc455c39182c` |
| source retrieval receipt | `a9012d19d9b87fa586a8b0a91e6c9687e3d669a6882a4cb47b0ab435f12f3588` |
| source provenance | `448552b4b03cfff6788b0e05fc89fed42bb39fe40724b0488193165bde9a5f61` |
| Search provenance | `2241fdd1c11820e0f24bc27ee5c9d7e752cb800255885cf1acc94bc2598bde7c` |

原native绑定为 Freqtrade2026.7 / `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`；配置 `okx / ATOM/USDT / spot / 1d / cash1000 / stake500 / max1 / fee0.001 / balance_ratio0.99`，策略 `startup200 / ROI{} / stoploss−0.08 / long-only`。`runtime-config.json`是冻结的Profile基配置，strategy由Search入口绑定上述唯一策略；还不存在已执行native命令或raw结果。

完整机器证据见同目录 `source-ready.json`、`source-consumer-qc.json`、`search-http-preflight.json`。注册退出发生checkpoint后，未重写原freeze；按已接受方式以只读事务核对Profile/批准Candidate/Generation/代码/counts，并在首次请求前写逻辑绑定补充回执。

下一步仅待监督核证后放行已定的1次Search。native内部finalist仍须通过协议的额外成本、现金、每日cost-MTM、延伸分组和集中度硬门才可晋级；本次未导入ResearchRun，也没有经济结论。
