XRP 周动量研究缺少 Binance 标的身份和同成本基准的合法记录位置。本 PR 增加 XRP 身份，并把已核验的阶段比较摘要附到原 Candidate.metadata_json；基准不占用 Candidate、ResearchRun 或 Execution，不改变阶段门和 Release。Refs #107，保持 Issue 打开，等待监督固定 HEAD 审阅。

比较使用各自的原生 ZIP/源码/config/provenance 与相同阶段来源，复用既有 parser、sanitizer 和保守 funding/小时 MTM auditor，核算 `net / max(MTM_DD, 1%)`。同阶段幂等、冲突拒绝；后期全部绑定同一个真实主 Run。Console 在既有 Generation 详情以文本显示结果及“不是完整策略资格”的限制。

读取阶段数据前，D/H/Stress 的主 ZIP 路径必须逐字匹配已完成 Execution，且核对 archive/provenance/source/window。S 用显式受信 Search/artifact root，上述 DB 冻结 terminal 与相对原 ZIP 定位；sanitizer 派生放在独立 artifact-root/S，不改冻结 Search root。复用现有逐层 descriptor/no-follow 读取器。错 H ZIP/provenance/source/window 有 fail-on-read 测试。

验证：

- `PYTHONDONTWRITEBYTECODE=1 uv run --with pytest --with pandas==3.0.3 --with pyarrow==25.0.0 python -m pytest -q -p no:cacheprovider tests/test_research_comparison.py tests/test_search_protocol_rejection.py tests/test_prefilter_evidence.py tests/test_binance_source.py tests/test_futures_costs.py tests/test_codex_generation.py --tb=short`：126 passed，4 skipped。新增比较测试 24 项；既有回归通过 102 项。
- 新测试用完全发明的 2030 数据/ZIP，实际 argparse CLI、临时 SQLite、Console HTTP、真实 parser/auditor；持久化 campaign 绑定另有未替换的真实验证。附件集成 fixture 单独隔离 campaign 构造，不能称为真实市场全流程测试。
- `stoploss=-1` 基准源码通过现 runner 的 `_verify_strategy_input`、producer `_validate_strategy`、独立派生 provenance、真实 `_sanitize_raw_artifact` 和 parser。只有原生进程以发明的保存 ZIP 代替，没有运行额外 Backtesting/native。
- 4 个跳过项均为未改动的 `tests/test_binance_source.py::test_source_failure_cleans_only_owned_temporary_directory[conversion]`、`[write]`、`[publication]`、`[existing]`，其首个 `pytest.importorskip('freqtrade.data.converter')` 因环境未安装 `freqtrade` 包跳过。本次 XRP identity、transport 正负例、成本/来源及附件路径校验均已有通过证据；未为此安装完整 Freqtrade 或扩展测试范围。
- `git diff --check`、实际 CLI help/失败入口、`node --check` Console JS、`scripts/init_database.py --path <temporary path>`：通过；临时库 Schema 1、恰六业务表。

范围：7 文件，无 SQL/依赖/服务/runner 改动。全部新比较产物是合成测试；没有 OHLCV 获取、Generation/审批、真实业务库写、市场回测或交易。测试通过不代表数据就绪、完整研究通过或盈利。固定 HEAD 交监督审阅，不自行合并。
