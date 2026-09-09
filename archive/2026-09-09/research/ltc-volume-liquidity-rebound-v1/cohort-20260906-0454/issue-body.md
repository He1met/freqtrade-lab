实施监督任务 01a05dcc-17fd-7972-9177-9fed95e4b07a 已批准的 LTC_VOLUME_LIQUIDITY_REBOUND_V1 最小合成检查、值前冻结登记及一次 S+D 源采集 QC。

唯一规则：OKX LTC/USDT SPOT 1d，日收益≤−2%、平方跌幅≥前30日r*r均值的2.25倍、量≥前30日均量2倍；过去3日无Q，前30日(V*Low)最小值≥500000 USDT，才于下一open入场。两日后下一open退出，价格stop8%、ROI空，stake500、E0=1000、一仓long-only。条件反转家族假设，不宣称volume增量或独立因子已证明。

UTC左闭右开：S[20210501,20240101)，D[20240101,20250101)，H预留[20250101,20260531)，pre-roll40。首次源只取LTC-USDT SPOT 1Dutc [2021-03-22,2025-01-01)，1381行；预计15次HTTP，硬上限24次实际HTTP含失败/30分钟/零自动重试，仅instrument身份及该历史端点。一次失败停止保留回执，不换根重试。成功只prepare-search-data为1015行；D仅producer/QC，H不取。

先用静态validator/纯合成样例确认因果指标、40前史、t事件→t+1买→t+3卖、3日Q去重、liq门、新仓同bar止损先买后卖。明确原生已反映的跳空不重复扣损；仅理想stop高于open才补保守差额。MTM预计清算费为未平仓估值准备，不重复写现金，退出后释放准备。

冻结最终协议、策略、真实Profile/批准Candidate逻辑快照、配置、native/producer/请求保护及参数SHA后一次采集。本Issue本轮不授权Search POST/screen-search/native smoke/真实Search、D/H/Stress、finalist导入、Release或交易。未来Search上限一轮一次，但需监督另授权。

代码基线7ae2b6b6c45cfb57c40a13dccd697ce1c57d08a4，独立3c7c worktree；项目业务代码/native/Schema修改预算0，六表不变。所有运行脚本与新非敏感SQLite在Git外，保留原项目与其他任务变化。验收：冻结SHA、真实请求数、1381源/1015S精确日期与QC、真实Profile/Candidate、隔离端口只读页面/preflight。验收不代表盈利。完成准备后Issue保持开放等待监督Search审核。
