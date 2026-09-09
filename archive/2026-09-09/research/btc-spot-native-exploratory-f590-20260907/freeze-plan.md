# BTC 原生执行约束变体：紧凑冻结包

状态 **STATIC_ENTRYPOINT_CHECKS_PASS / EXECUTION_NOT_AUTHORIZED**。规则/AST、Profile、探索合同/窗口、既有2026.7运行时身份均通过只读检查；尚未声称 synthetic、source QC 或市场可执行已经通过。未发现需改项目代码的接入点。

唯一规则：BTC/USDT OKX spot，已收盘UTC周日计算28日close return，严格>0目标long，否则cash；native下一根日K即周一open处理信号。正目标连续持有不周周重开；8%原生止损任何日可出场，此后只在下一周信号再入。ROI={}、1仓、固定配置stake250/钱包1000，不复利；原生lot-size舍入保留，不把余额不足的拒单隐藏。末尾按native force_exit，不能视为自然完整episode。不是旧源码等价复现、不是新alpha、优劣UNKNOWN。

范围：新原生采集旧已见训练年，source [2024-01-01,2024-12-31)，共365日K；29预热，score [2024-01-30,2024-12-31)，336日。窗口末边界也在2024，不请求2025。预计可行动周一02-05至12-30共48次；连续long/现金会更少交易，stop后下一周可重入，理论交易入口上界48，不保证样本。固定自然季度块按score截断：[01-30,04-01)、[04-01,07-01)、[07-01,10-01)、[10-01,12-31)。不读其它D/H，不延长旧root/旧Families预算。

事前**探索继续研究门**：native完整交易数>=6、净利>=1 USDT（钱包0.1%）、PF>=1.05、native DD<=10%、ROI exits=0、无short/leverage、source/cost身份一致。仅是允许root讨论下一次研究的工程内兼容门，不是盈利资格；6笔不足以声称统计稳健。低于6为样本不足，经济负仍如实报告；不降门。持有期只报告，不设从XRP搬来的天数门（economic gate holding floor=0）。净额/1000是钱包收益；净额/250单列“固定配置名义投入比”，不能当复合收益或年化。

成本：每边fee=.0012是手续费.001+滑点.0002的**原生费用代理**，并非真实成交滑点模型，不能再重复扣.0002。250名义往返且价格不变时代理成本约0.60 USDT；真实按native入/出notional计。报告净、由交易amount与open/close重建毛利和代理费用、PF、native DD、成交数、stop/force计数、持有期。native DD不改叫daily/hourly MTM。当前OKX spot没有已核的同口径MTM附加入口：第一轮MTM记UNKNOWN；季度仅按原生导出成交close_date归属净利，明确不是持仓跨块MTM，也不作独立块显著性。无需新增comparison或复杂episode算法。

执行许可建议一次涵盖：1次已附synthetic_probe.py（全人工365日K，网络deny，BTC人工market精度不充当真实metadata）、1次capture、1次Generation及正常人工批准、1次R1市场native。总探索框架2轮/2次，但本包只授权拟议首轮1次，剩余市场native=0直到root看R1决定。synthetic先证首Feb5周一、Feb14止损、只在周一重入/现金退出、同周不反复交易、末Dec30force、250固定stake及现金费用守恒；失败保留根并停止，不偷偷重试。该探针只AST解析过，尚未运行；不是已通过凭证。

实际采集argv见capture-command.json；合成argv见synthetic-command.json。引用的现有python和freqtrade源码路径已核版本Python3.13.13/Freqtrade2026.7/ccxt4.5.68/pandas3.0.3/pyarrow25.0.0，native clean commit52bc96f4480b1a0da6a9b455bd00b17fbb6786a5。仅做版本/源码只读核验，没有执行native。

采集预算与失败：此spot分支1 instrument+4个history-candles页（100/100/100/65）=5个预期GET，无funding/mark/tier。当前代码没有总响应字节/磁盘硬上限，不能承诺有；单请求timeout30秒、CCXT maxRetriesOnFailure默认0，代码无spot重试循环。公共GET白名单、禁redirect/禁环境代理，严格检查原始9字段confirmed/UTC页和base-volume映射。HTTP/页QC异常停止，exploratory输出根保留acquisition-failure.json且retry_allowed=false；失败前可能已有响应，仍是已见暴露。预算为1次进程，不自动重启；拟议外层watchdog900秒、累计运行目录上限50MiB（响应后检查/终止阈值，非现有脚本硬字节限制），超限停止并报告，不换网络。

root一次批准后按既有正常路径：创建新独立六表DB与完全相同Profile→synthetic通过→capture（新source根）→prepare-search-data使用新source真实provenance/receipt SHA及exploration合同、D=null→Console以--exploration-contract及新search-root启动→POST /api/generations（generation-request.json）→校验源码SHA→正常APPROVE→POST /api/search-campaigns {candidate_ids:[真实新id],profile_id:本Profile}触发R1。这些API均为已核入口；ID和sourceSHA必须从真实输出取，不能预造。R1尚无两轮terminal时报告真实阶段状态，不伪装完整终态，不启动D/H。新DB/Generation/Candidate/服务端口均未创建。

既有source preparation完整argv须在capture成功后绑定实际SHA：run_bounded_research_pilot.py prepare-search-data --source-root /Users/shenjianpeng/.codex/runs/freqtrade-lab/btc-spot-native-exploratory-f590-20260907/source-2024-01 --source-provenance-sha256 <capture实际SHA> --source-receipt-sha256 <capture实际SHA> --database /Users/shenjianpeng/.codex/runs/freqtrade-lab/btc-spot-native-exploratory-f590-20260907/lab.sqlite --profile-id btc-spot-native-exploratory-f590-v1 --search-timerange 20240130-20241231 --pre-roll-candles 29 --economic-gate /Users/shenjianpeng/.codex/runs/freqtrade-lab/btc-spot-native-exploratory-f590-20260907/economic-gate.json --exploration-contract /Users/shenjianpeng/.codex/runs/freqtrade-lab/btc-spot-native-exploratory-f590-20260907/exploration-contract.json --output-root /Users/shenjianpeng/.codex/runs/freqtrade-lab/btc-spot-native-exploratory-f590-20260907/search-data-01。不加--single-baseline，不传development。未知源资格保持UNKNOWN直到QC，未要求改项目。

本包Profile holdout字段只是现schema的必填占位，不预留或授权H；exploration强制D=null且拒绝进入Development。以后必须另冻未消费/不冲突验证窗与正常候选，同资产/其它资产的具体保护粒度分别核，不能从本探索过门推独立资格。
