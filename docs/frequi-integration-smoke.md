# FreqUI 本机集成 Smoke Receipt

日期：2026-08-30
状态：`PASS_WITH_LIMITS`

固定版本的 Freqtrade Webserver、真实 FreqUI `/backtest` 页面，以及冻结
回测结果的历史发现与结果加载链路，已在全新本机 loopback 隔离环境验证
通过。该结果只证明可选入口技术可用，不证明策略盈利、Judge 通过、
可交易性或资金安全。

## 固定版本

| 项目 | 已验证值 |
| --- | --- |
| Freqtrade | `2026.7` |
| 参考 tag / commit | `2026.7` / `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5` |
| Smoke Python / CCXT | `3.12.13` / `4.5.76` |
| FreqUI | `3.1.1` |

实际 Python package 不内嵌 Git commit；上面的 commit 是固定版本源码
Gate 参考，不能当作 package runtime 的独立 commit 证明。另一个同版本
Freqtrade 环境因未安装 FreqUI 而返回 `not_installed`，不能作为本入口
runtime。

## 隔离边界

Smoke 使用全新的临时 `HOME`、`TMPDIR`、`user_data` 和 sanitized config：

- `dry_run=true`，exchange key、secret、password 均为空；
- 未读取现有 config、交易数据库、账户、订单或资金；
- 未执行回测、数据下载、下单或交易；
- Webserver 只监听 `127.0.0.1:18765`；
- macOS sandbox 禁止 `network-outbound`；
- `lsof` 全程只观察到该 loopback listener，无外部连接。

脱敏命令形状：

```bash
env -i HOME=<isolated-home> TMPDIR=<isolated-tmp> \
  PATH=<freqtrade-2026.7-venv>/bin:/usr/bin:/bin \
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 TZ=UTC \
  NO_PROXY=127.0.0.1,localhost \
  sandbox-exec -f <deny-outbound-profile> \
  <freqtrade-2026.7-venv>/bin/python -m freqtrade webserver \
  --no-color -c <sanitized-config.json> --userdir <isolated-user-data>
```

认证历史 API 只使用本次进程的一次性本机测试认证；认证值未写入 receipt，
`freqtrade-lab` 也不读取或保存它。

## 冻结结果与端点证据

| 文件 | SHA-256 |
| --- | --- |
| `backtest-result-2026-08-30_06-43-22.zip` | `3cb0f8e8a943e7fdff24c10a2e8afca2e165d7d375d5e216b606316e40ec6a68` |
| `backtest-result-2026-08-30_06-43-22.meta.json` | `a08c296eacb7f4d19774eb25109695907df2e699e0a1a8b8e6767c90e4028255` |

两个普通文件位于隔离 `user_data/backtest_results`，Smoke 前后哈希一致。

| 端点 | 最小验证结果 |
| --- | --- |
| `GET /api/v1/ping` | `200`, `{"status":"pong"}` |
| `GET /ui_version` | `200`, `{"version":"3.1.1"}` |
| `GET /backtest` | `200`, 真实 FreqUI index；主 JS/CSS 均为 `200` |
| `GET /api/v1/backtest/history` | `200`, 精确发现一条冻结结果 |
| `GET /api/v1/backtest/history/result` | `200`, `status=ended`, `running=false`, `comparison rows=1` |

历史发现身份：

```text
filename = backtest-result-2026-08-30_06-43-22
strategy = StrategyTestV3Futures
run_id   = 6add9846400d05f3eb92429acaa292c38a70fae2
timeframe = 5m
```

结果 metadata 与实际 result 都只返回 `StrategyTestV3Futures`。

## 已验证限制

- 入口只能打开通用 `/backtest`，`single_result_deeplink=false`；
- 当前结果不会由 URL 自动选中，用户必须按 filename 和 strategy 手动选择；
- ZIP/meta 足以加载历史摘要与交易结果；K 线和指标还可能需要本地 strategy
  与 OHLCV 数据，不属于本 Issue；
- 第一次 `SIGINT` 会立即关闭 listener 和 HTTP 服务，但此 standalone runtime
  仍等待线程，第二次中断后才以 `130` 完全退出；Smoke 结束后无残留进程或端口。

实现契约依据 Freqtrade `2026.7` 的
[FreqUI 文档](https://docs.freqtrade.io/en/2026.7/freq-ui/)、
[Backtest history API](https://github.com/freqtrade/freqtrade/blob/2026.7/freqtrade/rpc/api_server/api_backtest.py)、
[历史文件扫描](https://github.com/freqtrade/freqtrade/blob/2026.7/freqtrade/data/btanalysis/bt_fileutils.py)
及 FreqUI `3.1.1` 的
[Backtest history store](https://github.com/freqtrade/frequi/blob/3.1.1/src/stores/ftbot.ts)。

## Issue #11 producer 组合验收

Issue #11 在同一固定 Freqtrade tag/commit 上重新真实运行 producer，并把同批
三场景 ZIP/meta 普通文件复制到全新、独立的 FreqUI results 目录。producer
manifest SHA-256 为
`03160b8a8a6be6f68b84248f787d6c968690af40c043af2fcb7bddb4136d0e45`：

| 场景 | FreqUI 可发现文件 | Trades | ZIP SHA-256 |
| --- | --- | ---: | --- |
| Development | `backtest-result-development-01.zip` | 11 | `88b517d30098bd37e3557ed96be7f130a6eacf07b109a5ef9774c1ab1398d047` |
| Holdout | `backtest-result-holdout-02.zip` | 9 | `85728258114ae0300d1448e1a84e02d5be1d8317e785798ee2959138ed89c938` |
| Holdout Stress | `backtest-result-holdout-stress-03.zip` | 9 | `451e8158eb6be6920be18b1cca26dbd662eb5e7fc8338fd794238d4ca4c65ec5` |

组合验收结果：

- schema-v1 仍恰好六表；三执行共享 ResearchRun
  `4f7a346b-5c98-4d03-bf7c-e78a4955164b`，状态为 `COMPLETED`，
  `verdict` 与三个 `scenario_passed` 均为 `NULL`；
- Lab 的 list/detail/download 与现有 FreqUI Gate 均使用这同一批产物；三场景
  `download_available=true`、`frequi_available=true`、
  `local_copy_ready=true`，`history_visibility` 继续诚实保持 `NULL`；
- Lab 下载的 Development ZIP 与冻结 Artifact SHA-256 相同；
- 固定 Freqtrade history API 精确返回上述三条，Development result 返回
  `status=ended`、`running=false`、一条 comparison；
- 浏览器中的 Lab 页面显示同一 Run `3/3` 成功及三个普通 FreqUI 入口；真实
  FreqUI **Load Results** 表显示三条新 stem，Development 可加载并在
  **Analyze result** 中读取 11 笔交易；
- producer 与 Webserver 均在隔离临时根运行；Webserver 只监听 loopback，
  临时认证未写入本 receipt 或仓库。验收结束后 Lab 与 FreqUI 监听端口均已关闭。

该 receipt 只证明 producer、Lab 与固定 FreqUI 的组合兼容性，不证明策略
盈利、Judge 通过、Release 资格、可交易性或资金安全。
