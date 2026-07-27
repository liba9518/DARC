# Binance 股票合约飞书卡片交易计划

飞书机器人只推送 Binance 股票代币合约观察信号，不会自动下单。卡片里的交易计划用于帮助人工执行时控制风险。

## 信号方向

- `long_watch`：短周期动量向上、24h 不逆风、主动买入占比偏强。
- `short_watch`：短周期动量向下、24h 不逆风、主动卖出结构偏强。
- `neutral`：没有触发多空条件，不提供参考入场、止损、止盈。

## 卡片计划字段

- `参考入场`：以标记价 / 最新价为中心的参考入场区间。
- `止损`：参考止损位，按近期 K 线振幅估算风险宽度。
- `止盈1`：按 1R 计算的第一止盈位。
- `止盈2`：按 2R 计算的第二止盈位。
- `失效`：价格突破止损或主动买卖结构反转时，信号失效。
- `单笔风险≤账户 0.5%-1%`：提醒按账户风险控制仓位。
- `模拟开单`：按模拟账户权益、单笔风险、杠杆和最大保证金占用估算模拟数量、名义仓位和预估保证金。

## 模拟开单参数

```env
BINANCE_SIM_ORDER_ENABLED=true
BINANCE_SIM_ACCOUNT_EQUITY_USDT=10000
BINANCE_SIM_ORDER_RISK_PCT=1
BINANCE_SIM_LEVERAGE=3
BINANCE_SIM_MAX_MARGIN_PCT=30
```

- `BINANCE_SIM_ACCOUNT_EQUITY_USDT`：模拟账户权益。
- `BINANCE_SIM_ORDER_RISK_PCT`：单笔风险预算，占账户权益百分比。
- `BINANCE_SIM_LEVERAGE`：用于估算保证金占用的模拟杠杆。
- `BINANCE_SIM_MAX_MARGIN_PCT`：单笔最大保证金占用，占账户权益百分比。

模拟开单只在出现 `long_watch` 或 `short_watch` 触发信号时写入账本；后续扫描会按卡片里的止损、止盈1、止盈2检查是否平仓，并在卡片顶部展示已平仓样本、胜负笔数、胜率、累计盈亏和当前持仓数。GitHub Actions 定时运行时会通过 Actions cache 轻量保存 `data/binance_contract_sim_state.json`，避免每轮扫描后胜率重新归零。

## 风险边界

这些字段只是行情信号和风险计划提示，不代表自动下单，也不保证成交或收益。合约交易应结合杠杆、流动性、滑点和账户风险承受能力执行。
