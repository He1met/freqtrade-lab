# #131 修正实现探索复核准备包

批次为 `CORRECTED_IMPLEMENTATION_EXPLORATORY_REEVALUATION`。当前授权仅准备，未批准native执行。复核动机是#127确认、#129修复的合法网格目标丢失，需要完整原生消费者验证修正实现；不因旧净收益选择模式或改策略。准备完成后由监督按固定SHA和十份manifest明确放行，另建真实activation；待批模板不会被运行入口接受。

## 固定复核范围

复用已消费探索片 `[2024-08-01,2024-11-01)` 和原warmup `[2023-11-01,2024-08-01)`。旧prepared Feather/assembly/events逐字复制、逐SHA验证，无重新转换/GET。五mode按原顺序A-trend、A-reversal、B、C、half-risk-B，先base后stress，各一次；central63/2、1000USDT、1x、费用/滑点/资金费/风控/退出/最后一小时全平及精确gate不变。唯一交易行为修正为合并于`1fce623626a843050ba55a8b5acf6964cd2e5cb6`的`EXACT_COMMON_SCALE_V1`。

新十键不覆盖旧十键，不借technical retry重放成功记录。旧manifest/activation/output/净值及“受实现缺陷影响”定位永久保留；新manifest绑定对应旧manifest和原证据文件SHA。旧18调用完整字节prefix继续验证，原checkpoint继续使用。后61日没有manifest和解封入口。

## 预算一对一映射

历史说明纠错：旧#121说明将退休资源称作“原24 training前20槽”不准确。已冻结机器列表实际包括fold-1 training、fold-1 validation base/stress及fold-2 training前2槽；始终以机器key列表为准。本次不改旧activation或追改原映射。退休是未用预算slot重分配，不表示已读取原validation数据；新批不是原验证，其实际日期/用途仍是已见92日探索片。

新键前缀均为 `CORRECTED_IMPLEMENTATION_EXPLORATORY_REEVALUATION/`；右列均有前缀 `BTC_ETH_PORTFOLIO_V1/`。资源名称是原预算槽身份，不表示本次执行对应原fold或改变窗口。映射验证原96目录和此前20个映射，拒绝重复/未知/已占用资源。

| 新键后缀 | 替换的精确未激活资源后缀 |
|---|---|
| base/A-trend | fold-2/train/trend-84 |
| base/A-reversal | fold-2/train/reversal-1.5 |
| base/B | fold-2/train/reversal-2 |
| base/C | fold-2/train/reversal-2.5 |
| base/half-risk-B | fold-2/validate/base/A-trend |
| stress/A-trend | fold-2/validate/base/A-reversal |
| stress/A-reversal | fold-2/validate/base/B |
| stress/B | fold-2/validate/base/C |
| stress/C | fold-2/validate/base/market-exposure |
| stress/half-risk-B | fold-2/validate/base/half-risk-B |

总预算96；当前18已用、10后片资源sealed、68未激活资源。新批映射其中10后，尚未消耗任何调用；若完成则28已用、68剩余=10 sealed+58未分配。每调用仍有180秒内部超时，首工程/MODEL_INVALID/中断/完整性失败即停余批；合法负结果继续固定顺序，无赢家追逐。reservation写明替换资源、manifest、修正协议、审批/代码SHA；保持原同一writer锁、calls.jsonl链和global checkpoint。无新预算目录或恢复额度。

## 原入口复用与失败保护

新薄入口为 `scripts/run_portfolio_corrected.py`，准备路径固定`issue131-corrected-prepared`，输出固定`corrected-exploration-jobs/01..10`，审批固定`corrected-exploration-activation.json`，均在原Git外budget根。原native函数只将data/assembly路径改为读取经审核manifest绑定的prepared_root；原匹配/回调/资金费路径不变。原终态审计支持显式新prepared/activation路径，继续复用于成功与异常；并核对原冻结清单中的140份旧执行证据SHA，禁止覆盖。

旧入口的activation/key白名单不扩展；新入口明确排除旧已用键、后片键和原资源键。新plan/完整manifest等值验证当前全代码包、固定环境和原模型字段；run时再次执行原source/QC及protected-view检查。调用锁前后重复anchor与manifest校验，冻结当前代码commit和全部输入/控制SHA之后才允许durable reservation。准备阶段不创建真实activation；CLI无绕过参数。

## 预先规定比较方式及收束

仅将新真实产物与同mode/cost旧真实产物比较：目标数量、实际order/cycle、费用与资金费、精确净值/回撤及gate、完整性/退出行为。禁止用手工匹配或价格重算制造“修复后收益”。旧值不替换，不将两批、不同mode或base/stress当独立重复试验。

新实际episode/trace/orders/cycles齐全后，才可按#127冻结自然簇定义及SHA只读重算，逐路径报告正式计数/NULL、支持归属及可证明上界；不能把旧新计数相加，不能把时间不重叠区间直接称独立。本片已暴露，仍属探索复核，不能成为新独立确认或真实经济资格。完成后应收束机制与执行可行性；少样本不触发循环调参/重跑，后续窗口始终另需裁定。

## 非原生验证与交付

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --with pytest python -m pytest -q -p no:cacheprovider tests/test_portfolio_corrected.py tests/test_portfolio_observed_budget.py tests/test_portfolio_observed_terminal.py
```

32 passed（8新集成/预算/准备测试+4原budget+20原terminal）。用真实observed控制函数和纯合成bar/episode确认实际60精度调用已合并修复，保留合法0.001BTC且不超过desired；原native padding门仍拒绝不够stake的一手，未凑大数量。临时18+10账本验证兼容历史、累计28、拒绝旧/后片/重复键、失败停批、审批漂移、prefix截断和锁竞争。未重复上轮69tests，未增加synthetic native调用。

真实准备命令使用原固定Python：`/Users/shenjianpeng/.codex/runs/freqtrade-lab/issue-43-profile-driven-v1/venv/bin/python scripts/run_portfolio_corrected.py --prepare`。新plan/manifests/SHA和实际准备结果另见`issue131-preparation-receipt.json`。固定包交监督审阅，不自行合并、关闭或执行native。
