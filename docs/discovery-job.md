# 一次性来源到提案作业（Issue #137）

单命令负责固定URL获取、有限HTML文本提取、一次拟议的受限Codex提案、已有离线预筛及收据。当前只完成工程和合成验证；真实provider明确BLOCKED_TOOL_ISOLATION，审批参数也不能绕过代码硬阻塞。不创建调度器，不写Generation或数据库，不运行市场研究。两个已知BIS/MIT页面用于provider集成验证，不当作新发现或独立证据。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_discovery_job.py
```

默认仅输出PLAN_ONLY和canonical manifest SHA，不检查认证、不联网、不创建运行目录。监督批准固定包后，才给同一命令提供 `--execute-reviewed-manifest-sha <已批准canonical SHA>`。这个显式参数是防误运行的确认值，不是认证令牌，也不是自动获得授权的机制。真实试运行参数全部在 [manifest](protocols/issue137-discovery-job-v1.json)：每URL一次、最多2 HTTP，无redirect/retry；1MiB响应、20秒请求；1次CLI provider，180秒、1MiB stdout+stderr上限、256KiB最终JSON、192KiB提示词、0-3卡。绝对截止2026-09-09T00:00:00Z。到期不移动deadline；重新授权版本才可改变。参数是工程上限，不是经济门槛。

唯一固定运行根是当前OS用户的 `~/.codex/runs/freqtrade-lab/discovery-jobs-v1`，CLI没有registry/output-dir参数。job_id在根中绑定canonical manifest SHA（不是原文件格式SHA）；改变文件所在目录不能重置同一身份。manifest还绑定实现、schema、adapter与CLI二进制SHA。旧本地a6d6be9历史保留，本分支从main4934e1a开始。

一次非阻塞全根flock限定一个worker。HTTP和provider动作前原子写入RESERVED并fsync目录；失败/超时/进程退出不退还尝试，不自动retry。完成的阶段保存hash与状态；全部阶段完整而终态未写时，可以不调用provider离线完成。RESERVED但没有完成收据时只能INTERRUPTED_OUTCOME_UNKNOWN，不能凭猜测重发（即使有未绑定的final.json）。成功终态重复调用只核结果hash并返回原收据；漂移阻塞。进程组在timeout/超限/退出时清理，原始stdout/stderr只在内存中，有上限且不保留；必要event_count/status/hash才入私有状态。

UTC绝对deadline在新外部动作前检查；HTTP硬计时，provider循环检查wall clock，休眠醒来后过期就终止，绝不补跑错过动作。已完成的离线归档不受截止阻止。不能承诺休眠期间定时运行，未测试launchd、锁屏、钥匙串后台条件。没有scheduler或automation变更。

认证与无工具边界：

- 真实执行先由CLI自身运行 `login status`，仅精确接受 `Logged in using ChatGPT`；原始状态不记录。API key或未知输出都BLOCKED_AUTH_MODE。Python不读认证文件，不登录、不复制key、不兑换reset。环境仅传HOME/CODEX_HOME/PATH/LANG，剔除API key和自定义provider环境；实际exec再固定 `forced_login_method="chatgpt"` 与openai provider，禁用auth交互。CLI正常使用已有认证不等于把桌面会话权限当成后台API凭据。此阶段没有运行status，实际模式UNKNOWN。
- 固定CLI 0.153.4二进制身份；复用项目已存在的shell_tool默认shell开关和已知工具feature关闭机制，同时关闭apps/plugins/MCP关联、web、code mode、browser/computer/image、hooks、multi-agent、goals和auth elicitation等40个开关；启用skip_host_skill_discovery。exec忽略用户config/rules，隔离空workspace，mcp_servers空配置，web_search disabled。`unified_exec`部署控制仍true，不能将其报告false；默认shell开关实际probe false，但不能推断所有命令或文件工具均已移除。只读sandbox是额外限制，不是无工具证明。
- 本地无模型feature probe仅验证40个指定开关false、skip_host_skill_discovery true；unified_exec仍true。[官方配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)定义shell_tool仅为默认shell开关、unified_exec为PTY执行工具，未提供覆盖apply_patch/文件读取/全部外部工具的事前总禁用证据。公开help也未建立这种完整工具allowlist，当前固定二进制与公开实现的完整对应关系未核实。因此真实preflight在认证status、HTTP和模型调用之前硬返回BLOCKED_TOOL_ISOLATION，直接adapter调用同样硬阻塞；不可通过manifest或确认SHA开启。JSONL事后拒绝工具和read-only sandbox均不能弥补此缺口。诊断字段列出各feature实际状态及unified_exec例外，不再使用笼统VERIFIED_FALSE。plan等纯内存工具若将来允许，必须明确列入可审清单，目前不假称0工具已成立。
- 固定请求/stream retries=0并关闭unbounded_connection_retries，命令不重试。计数是一次CLI provider进程预算，不伪称已拿到供应方计费明细。模型选择gpt-5.6-sol、manifest及argv显式model_reasoning_effort="medium"，实际可用性未验证；不自动切模型。

官方能力依据：[非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)、[认证](https://learn.chatgpt.com/docs/auth)。本机只运行过公开help/version/features，未作真实认证/模型测试。若CLI或认证模式不支持约束，保留BLOCKED；不能启用付费API补齐。

HTTP文本提取不执行script/style、链接或源代码；不解压响应，不跟redirect；这里只支持UTF-8 HTML且不浏览其他链接。原HTTP字节仅hash，提取文本Git外缓存标为HTTP_HTML_TEXT_EXTRACT_NOT_FULL_HTML，绝不冒充#135 WEB_TOOL_EXTRACT。出版日期未知为null。模型locator必须是提取中的实际短字符串，但语义支持/因果/独立性仍是模型推断。#135只加显式protocol参数及content-kind适配，默认协议/SHA/输出不变。

验收分层：合成测试验证机制；批准后的真实一次终态才证明该手动独立进程provider链路。0卡合法；来源不支持当前双腿/跨场所执行的卡仍阻塞。没有真实运行前不写LIVE_PROVIDER_VERIFIED，更不宣称无人值守、经济合格或后台认证已验证。失败也冻结真实收据，不让模型自动修输入再问一次。

最小可行执行边界：需要现有ChatGPT认证主体可用的、在请求构造前提供可核验工具allowlist的受支持入口，明确排除文件读取/写入、命令及外部工具；目前CLI配置证据未建立这个条件。若只有现有任务会话工具权限，不能转成后台无工具认证/API。此PR不造代理、认证平台或改用付费API，不通过真实provider探针反推隔离。就当前边界，只能交付并验证可注入合成provider的状态机；真实链路阻塞是未完成事项，不称自主发现成功。
