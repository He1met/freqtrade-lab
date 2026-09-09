# 首次XRP新值之前的授权采用记录

监督任务01a05dcc-17fd-7972-9177-9fed95e4b07a已明确采用新普通SINGLE_BASELINE / INDEPENDENT_VALIDATION_REQUIRED的有条件资产级历史验证路径。不是旧exploration转正；不是已独立验证；总目标仍要求真正合格而非历史core通过。proposal.md与decision-addendum.md中有待root选择的事项，以本次明确授权为准；任何旧BNB结果与保护窗不变。

拟议S[2023-11-06,2024-11-04)、D[2024-11-04,2025-11-03)、H/Stress[2025-11-03,2026-05-25)。截至台账SHA8b6fb2c4141411da5f3d114ecb68800e27f868c9a0d2a3d0e2fe462da1cee2da，没有XRP同评分窗直接signal/PNL记录；未登记外部暴露UNKNOWN。XRP旧2022研究及未来H[2026-10-01,2027-04-01)不借用。

完整跨资产已知暴露来源是该133行原台账，原文件不重写，不把缺币名的记录视作未暴露；旧BTC/ETH 2020–2024多轮趋势/波动/日历研究，2025保护；BTC/ETH 2026-01及04–07多个信号研究、后期保护；AVAX 2026-07/08；LINK 2024资金/冲击；SOL 2024/2025通道及之后保护；NEAR/DOT 2026短周期；DOT/ETC/TRX 2024 S及2025 D QC/保护；XLM/ATOM/LTC多年S与随后D/H保护；BCH2023/2024 S与之后D/H保护；DOGE/ADA/BNB2023-11至2024-11 S已消费（DOGE D也执行），其余D QC/H保护。引用的是既有台账和已读S报告，不新增读取任何旧D/H市场值。全资产UNKNOWN[2026-05-31,2026-07-31)排除。相同年份的宏观/共同因子信息已被学习；新资产不是统计独立，后续D/H只是目标资产未读验证，最终仍须评估共享因子影响。

当前仅授权5个代表日fundingRate metadata请求（2023-11-06、2024-11-04、2025-11-03、2026-02-09、2026-05-24），每个半开UTC日转换为官方inclusive endTime=次日00:00-1ms，limit1000。最多5GET/5MiB decoded/10min，单请求30秒，无重试/重定向，失败停止余下。原始响应私有保留但报告不打印费率/mark；8h三事件及原分钟桶合同，associated mark必须正。该操作产生明确metadata暴露，不消费策略评分样本。

主/基准均采用已解释的原生末K exit/stop优先，余仓按open force_exit模型；平均native trade及自然episode均>=4320min，全阶段PF>=1.10。基准单次新增人工原生表达验证单列第3次synthetic；不重跑原2组。任何OHLCV、Generation/批准、市场native策略/基准及真实业务DB写仍未授权。

B(metadata)+C(第三次人工基准)全部通过，才获准开唯一新Issue并实施XRP绑定及限定比较附件/Console小工程；本记录不提前宣称它们通过。
