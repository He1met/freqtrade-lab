# Issue101终态：UNDERPOWERED，未运行Search

唯一ADA归一化趋势回撤基线已按冻结容量门停止。14个评分S准入事件全部下一日入场仍在S内，多5/空9；自然交易不可能多于准入事件，因而无法达到24总/多8/空8。PnL、价格毛利、PF/DD全部UNKNOWN，不能写经济亏损。

一次64 CCXT fetch/5,314,665 decoded bytes完成S+D来源，公开线缆尝试UNKNOWN，零重试/重启/拼接。800日线/19200小时mark/2184评分资金完整；S/D隔离各436/10464/1092及UTC序列、原响应/来源/consumer SHA通过。H未采集。D只机械QC，不计算信号。真实CODEX Generation1（tool events0）与Candidate1源码SHA完全匹配冻结文件；native Search0、ResearchRun/Execution/Release0。

首份signal-capacity.json按信号日分块；保留不覆盖。capacity-entry-boundary-audit.json以相同源码/来源核下一日入场：仍14/5/9，四块多空3/0、2/2、0/5、0/2未变。预热事件不进入交易；只接受评分期信号且entry在S内，不用预热制造样本。此为边界复核，不是新候选或参数扫描，无未来收益/订单模拟。

Generation ef5de524-0506-4bd6-9af5-eec9d9c59202；Candidate fbf47a7c-c892-45c0-80ce-03bee437e1d9。六表1/1/1/0/0/0，Generation COMPLETED/Candidate APPROVED表示代码生成/审批成功，不能解释为研究通过。Profile显示名沿用模板文字Issue98 ADA confirmed shock reversal 3D是标签疏漏；真实id issue101-ada-normalized-pullback-v1、pair、参数与来源/源码绑定均准确。未在Generation冻结后修改Profile名，以免破坏快照。

## Console与JSON入口缺口

当前Console在来源准备前启动，startup冻结Search能力为BLOCKED_DATA，campaign_id=null、attempts空、consumed0；无实际Search campaign。页面默认预算3/6来自未冻结能力的通用投影，不是本批获准预算；本批合同文件唯一预算1且实际0。console-search-context-terminal.json、console-terminal.html保留现场原视图，不把该BLOCKED_DATA说成当前完整来源缺失。来源consumer已独立验证成功；为已停止基线重启UI以显示READY没有研究价值。

现有lab.codex_generation.load_generation只投影生成/审批字段，review_generation只支持APPROVED/REJECTED，transition_review_metadata拒绝把已APPROVED改为相反终态。lab/scripts无UNDERPOWERED/S_SIGNAL预筛写入入口，也无通用证据注释API。不能以机械审批REJECTED伪装容量状态，不能制造source=SEARCH generation或ResearchRun。

最小无schema闭环：保留真实数据库不改；以实际Generation/Candidate/cohort/Profile/源码/来源SHA绑定本Git外JSON receipt，并在原ledger追加真实S_SIGNAL_EXPOSED/UNDERPOWERED关联记录和Issue链接。当前已采用该路径。若要求Console内直接显示，需要另授权极小的现有JSON metadata注释及读取投影；本轮没有实现，不把外部附件谎称已通过项目证据入口入库。只写未知JSON字段而UI不展示不能算完成UI闭环。

## 下一任务应先纠正容量设计

| 方向 | 样本/成本取舍 | 最小独立验证边界 |
|---|---|---|
| 减少同时成立条件 | 去掉复合条件可能增加原始事件，但实际可执行自然数未知；也可能加入噪声并增加交易费。优先讨论一条较宽机制的值前容量设计。 | 不在本ADA S删条件重算；另一个合规独立窗口事前冻结单条规则与容量门，先容量再native，不先看盈利挑条件。 |
| 改周期或持仓 | 更短bar不保证独立信息；更短持仓可能降低资金支出但提高周转费，降低持仓门只能在新批次事前说明。更长持仓会占用槽位并减少自然交易。 | 先用费用/最大持仓与事件间距的算术排不可能方案，不扫描已消费ADA S；不可用日历强制交易凑自然样本。 |
| 延长独立窗口 | 可增加日历机会、维护最小，但同资产已消费/封存年份不能拼入。此前14/年只是这个S的观测，不能预测未来信号率。 | 先查是否有完整、未消费且满足associated mark合同的较长S加独立D/H；否则是日历/数据成本，不能宣称立即可跑。 |

建议下一任务先比较“较少条件的一条日线机制”与“保留机制但真正延长未消费窗口”的成本和容量，再选择一个新值前方案，不机械轮换币。没有在本轮执行任何下一方向扫描。总体目标未完成；本Issue待监督验收后关闭，未自行关闭。
