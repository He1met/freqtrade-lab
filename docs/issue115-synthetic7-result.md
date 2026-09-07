# synthetic/7实际结果：控制通过，风险门未通过

监督精确放行固定HEAD 767fda5a00c215f8b4aa63b55db2c5f26474ab94与V2准备清单后，
本地/远端/manifest核对一致，仅执行一次。构造1、Backtesting.start 1，10 trades/20 orders，
120小时trace，callback fatal=0。原生ZIP、trace、bindings、结果、日志及证据SHA见
`issue115-synthetic7-actual-receipt.json`。没有retry或synthetic/8。

## 三层结果分开

1. **V2控制审计PASS / budget SUCCEEDED**：实际硬敞口全平、最近周期flat确认、
   按资产暂停至严格下一UTC日线、真实日线恢复及第二周期、存续episode、halt即时清仓、
   实际fill fee/slip净权益对账均满足新审计。不得用于改判synthetic/6。
2. **20%回撤门FAIL**：最大mark DD=25.6812583254182721374%；固定不利mark冲击未改。
   合成成本后净收益=-5.761596820833746054 USDT，fee+slip=7.683483600000099384 USDT。
   这些仅为合成观测，不是市场策略经济证据，不从与旧输入的差额推导改善结论。
3. **40%/80%持续合规=false**：控制前真实库存确实三次超限，之后及时全平不抹掉超限。
   原trace库存/权益与固定输入同小时open重算占比如下，重算字段不冒称原trace保存值。

| UTC时点 | 每币实际库存 | 每币占净权益 | 总名义占净权益 | 当小时实际成交/残余 |
|---|---:|---:|---:|---|
| 2019-10-03 01:00 | -3.883 | 40.059288% | 80.118576% | 每币买回3.883，残余0 |
| 2019-10-04 01:00 | +3.837 | 40.036152% | 80.072304% | 每币卖出3.837，残余0 |
| 2019-10-05 01:00 | -3.790 | 40.012089% | 80.024177% | 每币买回3.790，残余0 |

每次真实确认后的暂停边界分别为10-04、10-05、10-06 00:00 UTC；暂停期无新entry，
最早适用日线有实际恢复/新周期证明。halt在10-07 01:00，两币真实库存各+2.351，
同小时各卖出2.351，残余0；下一小时库存0。完整精度与成交delta见JSON实际收据。

## 预算、限制与保留项

预算现累计8个已占槽、7次实际原生调用；synthetic/7事件RESERVED→SUCCEEDED。
ledger SHA=a828469373802b7296a19d15bb79735d3adf30ca31c7201e4ff881b59e969e18。
剩余fresh synthetic/8与retry/2–4均未获授权。未追加测试调用，没有市场/保护窗读取。
原synthetic/6 ZIP/trace/log/FAILED evidence等SHA逐一验证不变，负结果永久保留。

cash不足原生仍NOT_COVERED_NATIVE；真实funding结算UNVERIFIED；市场准入false，
市场经济结果NULL，官方UI未新增发布。前106项非原生测试为工程验证，不是风险证明。

为满足完整异常栈保留，启动时仅加只读Python异常观测hook，执行已审dispatcher脚本，
未修改任何已绑定文件。日志的SystemExit:0是正常成功退出记录，非失败；原native无重试。
当前只提交终审，不自行合并/关闭；下一市场前置门和风险含义仍由监督结合证据裁定。

## 实际启动包装器与批准清单差异

已审清单固定的是dispatcher及其依赖；本次唯一启动命令在进入dispatcher前额外加入
Python异常观测hook，以满足完整异常栈保留。该包装器**未纳入原批准CODE_FILES/manifest**，
属于实际启动方式的差异，不能把主文件没改等同执行环境完全未变。

实际cwd为`/Users/shenjianpeng/.codex/worktrees/1b63/freqtrade-lab`，shell启动部分为：

```sh
set -C
PYTHONDONTWRITEBYTECODE=1 /Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python - <<'PY' > /Users/shenjianpeng/.codex/runs/freqtrade-lab/btc-eth-portfolio-v1/synthetic-7-dispatch.log 2>&1
# stdin完整源码见 receipts/synthetic7-actual-launch-wrapper.py；原调用此处为该文件逐字内容
PY
```

上面注释仅用于文档指向，不是实际stdin的一部分。完整stdin源码从本次已记录工具调用
逐字整理到`docs/receipts/synthetic7-actual-launch-wrapper.py`，运行后SHA256为
`031b7248053aa034655102cd8b0c453a44f0610c363c981d8b290755bdbde722`。
来源是调用记录，不是运行前落盘文件；运行前包装器独立SHA记录为UNKNOWN，未补造预冻结证据。

源码只安装sys.settrace observer、设置与获准CLI一致的sys.argv并runpy执行同一dispatcher。
异常事件命中dispatcher文件时打印完整traceback；没有赋值frame.f_locals、改策略回调、
输入、订单/撮合、局部变量或策略返回值。trace函数return值用于注册跟踪函数，非替换
被跟踪函数返回值。该结论来自完整包装器源码核对；跟踪的运行时开销未测量，记UNKNOWN。
原批准文件的执行前后哈希校验通过；此事实与“存在额外未绑定的观测包装器”同时保留。
不因补披露而新增运行，也不据此抹去控制前敞口超限、DD失败或任何数据资格缺口。
