# 美股/韩股信号源推荐与抓取

本页说明独立的美股/韩股信号推荐入口。飞书策略自动化现已以美股和韩股为默认市场；该脚本可手动调用同一类候选池抓取与条件触发逻辑。

## 快速运行

```bash
python scripts/recommend_us_kr_signals.py --market both
python scripts/recommend_us_kr_signals.py --market us --format json
python scripts/recommend_us_kr_signals.py --market kr --count 5
```

默认不再固定每次推荐 3 只或 5 只，而是只输出满足触发条件的 `eligible` 标的；`--count` 仅作为最多触发数量上限，不传或配置为 `0` 表示不封顶。

美股默认采用质量优先筛选：趋势结构、20 日相对强度、资金承接、波动与回撤、流动性和信号一致性必须同时达标；单日急涨、月度涨幅过热或证据不足的标的不会为了凑数进入推送。弱市中会自动提高资金承接、评分和一致性门槛，因此允许当日零推送。

## 默认候选池

- 美股：默认复用合约友好池，优先覆盖高流动性科技、AI、加密/杠杆代理与 ETF。
- 韩股：默认覆盖 Samsung Electronics、SK hynix、LG Energy Solution、Hyundai Motor、NAVER、LG Chem、Samsung SDI、Kakao、Ecopro BM、Celltrion Healthcare。

可用环境变量覆盖：

```env
US_SIGNAL_POOL=NVDA,TSLA,AAPL,MSFT,AMZN,GOOGL,META,COIN,MSTR,SPY,QQQ,AMD,AVGO
KR_SIGNAL_POOL=005930.KS,000660.KS,373220.KS,005380.KS,035420.KS,051910.KS,006400.KS,035720.KQ,247540.KQ,091990.KQ
US_SIGNAL_MAX_COUNT=0
KR_SIGNAL_MAX_COUNT=0
US_SIGNAL_PICK_COUNT=0
KR_SIGNAL_PICK_COUNT=0
US_MIN_DOLLAR_VOLUME=10000000
KR_MIN_DAILY_TURNOVER_KRW=5000000000
YFINANCE_CACHE_DIR=data/cache/yfinance
```

`YFINANCE_CACHE_DIR` 默认会落到仓库内 `data/cache/yfinance`，用于避免 yfinance 在受限用户目录里创建 sqlite 缓存失败。

韩股使用 Yahoo Finance 后缀代码：

- KOSPI：`005930.KS`
- KOSDAQ：`035720.KQ`

如果传入 6 位裸韩股代码，推荐脚本底层会默认按 `.KS` 处理；KOSDAQ 标的应显式使用 `.KQ`。

## 推荐信号源优先级

1. **Yahoo Finance / yfinance**：当前默认抓取源。优点是无新增凭证、已在仓库内使用，并且 [Yahoo Finance 官方帮助](https://help.yahoo.com/kb/account/exchanges-data-providers-yahoo-finance-sln2310.html)列出韩国交易所后缀 `.KS` 与 KOSDAQ 后缀 `.KQ`；缺点是韩国行情通常延迟约 20 分钟。
2. **Longbridge OpenAPI**：适合作为美股增强源，覆盖美股股票/ETF、期权和盘前盘后/夜盘能力；[Longbridge Quote 文档](https://open.longbridge.com/docs/quote/overview)说明 US LV1 与 extended-hours 能力，仓库已存在 `LongbridgeFetcher`，但不覆盖韩股。
3. **Finnhub**：适合美股 quote、symbol lookup 和高级 candle 数据；[Finnhub API 文档](https://api2.finnhub.io/docs/api/crypto-candles)包含 symbol lookup、stock symbol、quote、stock candle 等入口，仓库已存在 `FinnhubFetcher`，国际实时行情通常需要企业权限。
4. **Alpha Vantage**：适合作为全球股票日线或兜底搜索源；[Alpha Vantage 文档](https://www.alphavantage.co/documentation/)列出 daily/daily adjusted、global quote、ticker search 等能力，仓库已存在 `AlphaVantageFetcher`，但免费额度较低，实时/高级能力受限。
5. **KRX Open API / Data Marketplace**：适合未来做官方韩股 EOD/参考数据增强；接入前需要确认 API Key、授权和字段契约。

## 当前边界

- 该脚本只做候选推荐，不推送飞书、不改状态文件。
- 韩股首版只承诺日线级候选筛选，不承诺实时盘口、资金流、行业宽度或官方复权字段。
- 韩股已接入飞书盘前策略和收盘复盘；当前仍以日线级条件触发为主，不做韩股盘中实时监控。
