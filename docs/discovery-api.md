# Responses API 验证协议：Issue137 / PR138

用户2026-09-08明确继续，并授权首轮累计最高5 USD及专用API密钥的程序使用。新API协议替代旧ChatGPT CLI-only局部边界；不涉及市场/数据库/Generation/调度。旧9382c92无工具隔离不足的证据和旧manifest保留，CLI路线停止。当前代码删去该未使用的CLI诊断/子进程代码，直接发一个官方HTTPS请求，没有本地工具或函数dispatcher。

当前独立身份 `issue137-responses-api-validation-v1`；不是重用旧CLI任务，也不是移动失败研究窗口。新绝对截止2026-09-10T00:00:00Z；两个既有BIS/MIT URL只是集成验证材料，每个最多一次20秒/1MiB，无redirect/retry。一个API请求<=180秒，0-3卡。默认入口只计划，不联网：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_discovery_job.py
```

监督审固定头后才提供已审canonical manifest SHA给 `--execute-reviewed-manifest-sha`。此次授权只准备，没有执行真实请求。该值是防误运行确认值，不是密钥。

## 请求与价格

固定 `gpt-5.4-mini-2026-03-17`；官方模型页支持medium、Structured Outputs、Responses及400k context，标准输入0.75 USD/M、输出4.50 USD/M。价格核对日期2026-09-08 UTC。[模型与价格](https://developers.openai.com/api/docs/models/gpt-5.4-mini)

请求固定 `tools=[]`、`tool_choice="none"`、`reasoning.effort="medium"`、`text.format` strict JSON schema、`max_output_tokens=8192`、`truncation="disabled"`、`service_tier="default"`、`store=false`、非stream/background。没有previous response、conversation、文件附件、代码工具、MCP或外部dispatcher；只上传显式来源文本和schema。[Responses定义](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)、[结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs)

输入预算使用模型完整400000-token上下文上界，而非字符/token经验比例；这已经覆盖提示词、schema和API framing。请求本身另限256KiB、提示词192KiB，并关闭自动truncation。服务端context限制是接受请求的token硬边界：超出不会被应用当作更高预算请求继续。输出8192上限包括reasoning收费tokens。保守费用：400000×0.75/1M + 8192×4.50/1M = **0.336864 USD**。没有缓存折扣、区域处理或priority假设；不是实际费用估计，更不是花满5 USD的目标。

固定用户registry根 `~/.codex/runs/freqtrade-lab/discovery-jobs-v1` 下的 `api-budget-v1.json` 使用整数micro-USD累计。单worker锁内，在请求前先fsync完整336864预留，再写provider RESERVED；累计超过5000000拒绝。两步间崩溃仍保留全额charge，重启不可再发。成功/401/429/timeout/未知结果都不退预留、不自动重试；usage仅记录真实可用token值和估算费用，缺失不是0。已有完整阶段收据可以离线完成。终态重复不请求、不再次收费；换manifest文件目录不能重置任务身份，budget缺失但有provider历史会阻塞。SDK未引入，http.client不带应用自动重试。

## 输出与密钥

只接受completed、唯一assistant message中的单一output_text JSON，逐字段验证既有schema。正常reasoning元数据允许但只校验类型后丢弃，summary/加密内容绝不拼入候选证据。拒绝refusal、incomplete、多个message、工具调用、未知输出类型或畸形JSON；不自动再问模型。返回数据永远不执行。源locator必须出现于缓存文本，语义支持仍待审，当前不可执行机制仍阻塞。

程序只读取专用环境变量 `FREQTRADE_DISCOVERY_OPENAI_API_KEY`，不读取OPENAI_API_KEY、旧provider key、ChatGPT认证文件或keychain。当前仅核presence=false。没有可用openai-platform-api-key工具，不安装插件。代码只向固定 `api.openai.com:443/v1/responses` 发送Authorization，无代理继承、redirect或备用endpoint；异常仅留固定错误码，不打印headers、key或响应原文。缺key在HTTP前返回BLOCKED_MISSING_API_KEY，不等于旧BLOCKED_TOOL_ISOLATION。

安全配置方式：由用户在自己本地终端，以不回显的交互输入设置专用环境；不要粘贴到聊天、命令字面量、Git或日志。以下仅说明配置，不自动执行请求：

```zsh
read -r -s 'FREQTRADE_DISCOVERY_OPENAI_API_KEY?专用 API key（不回显）: '
export FREQTRADE_DISCOVERY_OPENAI_API_KEY
```

完成固定包审阅后，在同一终端运行已审命令；随后 `unset FREQTRADE_DISCOVERY_OPENAI_API_KEY`。不自动充值/购买余额，不把平台提醒上限替代本地硬预算，也不保证该key在别的程序中的消费受本项目约束。本机配置不会传给模型。

全部旧状态机约束保持：原子文件、动作前reserve、单worker、绝对deadline、崩溃不重发。当前仅合成测试；真实成功和真实费用须等唯一运行收据成立。无需为缺key提前终止工程，但不得用其他凭据替代。
