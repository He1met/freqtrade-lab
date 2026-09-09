## XLM_SPOT_SMA90_TREND_V1 值前冻结

唯一策略按既有protocol.md v2执行，SHA-256 `ba627b813510ed26cb5ace447d4673d27fd4a694d20e5211a9e323733c1cad4d`。工程前置Issue88已关闭，PR89 merge `9a5c00ba2ad1617645b67c1d0475508ba02c401a`。不因工程合并修改经济门。

本阶段仅授权新隔离根/非敏感六表研究DB，绑定Profile、Generation/Candidate、SINGLE_BASELINE_V1和事前计划/成本/窗口/预算收据。零行情采集，零Search，D/H封存；完成后交监督放行一次source及唯一真实S。不自动R2、换币或换参。

XLM/USDT spot 1d，SMA90仅多、下bar成交、20%价格止损、无ROI/追踪/加仓。E0=1000，固定stake500，每边原生fee .001；基础滑点每腿另扣.001，敏感性额外fee .001+slip .002，原生手续费不重复扣。PF1.0、原生及逐日计成本DD≤20%。经济/风险/样本独立验证/集中度四类门均以原protocol确切公式为准；原生机械finalist不代表全部监督资格通过。

UTC左闭右开：S2021-05-01/2023-01-01，D2023-01-01/2024-07-01，H2024-07-01/2026-05-31。预热90日。所有资产2026-05-31/2026-07-31保守排除。首次source仅S+D及预热，D只供producer/QC隔离，模型不读值；H不采。历史曝光证据有限覆盖，UNKNOWN不伪造。

时间容量上界：S610天最多6个完整90日组；D547天最多6；H699天最多7；D+H1246天最多13，联合门要求12。不是数学不可能，也不保证真实事件够；不足按UNDERPOWERED终止，不救门。

source预案一次60分钟、HTTP硬预算64（含元数据和分页、无自动重试），须值前核对实际producer路径请求量及可执行性后由监督授权。真实S最多一次30分钟。S全部门通过后监督核准D；H/Stress仍需用户另行授权，Release/交易未授权。现货是本轮选定核算路径，不是收益优势；合约保留为未来候选，不在此Issue扩支持。

验收：准确ID/源码和Profile/hash、费用现金及资格门绑定、值前receipt、唯一入口和预算、源及native身份；采集和Search均未执行。范围内不新增平台工程或H bootstrap服务。


## 当前实际状态（2026-09-06）

Profile/APPROVED Candidate及协议收据已冻结，新增Git外一次性envelope经监督精确SHA授权后采集成功：14/64实际请求，0重试，1247行spot日线，producer记录0缺口/重复/未闭合bar。receipt SHA210121a9f225dbc7ad6686acc515b9606d4a8551ff3fdaec82df6d1e8ac3ed3f，provenance SHA2e2b2e6c66d2d4e546db753e830cdcaaf7fa537300c7694d3b6609a58e40f026。source/raw价格未输出给模型。

消费者prepare-search-data随后在市场值读取/新Search root发布前失败：`Search window exceeds its bounded duration`。现`lab/bounded_research.py:_profile_window_contract`及Search plan validator上限366天，无法接受冻结的S610/D547天。当前SOURCE_ACQUIRED_CONSUMER_BLOCKED，真实Search=0，无经济结果，无ResearchRun，不缩窗、不重采、不改门；已交监督裁定最小消费者合同范围。

完整控制证据：`/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-90-xlm-sma90-v1/`，含原protocol、freeze-receipt、追加acquisition-preflight、source-authorization、逻辑DB快照、source-attempts及source-consumer-status。旧freeze如实保留原预算保护未完成的准备状态，由后续收据追加绑定，不改旧hash。


## 已授权窄消费者修复验收

仅lab/bounded_research.py、lab/development_run.py、lab/holdout_run.py及针对测试：已验证Profile spot1d每阶段资源上限1830日，预热≤512，总≤2342日线；这是资源上限，S610/D547/H699及经济协议不改。统一小helper，legacy5m/futures1d仍366，旧60D/30H分支不变。D freeze/snapshot/物化均传Profile，H源授权前检查资源界限。

原producer/native/schema不改；原source打包仅两个producer源码，不绑定当前consumer SHA，故原始source/receipt/provenance/data/control保留不变。少量参数化边界T0、受影响T1、同一真实source消费者QC（零native/回测）后提交PR待审。保留exit2失败收据，成功追加新consumer身份；未验收不得merge/close90，不得触发唯一真实S。
