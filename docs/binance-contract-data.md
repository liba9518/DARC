# 币安股票合约行情信号源

本页说明 `scripts/fetch_binance_contract_data.py` 与 `scripts/push_binance_long_signals.py`。这条链路只读取 Binance 股票合约 / TradFi equity perpetual 公开行情数据，不需要 API Key，不会下单，也不会扫描 BTC、ETH、SOL 等加密货币合约。

## 当前飞书机器人模式

飞书机器人现在只抓取并推送 Binance 股票合约多空信号：

- 云端 workflow：`.github/workflows/feishu-strategy-push.yml`
- 本地任务入口：`scripts/run_stock_task.ps1 -Mode binance-contract`
- 兜底守护入口：`scripts/push_strategy_watchdog.py`

旧的美股 / 韩股普通股票盘前卡、收盘复盘卡、盘中监控不再由这个飞书机器人触发。

## 快速运行

```bash
python scripts/fetch_binance_contract_data.py
python scripts/fetch_binance_contract_data.py --symbols MU,SAND --interval 5m --limit 288
python scripts/fetch_binance_contract_data.py --symbols MUUSDT,SNDKUSDT --format json
python scripts/push_binance_long_signals.py --side both --symbols MU,SAND
python scripts/push_binance_long_signals.py --side both --dry-run
```

默认市场是 USDT-M TradFi/equity perpetual，默认候选池：

```env
BINANCE_CONTRACT_MARKET=usdm
BINANCE_CONTRACT_SYMBOLS=TSLAUSDT,AAPLUSDT,NVDAUSDT,MSFTUSDT,AMZNUSDT,METAUSDT,GOOGLUSDT,AVGOUSDT,TSMUSDT,AMDUSDT,MUUSDT,SNDKUSDT,MSTRUSDT,COINUSDT,PLTRUSDT,CRCLUSDT,HOODUSDT,BABAUSDT
BINANCE_CONTRACT_STOCK_ONLY=true
BINANCE_CONTRACT_INTERVAL=1h
BINANCE_CONTRACT_KLINE_LIMIT=24
BINANCE_CONTRACT_TIMEOUT_SEC=10
BINANCE_CONTRACT_SIGNAL_SIDE=both
BINANCE_SIGNAL_MIN_SCORE=2
BINANCE_LONG_SIGNAL_MIN_SCORE=0
BINANCE_PUSH_EMPTY_LONG_STATUS=false
BINANCE_STOCK_CONTRACT_ALLOWLIST=TSLAUSDT,AAPLUSDT,NVDAUSDT,MSFTUSDT,AMZNUSDT,METAUSDT,GOOGLUSDT,AVGOUSDT,TSMUSDT,AMDUSDT,MUUSDT,SNDKUSDT,MSTRUSDT,COINUSDT,PLTRUSDT,CRCLUSDT,HOODUSDT,BABAUSDT
BINANCE_STOCK_CONTRACT_ALIASES=MU=MUUSDT,SAND=SNDKUSDT,SNDK=SNDKUSDT
BINANCE_FUTURES_BASE_URL=https://fapi.binance.com
```

脚本会用 Binance USDⓈ-M Futures `exchangeInfo` 校验符号，只保留 `underlyingType=EQUITY` 且 `contractType=TRADIFI_PERPETUAL` 的交易对。即使误填 `BTCUSDT`、`ETHUSDT`，默认也会跳过，不会推送。

裸股票 ticker 会自动转换为 Binance 股票合约符号，例如 `MU` 会转换为 `MUUSDT`。注意 `SANDUSDT` 在 Binance 是加密货币合约；如果你说的是类似 SanDisk 的股票合约，脚本默认把 `SAND` 映射为 `SNDKUSDT`。

## 多空推送规则

`scripts/push_binance_long_signals.py` 默认 `--side both`：股票合约出现 `long_watch` 或 `short_watch` 任一方向信号才推送飞书；没有多空信号时默认不发送空状态卡。

- 只看做多：`python scripts/push_binance_long_signals.py --side long`
- 只看做空：`python scripts/push_binance_long_signals.py --side short`
- 多空都看：`python scripts/push_binance_long_signals.py --side both`
- 临时发送空状态卡：追加 `--push-empty`

飞书卡片会把信号分成“开多精选”和“开空精选”两块，每个方向最多展示 3 支合约。若同一方向触发超过 3 支，会优先展示信号强度更明确、24h 成交额更高的合约；模拟开单也只跟随卡片里的精选合约，避免后台记录了用户看不到的信号。

卡片里的“信号强度”按通俗口径解释：

- ≥ +8：强多，做多条件高度集中。
- +2 到 +8 以下：偏多，做多条件占优。
- -2 到 +2：观望，方向不明显。
- -8 以上到 -2：偏空，做空条件占优。
- ≤ -8：强空，做空条件高度集中。
- 信号强度只用于排序优先级，不等于胜率，也不是自动下单命令。

做多逻辑主要看短周期价格动量转强、主动买入占比偏高、标记价/指数价没有明显失真、资金费率风险可控；做空逻辑主要看短周期动量转弱、主动买入不足或卖压占优、反弹承压、资金费率风险可控。

卡片展示的胜率来自本地模拟开单账本：有已平仓样本时显示胜负笔数、模拟胜率、累计盈亏和当前持仓；样本不足时会明确提示“暂无已平仓样本”。该胜率只是当前规则的模拟记录，不代表未来收益保证。

## GitHub Actions 自托管 runner

Binance Futures 可能对 GitHub-hosted runner 所在机房返回 HTTP 451，导致云端 workflow 成功执行但抓不到任何合约行情。当前 `.github/workflows/feishu-strategy-push.yml` 已固定运行在带有 `binance-futures` 标签的 Windows x64 self-hosted runner 上。

该 workflow 只安装 Binance 信号推送所需的最小依赖 `requests` 和 `python-dotenv`，避免在 Windows runner 上安装全量 `requirements.txt` 时被旧股票分析链路的无关依赖拖挂。

如果本地 Windows 电脑已经可以访问 `https://fapi.binance.com/fapi/v1/time`、`MUUSDT` 和 `SNDKUSDT` ticker，可以直接把这台 Windows 电脑注册为仓库级 runner：

1. 进入 GitHub 仓库 `Settings` -> `Actions` -> `Runners` -> `New self-hosted runner`。
2. 选择 Windows x64，按页面给出的 PowerShell 命令下载并配置 runner。
3. 配置 runner 时添加标签：`binance-futures`。最终 workflow 匹配条件是 `[self-hosted, windows, x64, binance-futures]`。
4. workflow 使用 Windows 系统自带的 `powershell` 执行命令，不要求额外安装 PowerShell 7 / `pwsh`。
5. 在 Windows PowerShell 里先确认 Binance Futures 可访问：

   ```powershell
   Invoke-RestMethod "https://fapi.binance.com/fapi/v1/time"
   Invoke-RestMethod "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=MUUSDT"
   Invoke-RestMethod "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=SNDKUSDT"
   ```

6. 将 runner 安装成 Windows 服务并启动，确保电脑重启后仍会接单：

   ```powershell
   .\svc.cmd install
   .\svc.cmd start
   .\svc.cmd status
   ```

如果这台 Windows 电脑关机、休眠、断网，或者 runner 服务没有运行，workflow 会在 GitHub Actions 等待可用 runner。若未来改用 VPS，可把 workflow 的 runner 标签改回对应平台，例如 `[self-hosted, linux, x64, binance-futures]`。

## 当前抓取字段

- `exchangeInfo`：用于确认只扫描 `EQUITY` / `TRADIFI_PERPETUAL`。
- 24h ticker：最新价、24h 涨跌幅、24h 高低价、成交额、成交笔数。
- Premium index：标记价、指数价、最近资金费率、下一次资金费时间。
- Kline：指定周期动量、区间振幅、主动买入成交额占比。
- 合约信号：`long_watch` / `short_watch` / `neutral`，用于先把候选池按动量和主动买卖结构粗排，不代表自动下单。

## 数据源边界

Binance USDⓈ-M Futures 的 Kline 接口是 `/fapi/v1/klines`，24h ticker 是 `/fapi/v1/ticker/24hr`，标记价格 / 资金费率来自 `/fapi/v1/premiumIndex`。产品范围由 `/fapi/v1/exchangeInfo` 的 `EQUITY` / `TRADIFI_PERPETUAL` 字段约束。

Binance Academy 对这类产品的说明是：stock perpetual contracts / TradFi Perps 追踪传统金融资产，使用 USDT 结算，并提供杠杆交易。当前脚本只做行情信号，不做自动下单。
