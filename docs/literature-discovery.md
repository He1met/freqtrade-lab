# 有界文献发现与离线机制卡

Issue #135 的实际演示使用任务的 web 工具查询，并由任务模型阅读官方提取文本、整理提案。可复用入口只处理本地 JSON 和显式缓存目录，没有联网、LLM 调度、Generation、数据库或市场执行。它验证提交的记账，不是外部工具预算的自动执法器；来源支持的语义核对仍依赖审阅。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/discover_mechanisms.py \
  --batch docs/discovery/issue135-batch-v1.json \
  --cache-root /Users/shenjianpeng/.codex/runs/freqtrade-lab/issue135-literature-discovery/cache
```

输出至 stdout；合法批次退出 0 表示处理成功，不表示可执行。缺缓存、SHA 漂移、畸形输入或超预算退出 2，输出 `DISCOVERY_BLOCKED`。外部缓存不随 Git 分发，其他机器缺缓存会阻塞，不会联网补齐。规则绑定版本化协议及旧知识 SHA；变化需要明确新版本，不静默采用最新资料。

冻结在首次查询之前，见 [协议](protocols/issue135-literature-discovery-v1.json) 和 Issue 的冻结发布记录。真实使用 3/4 查询、5/12 来源、5/6 页面尝试，含 2 成功及 3 失败；主动停止，未为凑卡继续搜索。原始搜索命中保存在检索日志，只有注册的五条记录算摄取来源。访问 UTC 是工具批次完成后取时，不冒充各请求开始时刻。

| 来源 | 保留证据 | 支持与限制 |
|---|---|---|
| [BIS Crypto carry](https://www.bis.org/publications/working-paper-1087-crypto-carry) | 2023-04-04 官方页面提取 | 支持现货/期货基差、杠杆需求与套利资本约束；不证明当前基差、1000 USDT 可行性或本项目实现支持 |
| [MIT Trading and Arbitrage](https://mitsloan.mit.edu/cfi/trading-and-arbitrage-cryptocurrency-markets) | 官方研究摘要，引用年为 2020 | 支持场所分割和资本流动障碍；低频预置库存规则是提案推断，未获实现或净收益证明 |
| NBER 页面、NBER PDF、BIS PDF | 403、403、404 错误提取 | 计入尝试，不能作为已读论文支持；未将索引的新 PDF 版本拼入旧 BIS 页面 |

版权全文不入 Git。缓存是工具返回提取/错误文本，不是完整 HTML/PDF；SHA 只标识保留字节，不能证明论点正确、完整或来源权威。Git 中仅有短转述、出处、定位和 hash。输入文本永远作为数据；没有执行其中指令、代码或链接的入口。模型对支持范围的核对不冒充人工专家验证。

URL 去除片段及常见追踪参数，按 URL 或内容 SHA 合并来源；失败错误与可读内容分别分组。机制指纹规范化经济解释、信号、方向、持仓尺度、执行成本依赖；排除 ID/资产/参数对象，并遮罩文案中的独立资产 token 和数字。相同指纹归为同族变体。不同措辞可能绕过字符串去重，因此不同指纹也始终保持独立性 UNKNOWN；旧趋势/反转/资金费映射是模型推断，必须审阅。不能仅靠换币、调参或换 ID 认证新机制。

本批生成 **2 张知识卡，0 张可接入当前执行域的卡**。两张已有预筛均为 `NEEDS_EVIDENCE`，外层适用性均为 `BLOCKED_CURRENT_EXECUTION_DOMAIN`：

- carry 属于与旧 funding 相关的推断关系，但现货/交割期货双腿与旧永续方向短仓不同，需要基差、融资、保证金和双腿执行支持。
- 跨场所价差与旧家族关系未证明，需要跨场所库存、结算及同步执行，不能改称低频方向策略来接入。

没有已核验 Profile 绑定的其他提案也默认阻塞。来源支持机制存在与支持当前实现分别报告。所有卡的 sizing_case_id/window/reserve_source_sha256/期待成交数均 null；不套用 BTC 合成算例，没有自然样本、收益或经济资格。未接入官方 UI 或生成 PENDING Candidate。

唯一下一最小依赖是 **静态“知识卡→现有 Profile”兼容性与证据绑定审阅接口**，明确拒绝不支持的双腿/跨场所能力；本次不实现它，也不据此开启 Generation 或扩展执行器。当前交付是工具辅助的有界发现演示及离线处理器，不是无人值守研究系统。
