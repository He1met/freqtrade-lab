# Issue90 消费者窄修复交付

PR https://github.com/He1met/freqtrade-lab/pull/91
远端head `0e4d8e9d33b806239bb13d618b4db2881a892ac3`，OPEN/MERGEABLE。
工作树干净，Issue90保持OPEN，未merge、未Search。

仅3个lab文件和2个测试文件，139 insertions/19 deletions。spot1d每阶段资源界限1830日、预热512/总2342根；其他模式366、legacy60D/30H保持。原S610/D547/H699、策略、成本和四类资格门无变化。来源两个producer/native/schema均未修改。

227个受影响测试通过、0 skip、6.30秒，无native调用。含15个参数化边界测试、547D实际freeze/snapshot/物化、H实际授权路径超1830/512受控拒绝且无文件/DB副作用。初次两处测试fixture错误（未将spot_profile周期改1d、授权返回tuple断言）已修正；未改生产逻辑救测试。未重复全量或新增native批次。

真实来源消费者QC成功，`consumer-qc-success.json`：700根Search日线=610评分+90预热，Search provenance `b0dfb4ef4f88ef03e6f9999d330c6a29c179a276e9f1df2055ad803707d40e15`。原source八文件的前后SHA字典完全相等，见`source-identity-before-consumer-fix.json`/`source-identity-after-consumer-fix.json`。原exit2收据`source-consumer-status.json`保留，不覆写成成功。

当前实际Console http://127.0.0.1:64697/console
启动进程exec session39641，超时1800秒配置用于未来获准的单次Search，当前只运行只读Console。
GET `/api/search/context`完整原响应保存在`console-search-ready.json`：SEARCH_READY，候选`d41d96ff-81df-4fdf-8d97-404a42d00f01`，Profile`531e0fe0-2d97-443d-ad98-b3db5ce0bcb0`，attempts空，consumed_total0，active_attempt_limit1/remaining1，SINGLE_BASELINE最大1轮1次。底层通用maximum_attempts6仍显示，但本轮有效上限为1，不是六次授权。

`search-plan-preview.json`用当前_plan validator+verify_data验证过，只存在于Search根外。Search根仍只有acquisition；没有提前prepare_round_one、POST、trial或campaign。原planned UUID只是预览预约，未来实际POST由既有API分配actual UUID，届时用追加receipt记录映射，不改旧intent或接口。

尚待监督验收并放行唯一S。未来POST `/api/search-campaigns`会同时冻结实际计划并启动native，当前未调用。D/H保持封存，没有ResearchRun、Execution或Release；未观察经济结果。当前代码修复不改变已冻结source producer身份。

针对测试命令沿用固定native Python+临时pytest包路径，设置PYTHONDONTWRITEBYTECODE=1，PYTHONPATH依次为固定native源码、当前项目、pytest site；pytest参数：`-q -p no:cacheprovider --disable-warnings tests/test_profile_multiyear_windows.py tests/test_development_run.py tests/test_search_data_producer.py tests/test_profile_holdout.py tests/test_holdout_run.py`。不运行tests/native_profile_holdout.py。
