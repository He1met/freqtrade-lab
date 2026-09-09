# BTC absolute baseline 定位与接入审计

**结论：已找到准确 baseline；NO_GO_UNCHANGED_NATIVE_REPRODUCTION。** 不是缺一份通用设计，而是三个独立的真实差异：全现金复利/固定 stake、无止损/强制止损、旧双资产 JSON/现探索来源合同。现阶段不能交付诚实的“一次合成＋一次原样 native 市场调用”许可包。没有更换资产或追加经济规则。

**可复核的定位链（均在 ` /Users/shenjianpeng/Documents/freqtrade-lab-local/search-research-supervision-20260902 ` 下）。**

| 文件 | 已核 SHA-256 与作用 |
|---|---|
| `global-research-ledger.jsonl` 第 64 条 | `b29b11a8e01f43c00b742c994fde5df2d77a54df8f02f99ba8b96e3a03b20d73`；cohort `dual-momentum-btc-eth-2024-v1`，`root_replay_allowed=false` |
| `dual-momentum-search-2024-v1-correction/correction-receipt.json` | `06a5d287ea95ace7d61fbd1adf1a8e744e6248b5a825186e8376930e37ce23f9`，与第 64 条完全相同；defect 明指 `run_stage.py:199`，回撤分母错，ranking/finalist/status 无效 |
| `dual-momentum-search-2024-v1/cohort-preregistration.json` | `7d4d9fd110683b8ccca48fd7c9069ad4424d64c0bd6297b1578d90e0d4b562e7`，明确链接下列 runner/master/source SHA |
| `dual-momentum-search-2024-v1/run_stage.py` | `aa50532438dc3e2b9f3fb9678c9fb37b04e2c93004d76055b7115b4deda336e6`；唯一准确源码，baseline 分支为 `signal_at('btc-absolute-momentum-a',...)`，并非现成 IStrategy 文件 |
| `dual-momentum-search-2024-v1/master-contract.json` | `1e46aaa5f86d919fbcfc38fee8b9c14cf09e9d247ab6ad3b0ff4a010d0d1fc36`；冻结规则与执行语义 |
| `dual-momentum-search-2024-v1/stage-contract.json` | `968947a146e31f955c7c9123f9b79f1f13f849640b585f5fb571281ba8f75576`；2024-01-01 至 2025-01-01，原协议两候选而非单资产专用入口 |
| `dual-momentum-search-2024-v1/source/retrieval-receipt.json` | `7c3a3316e3daf07803d23b6733a4e795c84b320335f5ec73f1f633f900522f49`；与冻结引用相同 |

原 terminal/trials 的 SHA 仅由 correction 引用确认，未打开其交易或结果原文；没有执行旧 runner。它本身还要求原双候选/双资产文件并拒绝 consumed root，不能直接调用来“只跑 A”。

**精确规则及迁移差异。**

- 信号：BTC 的 `close[s]/close[s-28]-1 > 0` 则 BTC，否则现金。每隔 7 个日索引决策；s+1 整日 embargo，s+2 open 执行，同资产连续周不换仓。旧代码还无条件计算 ETH return；BTC 选择不依赖它，移除这项计算属于单资产提取，不能直接声称源码字节不变。
- 周钟是阶段行索引锚定，不是默认“周一开仓”：2024 阶段首 signal 为 01-29、整日跳过 01-30、首执行 01-31 周三；末平仓索引 359 为 12-25 open。由 366 天和代码 `range(28, len-9, 7)` 算得 47 决策槽，非市场信号计算。原生须额外正向 shift 保留 embargo，须用合成证明首次/末次/同资产不重开；不能默认 next-bar 就等价，也不能原生末 K 强平代替旧 12-25 open 清算。
- 仓位：初始 1000 USDT，每次用**全部当时现金**买入，盈利复投、亏损降仓，卖出后再持全部现金。当前 `profile_search_config` 使用固定数值 `stake_amount`、`tradable_balance_ratio=0.99`；Profile 不接受 `unlimited`。没有允许动态 stake 的策略回调。改成 250 或 990 固定 stake 会改变路径与 DD，不能叫只修分母。
- 退出：旧规则无 ROI/盘中止损，现金信号或最后 open 清算。当前 AST 接受空 `minimal_roi={}`，所以 ROI 可禁用；但严格要求 `-1 < stoploss < 0`，不能真正无止损。用 -0.999 仍是新尾部退出机制，不可声称等价；无需读取行情就能确认这项差异。
- 成本：旧每边 `fee=.001 + slippage=.0002`，买入 quantity=`cash/[open*(1+.0012)]`、卖出 proceeds=`quantity*open*(1-.0012)`；MTM 也扣假想退出成本。当前 Profile 只有 fee，不能未经证明将 .0012 native fee 当完全等价的资金和舍入模型。旧 DD 是 daily close MTM；native summary DD 不能直接冒充相同每日权益定义。这些差异需要合成证据，未执行。

**训练源真实状态。** `exploratory-training-sandbox-v1/protocol.json` 的 schema 是 `EXPLORATORY_TRAINING_SANDBOX_V1`，SHA `d050d0383b3d54489b63587ff31bf80998cd6bc14f4a3bbc54ccb1fd7c77523c`，训练窗 2020-01-01 至 2025-01-01。其五条 source receipt 全部与各年实际 receipt 字节 SHA 一致：

| 年份；位于 `exploratory-training-sandbox-v1/sources/<年>/retrieval-receipt.json` | receipt SHA |
|---|---|
| 2020 | `3812084be10b3fb100cf52da85fb8b850a24c14c95c42aee911f0ac6a47592ea` |
| 2021 | `16ec67637d8f96041f3ff6b652abc8ea23c98331b91a4a29c22333d898662768` |
| 2022 | `3f809ccbcafa02dda987a747574317e4162a4ecc5e63aba0dffe093368905441` |
| 2023 | `5045ccf23ff7f3a0d4c5d08e881d9ebf5fd884935002ce8bb97d36d043b2d769` |
| 2024 | `7c3a3316e3daf07803d23b6733a4e795c84b320335f5ec73f1f633f900522f49` |

这五份 receipt 均为 `okx-public-dual-spot-daily-source-v1`、host `www.okx.com`、`authentication=none`、`timeframe=1Dutc`，各自然年窗口。keys 中没有当前 `profile_acquisition/exploration` 合同，文件为 BTC/ETH JSON 和 instruments.json。2021/2023 的旧标签分别仍是 development-2021/development-2023；后来已经进入明确已见 sandbox 训练，不据旧文件名再次把它们说成未见 D。这里没有读取原价格文件，因而确认的是 receipt 和引用关系，**没有重新验证行情字节、连续性或数值质量**。

现 `prepare-search-data` 要求 `retained-data-provenance.json`、当前 Profile/source 控制文件、原生 Feather 与探索绑定；共享逻辑更要求父源已有 exploratory contract。旧 sandbox 的“探索”语义成立，但不等于当前格式接入就绪。不能补同名 exploration 键洗成受信任旧原件。

**最小衍生来源处理（需 root 决定是否值得，当前不实施）。** 只考虑 2024 一个已见年、BTC 单资产，从上述确切原件生成全新 Git 外衍生根；保留原 protocol/receipt/BTC 文件 SHA（原 receipt 声明 BTC SHA `bf233bbe04bcf57fef4ef5471ff23febb899daacc9b52983dd66effad15bc7b7`），显式 `DERIVED_FROM_OBSERVED_TRAINING / NOT_INDEPENDENTLY_VALIDATED`、新转换代码版本/UTC规则/父子 SHA。获准后只读 BTC 和必要 instruments 身份，禁止读取 ETH 值/2025；机械转换 JSON→1d Feather、检查原确认位及 UTC 完整性，不拼未知2019预热、不下载、不伪造 HTTP capture。2024-01-01 起自带 28+ 日训练内预热，按旧 01-31 首执行和 12-25 末平仓语义核对。当前项目没有已验证的此旧 schema 转换入口；新 provenance 需要受信任的衍生合同接线及失败验证，不是手写一份就能过现消费者。**只解决来源也不能解决仓位和止损差异。**

**准确调用草案及许可结论。**

现有实际入口为：

```text
python scripts/run_bounded_research_pilot.py prepare-search-data
  --source-root <新衍生原生源根>
  --source-provenance-sha256 <新合同实际SHA>
  --source-receipt-sha256 <新衍生receipt实际SHA>
  --database <另行获准的新研究DB>
  --profile-id <另行冻结的单资产Profile>
  --search-timerange <冻结且保留上述时序的训练计分窗>
  --pre-roll-candles <实际静态lookback>
  --exploration-contract <新暴露审计合同文件>
  --output-root <新Search源根>
```

这是**已核 argparse 的接口草案，不是可执行许可包**：括号项尚无真实产物，不提供假 SHA/不存在的 DB；现旧 root 不能填入 source-root。Exploratory 不传 Development，不加 SINGLE_BASELINE。由于原样表示失败，本次建议市场调用预算保持 **0**，不启动 Console/Generation/native。

如果 root 只希望确认分母数学、完全不接市场/旧源，可单独授权下列一次纯合成诊断（本次未执行；不导入项目、不写文件、无 native）：

```sh
python3 - <<'PY'
from decimal import Decimal as D
for seq, expected in [(['1000','1200','900'], D('0.25')),
                      (['1000','1200','1000','2000','1750'], D(1)/D(6))]:
    eq = list(map(D, seq)); peak = eq[0]; worst = D(0)
    for x in eq:
        peak = max(peak, x); worst = max(worst, (peak-x)/peak)
    assert abs(worst-expected) < D('1e-25')
print('SYNTHETIC_DD_ONLY_PASS; market/native/database calls=0')
PY
```

第二组会揭示“先找最大绝对跌幅再除初始资金”的另一问题：最大金额跌幅不一定对应最大比例回撤。该诊断不是新 runner，也不证明旧市场结果或 native 可用，单独执行价值有限。

**root 的真正决策只剩一个：是否值得改变这条 baseline 的执行语义或扩展接入。** 若要求保持原冻结行为，就需 source 转换、动态全现金/无止损支持和时序/成本等价验证，已超出“只修 DD”的小工作。若接受固定仓位与有限止损，则必须明确标为新的执行约束变体，另冻结，不能覆盖旧 invalid；当前没有经济依据证明这个变体优于旧规则。不建议为了本次测量纠偏直接开展上述工程。准确阻塞已交，停止于此，不再泛化设计或搜索其它 baseline。

审计边界：只读目录文件名用于定位、receipt 先 keys 后白名单、源码与冻结规则；未读 price/funding/trade arrays、2025 outer/其它保护窗、DB；无新行情请求、信号、合成/native/工程修改。仅 apply_patch 写 Git 外报告，台账未变。
