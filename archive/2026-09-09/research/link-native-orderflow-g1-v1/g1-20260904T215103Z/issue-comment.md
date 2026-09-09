G1 收尾：**BLOCKED_NATIVE_COMPATIBILITY**，Issue 保持 OPEN 交监督验收，未开放 G2/G3。

- 唯一 ZIP 41,976,244 bytes；实际 UTC 覆盖 2023-12-31T16:00:00.152Z 至 2024-01-31T15:59:59.729Z。仅授权一天的 169,574 条解释非时间字段，格式/ID检查通过。
- 真实 handler roundtrip 因输出父目录接线错误未完成；不重扫突破预算。archive taker side / size / 历史 contractSize 仍独立 UNKNOWN。
- 冻结合成 FLOW 的方向、UTC5m边界、尾部截断检测通过；84条合成 trades 的原生 Feather 写读相等。R1 在 strategy→DataProvider 路径订单流完整性断言失败后停止。源码支持末根开盘上界截断的解释，但未保存缺失行索引，不声称已实测缺失仅限末根。
- native backtest 尚未调用；一bar实际持仓、R2、stop/force均 NOT_RUN/UNPROVEN。没有策略亏损或盈利结论。原生引擎、冻结断言及 Lab 均未修改。
- 最小下一步仅是监督判断如何解除 G1 blocker；暂不开 G2。

单一最终收据（本机）：`/Users/shenjianpeng/.codex/runs/freqtrade-lab/link-native-orderflow-g1-v1/g1-20260904T215103Z/g1-receipt.md`
SHA-256：`864b5d27351e6c7fffe8cc94a64d7a96616eb0b590fd423c06dea43fd9983f9a`
完整证据索引：`g1-final-evidence.json`，SHA-256 `32db17b44cb3aeb937751bd3af8ab1fdfd3c26acc2b1bb0c3d9166b3b25e2282`。原始材料保留。
