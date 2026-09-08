# Issue153 冻结供给开发诊断v1

授权153#issuecomment-5584945369。固定经济问题及原卡参数，只有Ethereum链USDC存量变化与随后ETH月收益关联；不因返回数据调参。原卡为历史，本协议是执行定义。

唯一GET：`https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=usdc_eth&metrics=SplyCur&frequency=1d&start_time=2021-01-01&end_time=2022-10-31&page_size=10000`。20秒/1MiB/0retry、免账户、不redirect/分页、不另取crypto。HTTP200、JSON data非空，asset严格usdc_eth，metric严格SplyCur；root仅data和可空next_page_token/next_page_url；非空分页立即阻塞。每行只asset/time/SplyCur；未知字段不静默换语义。数值与decimal字符串都支持，bool/NULL/nonfinite/≤0为该日期无效。

日期time必须严格UTC零点，允许Z或+00:00及1–9位全零小数秒，归一YYYY-MM-DD后唯一；非UTC/非零点/格式冲突或域外日期阻塞，不推断移位。预期独立日历为2021-01-01至2022-10-31全部669个日历日，不套营业日。缺日/重复/不合法数值使该所属月供给端点NULL；全月都要完整，不能仅月末有值就通过。连续合法相同数值允许。供应商边界少日则缺月UNKNOWN，不补第二次请求。

日标签按当日账本存量作开发解释，RECONSTRUCTED_EX_POST；单位为USDC原生代币单位，不USD价格乘数。实际首次发布/历史版本/精确day-end计算点及修订例外UNKNOWN，月8日缓冲不证明PIT。单链迁移/发行库存/避险/替代均可能驱动供给，非净新钱/因果。

21个单元2021-03至2022-11，月8日00UTC决定01UTC入场、次月8日01退出。前一完整月月末SplyCur/再前一月月末SplyCur−1，>0 EXPAND，否则OTHER；任何输入月NULL则信号UNKNOWN。每事件同样1quote ETHUSDT往返，原base fee.001/slip.0006，stress.002/.0012，净值倍率(Pout/Pin)*(1-s)/(1+s)*(1-f)^2。无再投资/钱包/DD。

仅原39源manifest里ETHUSDT 1h具名源，价格解码限2021-03-08 00至2022-12-08 01UTC含端点；source SHA前后核对、旧inventory异常全域比对；持有每小时必须存在完整，缺/短整事件UNKNOWN，退出只需存在正开价。不读BTC，不动封存或forward。

所有21月含UNKNOWN公开，毛净/输入/分组/原因完整；组n、净均值/中位/正数、最大绝对及正贡献，组差EXPAND−OTHER。任一组有效<5优先UNDERPOWERED；否则任一成本差≤0 STOP_RULE_NOT_SUPPORTED；方向成立但EXPAND任一净均值≤0 NO_LONG_COST_SUPPORT；否则仅EXPOSED_DEVELOPMENT_ASSOCIATION。>=5无功效保证，不改阈值/币/链/日期/方向凑组。

固定Git外root issue153-usdc-supply-v1的acquisition与analysis分别mkdir独占，失败不换名。manifest绑定全部代码/协议/源清单/异常及保护文件，push+评论先于acquire。采集attempt/响应/HTTP/SHA/时间/校验终态保留；通过后推送响应+check+terminal绑定再execute。analysis一次worker180秒21units0retry，禁止网络/native/global/新钱包。

事前仅允许最多一次纯schema离线修复（不得改变日时序/身份/经济含义），需已下载原文证明同义，保留失败与v1代码/绑定，另冻结新版本/收据一次再校验、0GET；未明确或再次失败停止。本版本未预做fallback。原CMmetadata2/EFFRmacro1/crypto112/native32不变；本切片新增供给GET最多1独立记账。

必要7测试通过；CLI check只控制文件。测试/工程通过不代表市场结论。
