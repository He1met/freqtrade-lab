完成 Issue #96 的一次冻结 Binance BCH 28/14 日线趋势 Search，项目真实终态为 `SEARCH_TERMINATED_NO_FINALIST`。报告保留原生与保守指标口径、逐笔费用分解、全部额外门、来源批次、DB/页面/台账和artifact的核验路径；没有代码、schema或runner变更。

验证：唯一项目生成/批准Candidate；无市场因果T0；现有来源生产与S/D隔离；一次原生Search `VALID`；原artifact费用/PF/合计对账；实际浏览器确认NO_FINALIST、禁用D/H与UNKNOWN状态；新DB六表计数1/2/1/0/0/0；`git diff --check`。净/PF/DD/自然样本门失败，未运行D/H/Stress或追加Search。数据和完整产物留在Git外。

Refs #96. 研究终态和额外门已完整记录；Issue关闭留待监督独立核验。
