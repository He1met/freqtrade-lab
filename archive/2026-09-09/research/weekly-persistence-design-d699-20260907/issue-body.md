## 问题与结果

XRP周尺度持续动量已经完成原生人工序列时序证明及5个代表日funding metadata QC，但当前只支持BCH/DOGE/ADA/BNB身份；同成本buy-and-hold基准也缺少合法、明确非Candidate/ResearchRun的比较记录入口。本Issue只实现XRP身份绑定与限定比较附件，保留个人六业务表，不构建研究平台。

这是新SINGLE_BASELINE / INDEPENDENT_VALIDATION_REQUIRED的有条件资产级历史研究；其它币同期学习披露在冻结protocol，绝不宣称全局未见或历史过门即找到合格策略。旧BNB完整协议REJECTED保持不变，任何旧保护窗不借用。

## 前置证据与授权

- 代码基线97b5e5dd45605655e25574e0d6948acee20aacd5。
- 主策略两组synthetic 2次，48断言通过；单列基准synthetic第3次仅1笔1x long，stoploss=-1对应实际零止损价，周内无重入，无网络/真实市场。
- metadata恰5 GET、1841 decoded bytes，5代表日均通过三8h事件/原分钟桶/associated mark检查；只保留metadata有限暴露，非完整源就绪，未读取OHLCV/信号。
- ledger最新SHA 1b6b3c2cb2156ebaa8aae2f5907d2cce8efa23f58cdb7f367429475b1cc59fbd；原锁追加一条，旧字节前缀保留。
- Git外证据根 `/Users/shenjianpeng/.codex/runs/freqtrade-lab/weekly-persistence-design-d699-20260907`。监督任务已条件授权本Issue与最小代码；不授权真实业务DB、Generation/批准、OHLCV、任何native市场策略或基准。固定head小PR给监督审阅，不自merge。

## 最小附件与文件范围

- `lab/futures_costs.py`：XRP pair identity，复用已有wrong-pair测试模式。
- `lab/research_comparison.py` + `scripts/attach_research_comparison.py`：薄CLI严格验证一次附件，复用原native artifact/cost解析，Candidate.metadata_json保留原键，仅写阶段比较附件及updated_at。
- `lab/codex_generation.py` / `lab/research_console.py`：strictreader接受并验证限定新metadata键，现页文字显示主/基准成本结果及完整比较判决，无新页面/服务。
- 定向临时DB、纯synthetic archive及只读API测试：无真实行情/旧DB。

限定schema按候选绑定阶段S/D/H/STRESS；冻结protocol SHA、主Candidate id、stage、Search campaign id或真实同一主research_run_id；primary/benchmark各自策略/config/ZIP/provenance SHA、相同原始acquisition父SHA与同阶段source SHA、同窗口/钱包/stake/fee/资金合同、各自执行次数receipt（恰1）及派生审计。比较值由真实artifact解析与成本证据验证，不能信任任意传入PnL。只把已验证摘要/证据引用存入metadata，原大文件留Git外；基准不是candidate finalist，也不创建Generation/ResearchRun/Execution行。每阶段immutable/idempotent，冲突/非法hash/错stage/source/code/window/fee先于写入失败。

基准必须有自己的派生provenance，绑定同一raw父与阶段源，不能把主策略收据替换成基准SHA。已有低层native runner用于后续授权调用，本Issue不新建runner或跑真实基准。该附件仅记证据与比较判决，不改变core stage gate/Release；S完整外层PASSED必须含比较门，后期仍监督逐门审查，不新增通用审批系统。

## 验收与边界

恰六表不增表字段索引，保留Generation及其它Candidate metadata与reader兼容，重复相同附件不重复写、不同附件冲突。CLI实际用户入口与Console只读结果在临时synthetic DB验证。哈希/身份/同来源/次数/阶段失败不能写任何业务行。通过重点测试后提交固定head PR，不自合并、不关Issue。工程主动目标2–4h；发现新增范围先向监督报告。经济native预算S/D/H/Stress各主1+基准1是拟定上限，当前许可仍为零。
