# 值前消费者时间上限修复方案（未实施）

只读确认三处入口不一致：Search plan与_profile_window_contract均限制366天；Development的_development_window也限制366天，并在freeze、snapshot、物化三次调用。协议S610/D547无法通过。Profile H按holdout_days计算，没有366上限，699天本身不受这类阻塞；legacy H30天独立限制保留。

建议仅修改lab/bounded_research.py、lab/development_run.py、lab/holdout_run.py：共用一个小内部资源上限helper，仅已验证spot+1d Profile允许每phase最多1830天（明确5×366日上限），含既有最多512根预热共最多2342根日线。其他模式仍366日；旧固定60D/30H分支不改。D三处传已验证Profile上下文；H在源授权写入/取值前检查同一资源上限。不把610编码为特例，不改窗口、策略、成本、资格门、表或native。

来源无需重采或SHA豁免。scripts/fetch_okx_profile_data.py:implementation_snapshot只打包producer自身和historical transport，不含bounded_research.py。_load_search_source核原副本字节/原provenance hash并固定historical SHA；后续wrapper核数据/控制身份，无当前consumer==历史producer的比较。只改lab后可保留source原件及两个trusted SHA，另记新consumer commit。

针对验证：spot1d边界366/367/1830接受、1831拒绝；旧5m和futures1d超过366拒绝；547D全部调用贯通；H699接受、超限在源授权前拒绝；预热512/513与行数界限；受影响旧测试及现真实source消费者QC（零native，原source SHA不变）。当前为方案，代码未改。
