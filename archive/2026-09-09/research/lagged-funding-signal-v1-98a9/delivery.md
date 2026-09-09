# 工程交付与监督验收收口

最终收口：监督已验收固定 HEAD 并明确授权合并/关闭。PR72 使用
`--match-head-commit 71e42013305a9e085ffe77b3e79e5d59d78855c4` 保护合并，
2026-09-05T02:13:08Z 状态 MERGED，merge/remote main SHA 均为
`a0a6229dd75724e5cbd2f892eac0b8ebcb8b6e14`。Issue71 随后按工程已验收关闭。
关闭说明见 `issue-closure.md`；没有启动任何真实市场研究。分支、worktree、
全部原始 gate 证据保留。以下 OPEN / 等待核实内容是合并前交付快照。

- Issue https://github.com/He1met/freqtrade-lab/issues/71 OPEN。
- PR https://github.com/He1met/freqtrade-lab/pull/72 OPEN / CLEAN。
- 实现/远端分支 SHA `71e42013305a9e085ffe77b3e79e5d59d78855c4`。
- 基线 main `869b0d394a95f45bbcf0d25ae16dc61031a092ba`；初始本工作树 `dc82c61` 干净，安全切到本任务分支。原用户 checkout 未操作。
- 精确范围 10 文件，696 additions / 9 deletions；`scoped.patch` 保存完整差异。生产改动集中在固定模板、静态整 AST 接受、Generation/Candidate JSON 绑定、唯一 R2 conjunct 与 consumer funding 列表示。
- 六业务表无变化；native、producer、离线 adapter、全局配置无改动。工作树最终干净。

## 实际入口

1. 现有 Console 带显式 Search root / 冻结 exploration contract；既有 POST /api/generations 使用 `strategy_family=lagged_funding_signal_v1`。单 LINK/USDT:USDT、5m、max_open_trades=1 Profile。
2. R1 无 parent，R2 选择已批准固定 R1 parent。固定 source 放入受控 prompt；request 与 Candidate metadata 使用同一 signal_contract。缺失、改写、改成普通 family 不能绕开绑定。
3. R2 changed_factor=`entry_lagged_funding_positive_v1`；移除唯一 `lagged_funding > 0.0001` 后剩余 AST 全同。共享价格/连续时间/funding guard 不可改写。
4. 正常完整链仍通过现有 producer→prepare_search_data→source SHA/Profile/pre-roll/网格 consumer→现有脚本→Backtesting.start。standalone 策略只 import pandas/Freqtrade，无 lab 部署依赖。

## 验证命令与结果

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --with pytest --with pyarrow==25.0.0 python -m pytest -q -p no:cacheprovider --disable-warnings tests/test_lagged_funding.py tests/test_bounded_strategy.py tests/test_exploratory_session.py tests/test_search_data_producer.py tests/test_codex_generation.py tests/test_codex_generation_http.py tests/test_search_campaign.py tests/test_development_run.py tests/test_run_freqtrade_backtest.py
```

362 passed，36.71s；`t1.log`，258 条 Feather 弃用 warning，无 skip。

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --with pytest --with pyarrow==25.0.0 python -m pytest -q -p no:cacheprovider --disable-warnings tests/test_lagged_funding.py
```

增加原始 source failure 负例后 36 passed，2.10s；`t0-final.log`，42 warning，无 skip。与前者重叠，不加总成398。监督固定 SHA 独立复跑同专项为36 passed /2.25s。

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python tests/native_lagged_funding_gate.py /Users/shenjianpeng/.codex/runs/freqtrade-lab/lagged-funding-signal-v1-98a9/gate-05 /Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/freqtrade
```

原生最终合成 gate-05 PASS。native checkout 亲验 clean，HEAD `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`。同级 pinned venv，完整包 SHA snapshot 被现有 adapter 前后核验。真正独立 subprocess 中 PYTHONPATH 只有 native snapshot；不是靠测试 PYTHONPATH 才能加载策略。

- 原生原始 ZIP、argv、stdout/stderr 位于 gate-05/run-1、run-2。
- R1 5 笔 / R2 4 笔均纯合成。正常 00:05→08:05/480min；3月5日01:00 stop/55min，funding 0；其他日 +0.24 或 -0.16 funding 均按人工枚举值核验。无 ROI exit、force_exit，最后完整日正常退出。
- 21 个8h真实事件→161个小时行；真实零值保留。故意删掉真实事件后 native 确实补成0，因此只读native表不能证明完整性；producer和consumer先验拒绝缺失/重复/乱序/偏网格/小时填表。
- 三事件滞后与首个可用决策3月3日00:05、未来不影响过去、两轮共享guard、缺K线/零volume禁入、entry/exit互斥均通过。
- 实际 producer 配置接受 March–July/289，理论行数44065/3673/456；未读真实市场值。最终另以7日纯合成值执行现有 producer writer/provenance、prepare_search_data、消费者重新绑定。
- T2 HTTP 使用明确 synthetic fake Codex 可执行文件，通过真实本地HTTP生成/预览批准/父子绑定；无真实模型调用，无正式模型 provenance。

gate-01–03 保留原探针失败：producer配置不完整、native无pytest、runtime config缺字段。gate-04 是首个完整可行性门；gate-05 用最终部署模板并补guard/producer-consumer验证，未为美化结果重跑早期失败。

## SHA

- runner不变：`81dcf1f781a06aade4c8c7f31e85e3f38ba6430c599f45048b58bbd08cd687f5`
- gate-05/gate.json：`cb4f2b1a4823366273969150dc9cc0ae5761624b8abc8abf8b36468db11dee35`
- R1原生ZIP：`7bd0d9ebe5e8298a6c3f57cbc5bee1cc8224c2e4570b38ba9200a8a679d19621`
- R2原生ZIP：`5414165886a57840eba51fe86fb6028425d52eb69047ba4bce2e7e5825373c6b`

## 限制与下一门

本批没有取新市场值、下载、经济回测、正式Candidate/ResearchRun/Release、Holdout或交易。32h以上滞后只是保守历史as-of假设，archive实际发布时间 UNKNOWN；工程通过不能称策略合格或盈利。

按监督决定，后续用现有producer在新冻结合同下正式取得独立运行目录，不开发subset derivation模块，不改旧A/B source或SHA；独立目录仍是已见历史探索。实际采集须监督另行放行。

当前funding家族仅接受探索Generation，这一Candidate即使面对未来未见Dev窗口也不能直接晋级。若未来形成经济finalist，需先另行冻结独立验证协议/窗口、保留trial/exposure/source SHA，再授权最小合法handoff；现有探索隔离不可通过删除标签或造ResearchRun绕开。本次没有实现该handoff，也未把新独立窗建议并入本次授权。
