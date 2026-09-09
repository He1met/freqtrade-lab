# Issue98 单次 Search 交接

项目真实终态 `SEARCH_FINALIST_FROZEN`；同一原生 ZIP 的13项核心及额外冻结门全部通过。结论仅为 Search 阶段通过，D/H/Stress 尚未执行，不证明未来盈利或可交易。

| 项目 | 实际值 |
| --- | ---: |
| 总交易 / 自然交易 | 33 / 32 |
| 自然多 / 空 | 12 / 20 |
| 价格毛利 USDT | +180.804910 |
| 费假设 / 滑点代理 USDT | -8.236858 / -8.236858 |
| native funding USDT | +2.616244 |
| native 净 USDT | +166.947438 |
| 额外资金扣减 USDT | -1.628307 |
| 保守净 USDT / 钱包收益率 | +165.319130 / +16.531913% |
| 保守 PF | 1.975491 |
| native DD / 小时收盘 MTM DD | 7.268125% / 9.945161% |
| 平均持仓分钟 / ROI退出 | 3709.091 / 0 |
| 最低可用现金 USDT | 676.228176 |
| 有自然样本的块 | 4 / 4 |
| 移除最佳正收益交易后的净 USDT | +96.189732 |

风险解释：正常保守 DD 距10%门仅约0.05484个百分点；小时extrema顺序压力诊断为10.633109%，不是冻结正常DD门，也不是Holdout Stress。按开仓归属的四块交易净和分别 -44.249348、+21.317292、+11.088715、+177.162472 USDT，收益集中最后一块，不能宣称稳定。1笔零时长止损不计自然样本，其损益仍完整保留。历史静态 tiers 的适用性仍 UNKNOWN。

实际预算：真实 CODEX Generation1（tool events0，源码与冻结哈希一致）、Candidate1、native capture1、Search1、重采/重播0。61 CCXT fetch，decoded5,145,891字节，wire attempts UNKNOWN。D物理隔离并完成机械QC；ResearchRun/Execution/Release均0，H未采集。Console已实际浏览验证，Development按钮禁用，等待匹配人工协议审阅及单独D授权。

唯一产物：`search-campaign/search-results-round-1/a62cfea4-cdee-4f91-9631-9f5ec13568c5/raw/backtest-result-2026-09-07_04-44-57.zip`，SHA256 `92243059f5abd56d260bb83c89b15273c60457f74fe0a54a3bda1e327d2337d2`。完整逐笔成本、冻结门及原生来源在 `search-protocol-review.json`；原项目状态在 `search-context-terminal.json`。

额外QC初稿整点断言错误已如实保留在 `qc-script-correction.json`；原冻结合同本来使用native分钟映射，未改数据、合同或经济阈值。监督已确认该纠正。

Issue98继续OPEN；PR99工程已MERGED，工程通过不代替研究通过。下一步只由监督审阅决定是否单独授权冻结D；本交接不执行D或创建后期Run。
