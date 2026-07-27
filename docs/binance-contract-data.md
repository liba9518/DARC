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
python scripts/fetch_binance_contract_data.py --symbols EWYUSDT,KORUUSDT --format json
python scripts/push_binance_long_signals.py --side both --symbols MU,SAND
python scripts/push_binance_long_signals.py --side both --dry-run
```

默认市场是 USDT-M TradFi/equity perpetual，默认候选池：

```env
BINANCE_CONTRACT_MARKET=usdm
BINANCE_CONTRACT_SYMBOLS=TSLAUSDT,AAPLUSDT,NVDAUSDT,MSFTUSDT,AMZNUSDT,METAUSDT,GOOGLUSDT,AVGOUSDT,TSMUSDT,AMDUSDT,MUUSDT,SNDKUSDT,MSTRUSDT,COINUSDT,PLTRUSDT,CRCLUSDT,HOODUSDT,BABAUSDT,SPYUSDT,QQQUSDT,EWYUSDT,KORUUSDT,EWJUSDT
BINANCE_CONTRACT_STOCK_ONLY=true
BINANCE_CONTRACT_INTERVAL=15m
BINANCE_CONTRACT_KLINE_LIMIT=96
BINANCE_CONTRACT_TIMEOUT_SEC=10
BINANCE_CONTRACT_SIGNAL_SIDE=both
BINANCE_SIGNAL_MIN_SCORE=0
BINANCE_LONG_SIGNAL_MIN_SCORE=0
BINANCE_PUSH_EMPTY_LONG_STATUS=false
BINANCE_STOCK_CONTRACT_ALLOWLIST=TSLAUSDT,AAPLUSDT,NVDAUSDT,MSFTUSDT,AMZNUSDT,METAUSDT,GOOGLUSDT,AVGOUSDT,TSMUSDT,AMDUSDT,MUUSDT,SNDKUSDT,MSTRUSDT,COINUSDT,PLTRUSDT,CRCLUSDT,HOODUSDT,BABAUSDT,SPYUSDT,QQQUSDT,EWYUSDT,KORUUSDT,EWJUSDT
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

## 当前抓取字段

- `exchangeInfo`：用于确认只扫描 `EQUITY` / `TRADIFI_PERPETUAL`。
- 24h ticker：最新价、24h 涨跌幅、24h 高低价、成交额、成交笔数。
- Premium index：标记价、指数价、最近资金费率、下一次资金费时间。
- Kline：指定周期动量、区间振幅、主动买入成交额占比。
- 合约信号：`long_watch` / `short_watch` / `neutral`，用于先把候选池按动量和主动买卖结构粗排，不代表自动下单。

## 数据源边界

Binance USDⓈ-M Futures 的 Kline 接口是 `/fapi/v1/klines`，24h ticker 是 `/fapi/v1/ticker/24hr`，标记价格 / 资金费率来自 `/fapi/v1/premiumIndex`。产品范围由 `/fapi/v1/exchangeInfo` 的 `EQUITY` / `TRADIFI_PERPETUAL` 字段约束。

Binance Academy 对这类产品的说明是：stock perpetual contracts / TradFi Perps 追踪传统金融资产，使用 USDT 结算，并提供杠杆交易。当前脚本只做行情信号，不做自动下单。
