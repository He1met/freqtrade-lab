# S 终态与下一步范围

结论：SEARCH_TERMINATED_NO_FINALIST。仅运行1次市场主策略，基准跳过，D/H/Stress为0。

起始钱包1000 USDT、固定配置stake250；实际每笔249.93936–249.99963来自原生lot-size舍入，未补资金。30笔交易（long16、short14）对应27个完成自然episode（14/13）和1个censored组。48个有仓周；native平均13584分钟、完成episode累计有仓平均14773.333分钟。

纯价格毛亏280.607410 USDT；entry费7.499052、exit费7.392747；native funding净支出2.964826；native净亏298.464034；保守再扣0.930749，最终净亏299.394783（-29.939478%，钱包分母1000）。这是价格规则失败为主，不能解释为只差费用。

原生PF0.176604、保守PF0.175258；原生DD30.148672%、正常小时MTM DD32.207654%。四个13周块净额依次-104.358288、-66.000632、-38.666890、-90.368973 USDT。正块0、最大正份额UNKNOWN；去最大完成盈利episode后-342.353342。ROI/清算/拒绝信号均0，最低free cash447.394927。样本/持有门满足，不能覆盖净利、毛利、PF、DD、固定块、去最大组等失败。

真实Search已持久化为第2条generation_runs（MANUAL/COMPLETED）；原CODEX Generation仍COMPLETED。Profile1/Candidate1/ResearchRun0/Execution0/Release0。Console /api/search-campaigns/<campaign>返回200及NO_FINALIST；/api/generations/<CODEX id>返回200。Search的MANUAL id不属于CODEX generation详情路由，该探测返回404，未把404算通过。

容量、外层episode/固定块receipt目前仅在Git外；没有为无基准结果调用comparison importer，也未伪造入库或Run。Issue107保持OPEN待监督验收。D误输出事故和独立资金序列化勘误保留；D不能称未见验证窗。

后续仅方案：不在已消费S上测试反向规则，不简单换币或微调7日/止损。本次不能证明哪种替代规则会赚钱。可供root比较的低复杂度已知家族改进，是低换手、仅long/现金的现货绝对趋势：预先明确持续趋势的经济假设与失效情形，交易成本与资金占用先预算，再锁唯一规则和上界；它不是全新独立机制，须与既有个人spot研究去重。只有完成历史机制/曝光台账核对、找到未消费且不与保护区冲突的独立验证窗，才能称可执行。当前未查询新行情、未选参数/资产/替代窗口，也没有证据确认存在合法可用验证窗（UNKNOWN）；root决定是否值得下一批设计。
