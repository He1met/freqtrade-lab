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
