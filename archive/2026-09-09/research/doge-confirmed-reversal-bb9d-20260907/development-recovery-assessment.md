# Development 技术失败：只读恢复评估

真实 ResearchRun `68fcd677-fd22-40e9-a6f1-78ee910b3a68`，Execution `711d5d63-d15e-4bee-9bc2-ea1bbd9c2026`，均 FAILED，verdict NULL、所有经济指标 NULL；六表计数1/2/1/1/1/0。唯一D已经消费，无重跑。

根因确认：`lab/research_console.py:3958` 用 `Path(sys.executable).resolve(strict=True)` 启动worker。Console原venv解释器有pandas；解析后 `/Users/shenjianpeng/.local/share/uv/python/cpython-3.13.13-macos-aarch64-none/bin/python3.13` 的prefix是基础安装，find_spec(pandas)为false。4194的Holdout worker有同形态问题。native回测使用独立冻结freqtrade-python，因此先完成；worker在资金审计import pandas时失败。

实际保留产物：development-evidence中完整CRC有效、可解析的已净化ZIP，SHA256 `31032c04d4cad38c3f8efda2cefb0dbc99376622386d85b1b060f209b9e0d278`，内含report/config/冻结源码，源码SHA仍61488a…05f；metadata存在。报告身份DogeConfirmedShockReversal3D/1d，评分start2024-11-04、末根2025-11-02。development-input manifest所有输入哈希核验通过。未据此写入或评定经济结果。

缺失：_sanitize_raw_artifact写了ZIP/meta，资金审计失败于写provenance之前。execute_development_run的finally删除runtime，所以原始未净化ZIP、runner summary、原native stdout/stderr未保留；外层stderr只有真实traceback。这些不能伪造或用重跑替代。完整清单在development-failure-inspection.json。

现有入口结论：没有可直接使用的完整恢复入口。_sanitize_raw_artifact需要真实CompletedProcess/runner summary；import_backtest_execution要求完整provenance且Run为RUNNING，finalize_development_gate也拒绝FAILED。直接重置数据库状态、补造CompletedProcess或把幸存净化ZIP假称原始ZIP都不成立。重新调用run_development_candidate会重放D，禁止。

最小工程修复建议（待授权）：只修D/H两个worker解释器传递点，保留venv绝对调用路径而不解引用；可检查解析目标是否可执行，但不能拿解析后的路径启动。无需安装全局pandas或改策略。定向回归用临时venv及仅venv可见的小marker模块，验证真实worker解释器prefix及import语义，覆盖D/H argv，不跑native、不重跑整套测试。

本次Run处理建议：保留FAILED及原始错误。可另行授权用已存同一ZIP/源/manifest作只读逐笔资金与13门外部审阅，明确为幸存产物审阅，缺失执行provenance项UNKNOWN；它不能自动变成项目成功或开启H。若要求项目内同Run恢复，需要单独授权一个只接受此类后处理失败、严格绑定Run/Execution/ZIP/manifest/源码、原始凭据缺失如实标记、幂等且原子、绝不调用native的窄恢复入口。现有provenance合同不支持这些UNKNOWN，必须先决定是否接受不同恢复凭据，不应为了本次正负结果放宽既有原生验证标准。

本次没有修改仓库、安装依赖、修改DB、生成新Candidate、再次采集或回测。H/Stress仍SEALED_UNREAD_UNACQUIRED。
