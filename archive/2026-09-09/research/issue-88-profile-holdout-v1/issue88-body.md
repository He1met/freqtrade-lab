## 问题与目标

现Profile-driven spot 1d Development不能经实际Console入口继续同一ResearchRun的HOLDOUT/HOLDOUT_STRESS：H能力/门/物化与execution仍绑定旧5m路径，未来H-only来源缺少独立追加绑定，Profile wrapper拒绝Stress费用倍率。补齐最小现货日线闭环；工程通过不证明策略盈利。

## 授权范围

当前7183工作树、固定Freqtrade2026.7 / 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5及原venv不改。保留六表及D原快照/hash；H-only追加来源经显式授权绑定同research_run_id。调整现holdout_run、Console、现producer及应用wrapper的阶段绑定，动态timeframe/Profile gate、Stress倍率及同run结果展示。附加研究统计只保留既有JSON/receipt，不建评估平台。

不新增表/字段/索引、native修改、新runner、通用多市场平台、Release/Demo/交易。当前所有真实行情/真实H及预热不读取；XLM草案收益门不因工程改变，剩余唯一真实S需工程验收后另行冻结放行。

## 验收

- 未授权不读取H；D快照和原来源hash不可改，追加H收据绑定同run、Candidate、Profile、窗口与原生身份。
- 实际HTTP授权接通spot1d H及Stress；默认封存、重复授权拒绝；门/配置/市场/窗口/hash被篡改在副作用前失败。
- Profile阈值和timeframe全程绑定；只有HOLDOUT_STRESS接受已冻结倍率，其他场景拒绝漂移。
- D/H/Stress原生artifact同research_run_id，H两结果原子附加，实际Console诚实展示，不自动Release。
- T0直接改动测试，T1相关旧5m/Profile回归，T2临时六表DB真实HTTP授权与原子结果绑定。
- 一个纯人工合成native端到端批次，最多3次native调用（D/H/Stress各1，失败也计入）；不是mock-only成功。正常纯函数/HTTP stub单测可针对性迭代。
- 交付精确diff/测试、实际入口、native调用账、远端commit/PR及恢复命令；监督验收前不merge或关闭Issue。

预计12–24主动工程小时；若超出上述边界先交监督判断。监督任务01a05dcc-17fd-7972-9177-9fed95e4b07a。


## 2026-09-06 实际 native 验证发现与授权调整

v1 纯合成批次 D/H/Stress 各调用一次，共3次。D暴露 importer 旧的永续 domain 限制；严格增加 spot/futures domain 映射后，复用既有持久 ZIP 经现 importer+finalize 导入，无 D 重跑。H/Stress 均完成 native 并产生可解析 evidence，但跨场景 calendar span 和 H execution.timerange_end 两处固定5m导致原子附加失败。v1 结论为 NATIVE_EXECUTION_PASS / ATTACH_FAILED；原失败 DB/HTTP terminal/收据保留。净化 evidence ZIP 不能称逐字节临时原始ZIP，后者由既有清理流程删除。

必要范围增加 lab/backtest_artifact.py 严格 domain 绑定及 lab/research_bundle.py 按已验证5m/1d计算末根长度；修复 holdout_run 的同源末根写入，其他三场景身份/成本/窗口及SHA不变量保留。

监督已撤回行政状态恢复方案，不修改v1失败DB、snapshot、时间字段或receipt。明确追加一次新 producer SHA 下的 v2 纯合成验证：最多3次 D/H/Stress各1，累计 native 上限6，失败计入；v2再失败只读诊断，不自动开第三批。该工程测试预算调整不适用于真实市场Search/H，不改变策略收益门或放行真实数据。
