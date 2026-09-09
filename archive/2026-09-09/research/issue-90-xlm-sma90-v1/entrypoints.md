# Issue90 值前冻结交付

仅执行了注册、静态合同校验和两个无网保护测试。未采集、未运行Search，未读取真实D/H。

- Profile `531e0fe0-2d97-443d-ad98-b3db5ce0bcb0`
- Generation `a68cc2a4-e6a0-4427-affb-f7d78f8246e6`
- APPROVED Candidate `d41d96ff-81df-4fdf-8d97-404a42d00f01`
- planned campaign `7954a20c-4088-47e6-8648-2a5bdf17a2a1`
- DB `research.sqlite`：Profile/Generation/Candidate各1，ResearchRun/Execution/Release各0。
- 源码SHA `2294a8a2e399c1f6503b8e5221cd455c5e31b0e1636da0b40d39c9f1025c1554`
- Profile文件SHA `ac03df917b0c11f0b5dbe3d10b41591e8d3b580c1bad975574e1a5de8d6b2e57`
- 原freeze receipt SHA `19dade280d99cbd7255131591acbcd407f3880863e2129d00feff02358dd752a`

`protocol.md`是原v2逐字节副本，SHA仍为`ba627b813510ed26cb5ace447d4673d27fd4a694d20e5211a9e323733c1cad4d`。工程状态由PR89 merge `9a5c00ba2ad1617645b67c1d0475508ba02c401a`替代旧的H阻塞描述，经济门不改。

原freeze正确记录当时尚缺预算硬限制；随后监督授权的`acquisition-preflight.json`追加冻结本次envelope及测试证据，标明只经该入口才有64次/60分钟硬限制。不覆写原freeze。预计1次instrument+13页100日（最后47日）=14次请求。CCXT零重试、HTTP adapter total retries=0、禁止重定向，失败也计数；第65次在网络前拒绝，计数日志失败亦不发网络。此为已有producer的执行保护，不是新行情实现。

## 下一步：仅在监督明确授权采集之后

```sh
export FTLAB_PROJECT_ROOT=/Users/shenjianpeng/.codex/worktrees/7183/freqtrade-lab
export FTLAB_NATIVE_SOURCE=/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade
export FTLAB_PYTHON=/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python
export FTLAB_RESEARCH_ROOT=/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-90-xlm-sma90-v1
cd "$FTLAB_PROJECT_ROOT"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$FTLAB_NATIVE_SOURCE:$FTLAB_PROJECT_ROOT"
"$FTLAB_PYTHON" "$FTLAB_RESEARCH_ROOT/acquire_with_budget.py" --acquire
```

当前未执行此命令。它直接调用已合并的`fetch_okx_profile_data.main`，输出固定在`source`。one-shot日志`source-attempts.jsonl`独占创建，失败不重用、不换根重试。producer照常清理不完整source；元数据失败账留在父目录。响应体不打印给模型。

source尚不存在，因此`search-plan-intent.json`只冻结Candidate/Profile/规则及预定campaign，source SHA为NULL、executable=false，不伪造正式Search plan。采集成功后才用现`prepare-search-data`入口绑定真实receipt/provenance SHA，再由现Console API生成一轮一候选计划；最大attempt=1，没有自动R2。唯一S执行仍需监督放行。

四类门的精确公式由原protocol绑定。现Profile机械gate只核native笔数、PF/净正和原生DD；不能替代自然平仓、逐腿滑点/现金、逐日净盯市DD、90日暴露组和去最大组集中度的监督资格检查。S若机械通过，仍先审全部S门再请求D授权；不预建ResearchRun。H bootstrap此阶段不实现、不读取H。现货选择不代表现货收益优势，合约保留未来候选。
