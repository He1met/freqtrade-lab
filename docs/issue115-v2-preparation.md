# synthetic/7 V2准备：硬敞口合法全平与暂停

监督采纳的评分前新语义，仅用于下一工程验证。旧V1 JSON/SHA、原audit与synthetic/6负结果
不改判；当前0新增native/0真实预约，市场false。新state仅在纯内存计算，无schema或服务变更。

- V1 semantics SHA：5fb7ee5d01920eaa91eafd936569c6c7a15fbdf5708c16162fd49537d8b7848a（未变）。
- V2 semantics SHA：9773d03346b89822a8495a3d5e6566cd8895c3c83e377be63b74b9f80477e784。
- V2 input SHA：e83a58fc388f88e680555568e52028b2f87864cab5cfe2e3223de31a5bbf2119。
- 完整新code/input/source清单：issue115-prepared-binding-v2.json。
- 真实预算账本仍4813b776b6d23c44615fd0aaf7141fe407e00ed421ba1a8e5d1b491efc960d72，7槽/6次实际native。

## 行为与适用范围

V2调用V1不变的信号/生命周期/风险计算，再检查实际敞口与合法量化后的目标。
实际已经超过40%单币或80%组合，且削减目标仍不能恢复上限时，才选择原分配中需要削减
的资产，发全量reduce-only意图；量化后仍超限也触发。没有硬超限的普通小目标变化仍用V1。
两币各40%意味着当前80%门在数学上受单币门覆盖，但仍按组合目标实现，不按收益选币。

全平量必须与真实库存完全相等，并满足step/min_qty/min_notional/max_qty，不假定交易所
或原生豁免最小名义。若不合法，保持实际库存、BLOCKED并禁止组合新增风险。
合法全平仅是pending意图，保留原V1告警于v1_unexecutable_reductions，V2审计仍要求实际fill
在最早时点全平。不能把“发出目标0”当作已平或通过。

只有实际quantity=0且最近周期flat receipt>=请求时点才确认；旧周期时间不会放行。
确认后暂停到**严格下一个UTC午夜**：01:00确认到翌日00:00；恰在午夜确认则再到次日午夜。
必须有该边界或之后的新完整日线decision才恢复；没有decision不能仅凭时钟重开。
存续episode继续老化/止损/到期；暂停期不启动该资产新episode，不制造自然样本。

旧消费者仍保留verify_binding V1；V2通过独立verify_v2及RiskDecision封装显式调用，不覆盖
原常量。预算兼容旧记录：synthetic/6仅V1、synthetic/7仅V2；synthetic/8未分配版本而拒绝，
未知版本拒绝；技术retry仍必须同input/source/semantics失败链，当前未授权任何retry。

## 新固定输入与审计

独立人工fixture V2保留日线趋势/反转机制和第97小时mark50%不利冲击。
把原第5小时gap移到第29小时，让全平后的存续趋势能在次日恢复并建立第二持仓周期；
第25小时high小扰动覆盖新周期闭合小时观测。参数没有按收益/DD挑选，尚未运行原生。
V1输入保持b3a14a...f079cfce不变，绝不重放synthetic/6。

预期覆盖：实际首日对冲家族产生净空 → 第1小时硬敞口小额减仓不合法而全平 → 真实确认
后暂停至下一日 → 第24小时实际恢复持仓 → 第二周期再次确认/暂停 → 后续halt真实清仓。
新audit_v2不再要求V1已不适用的第3小时空转多/第5小时gap成交；V1审计文件未改。
新审计要求每次fallback库存/当时实际delta复算、同小时清仓、严格暂停无entry、次日恢复
真实entry、至少两周期flat证明、暂停episode仍老化、halt同小时实际退出及净fee/slip对账。
任何覆盖缺少或残余未处理仍失败；控制通过和20%DD门独立，冲击越门照旧报告风险失败。
cash不足原生未覆盖、真实funding结算UNVERIFIED保持，不生成市场经济结论。

## 入口及待监督执行计划

准备入口（已运行，仅元数据与固定输入，无预约）：

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python scripts/prepare_portfolio_causal_probe_v2.py --native-source /Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade
```

dispatcher支持显式--slot synthetic/7，选择对应完整manifest并在单writer锁内复查；
预约/checkpoint先于native、180秒、不可覆写、失败占槽、执行后复验及终态checkpoint沿用。
监督未放行，**当前不执行dispatcher**。将固定HEAD/input/code/semantics清单交审后，
才可决定是否放行现有fresh synthetic/7一次；失败先报告，不自动retry。

106项非原生测试通过，锁定native环境仅完成V2类导入，没有构造/start。
CODE_FILES当前与V2清单均包含portfolio_native_export.py；监督已纠正此前漏文件评论。
旧execution prepared manifest保持历史快照，不写入新依赖或新授权。
