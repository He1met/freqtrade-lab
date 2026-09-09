实现受限历史 funding 信号接线，先做 60–90 分钟纯合成原生可行性门；不承诺策略盈利。

验收范围：
- 使用固定 Freqtrade 2026.7 原生 DataProvider、merge_informative_pair 与既有离线 Backtesting.start 链路；不改 native、不自制 runner。
- producer/consumer 在填充前证明真实 00/08/16 UTC funding 事件完整性，保留真实零费率，缺失/重复/乱序/错误网格 fail closed。
- 固定模板在 UTC D 00:05 决策取得 D-48/-40/-32h 三事件均值；R1/R2 共用不可删除的有效性 guard，R2 唯一增量为 funding > 0.0001。
- 合成验证 289 根 OHLCV pre-roll、48h funding 内部烧入、未来不影响过去、00:05→08:05 原生持仓及 signed funding、stop/尾部/冲突。
- 若门通过，接入现有受限验证/生成、JSON Profile/source/Candidate 绑定及 Console/API 临时 SQLite 入口；单因素删除后剩余 AST 完全相同。
- 只进行 T0/T1 和一条 native 合成 T2、一条 Console/API 临时 DB T2。旧 NY/日线/探索绑定回归不破。

约束：六业务表不变，无新字段/索引/ORM/迁移/服务/任意数据路径。不得读取新市场值、下载行情、经济回测、正式 Candidate/ResearchRun 或交易。历史发布时间 UNKNOWN，32h 以上滞后仅为假设。探索不能晋级 Development。若需额外 source 衍生模块或合同扩张，先报告监督成本。预计总计 5–8 活跃小时，超范围先报告。工程验收不完整保持 Issue 开放；合并/关闭交监督核实。

冻结规划：decision.md SHA256 a04c6ea589a2cb213faab65cf20dcf31406c0165172989de0519675bb886121d；metadata.json SHA256 4f913a5addbbe4dd149b82b5ec67d4675d8e13d069c99a08e698dd4e76ee4a3e。
