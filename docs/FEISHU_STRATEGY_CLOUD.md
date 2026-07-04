# 飞书策略云端自动推送

这份说明用于把飞书策略推送从本地 Windows 任务计划器迁移到 GitHub Actions。迁移后，即使本地电脑关机、断网，云端仍会按计划抓取数据并推送飞书机器人。

## 1. 工作流入口

工作流文件位于 `main` 分支：

```text
.github/workflows/stock-strategy-key-cards.yml
.github/workflows/stock-strategy-watchdog.yml
.github/workflows/stock-strategy-intraday-monitor.yml
.github/workflows/stock-strategy-feishu-manual-push.yml
```

启用后会自动执行：

- A股盘前策略：周一到周五 09:00、09:10、09:20，北京时间三次补跑，全部在 09:30 开盘前完成。
- A股午间复盘：周一到周五 11:45，北京时间一次复盘上午表现并给出下午预案。
- A股收盘复盘：周一到周五 15:20、15:30、15:40，北京时间三次补跑。
- 美股盘前策略：周一到周五 20:50、21:10、21:25，北京时间三次补跑，确保尽量在 21:30 开盘前送达。
- 美股收盘复盘：北京时间周二到周六 06:30、06:40、06:50，对应美股周一到周五收盘后三次补跑。
- A股盘中监控：交易时段窗口内每 30 分钟检查一次，只在达到异动门槛时推送。
- 美股盘中监控：覆盖夏令时和冬令时交易窗口，每 30 分钟检查一次，只在达到异动门槛时推送。

关键卡片补跑不会重复发送同一份名单：脚本会根据市场、行情日期和股票名单生成签名，已推送过的内容会自动跳过。

盘前策略卡和收盘复盘卡会展示对应市场的大盘指数价格：A股展示上证指数、深证成指、创业板指；美股展示标普五百、纳斯达克、道琼斯。指数获取失败不会阻断精选股票推送。

云端推送前会自动抓取 A股 / 美股相关的重要快讯，只保留命中市场、宏观、指数、监管、财报、芯片、人工智能等关键词的信息。快讯源失败时不会阻断策略卡推送；卡片会显示“暂无新的重要快讯，按既有策略信号执行”。

关键卡片看门狗会在盘前、午间复盘、收盘复盘等关键窗口内重复检查状态缓存：如果发现当天应该推送但状态里还没有成功记录，会自动强制补发一次；如果已经推送过，则只记录“无需补发”，不会重复刷屏。看门狗与关键卡片工作流共用并发锁，避免两个工作流同时推送同一类卡片。

## 2. 必填密钥

在 GitHub 仓库页面进入：

```text
Settings -> Secrets and variables -> Actions -> Secrets
```

添加：

```text
FEISHU_WEBHOOK_URL
STOCK_FEISHU_WEBHOOK_URL
```

如果仓库里同时部署了世界杯预测等其他机器人，股票策略必须配置 `STOCK_FEISHU_WEBHOOK_URL`，不要复用世界杯的 `FEISHU_WEBHOOK_URL`，否则股票卡片会发到世界杯群。云端股票工作流不会再回退到旧的 `FEISHU_WEBHOOK_URL`，缺少股票专用 Secret 时会直接失败，避免串群。

如果飞书机器人开启了签名校验，再添加：

```text
STOCK_FEISHU_WEBHOOK_SECRET
FEISHU_WEBHOOK_SECRET
```

如果需要 Quiver 官方数据，再添加：

```text
QUIVER_API_TOKEN
```

不要把真实 webhook 或 token 写进代码、文档或工作流文件。

## 3. 可选策略变量

在 GitHub 仓库页面进入：

```text
Settings -> Secrets and variables -> Actions -> Variables
```

可以按需配置：

```text
US_STRATEGY_POOL
A_STRATEGY_POOL
DAILY_CARD_PICK_COUNT
DAILY_CARD_RETENTION_BONUS
US_MIN_DOLLAR_VOLUME
A_MIN_TURNOVER_CNY
INTRADAY_MOVE_THRESHOLD
INTRADAY_EXTREME_THRESHOLD
INTRADAY_STEP_THRESHOLD
INTRADAY_COOLDOWN_MINUTES
FEISHU_STATUS_ON_SKIP
FEISHU_STRATEGY_WATCHDOG_ENABLED
FEISHU_INTRADAY_STATUS_ON_IDLE
FEISHU_WEBHOOK_KEYWORD
STOCK_FEISHU_WEBHOOK_KEYWORD
PAPER_TRADING_ENABLED
PAPER_TRADING_CN_CAPITAL
PAPER_TRADING_US_CAPITAL
PAPER_TRADING_RISK_CONTROL_ENABLED
PAPER_TRADING_STOP_LOSS_PCT
PAPER_TRADING_TAKE_PROFIT_PCT
PAPER_TRADING_TRAILING_TAKE_PROFIT_DRAWDOWN_PCT
PAPER_TRADING_TRAILING_TAKE_PROFIT_ARM_PCT
```

不配置时，工作流会使用仓库内置默认值。

`FEISHU_STATUS_ON_SKIP` 用于控制“运行状态卡”。云端关键卡片工作流默认开启：当盘前或复盘任务正常运行，但没有生成有效名单时，会发送一张简短状态卡，说明系统仍在运行；重复补跑不会重复发送同一张状态卡。

`FEISHU_STRATEGY_WATCHDOG_ENABLED` 用于控制关键卡片看门狗。云端工作流默认开启：看门狗只在关键推送窗口内发现当天未成功记录时补发，不会替代原来的三次固定推送。

`FEISHU_INTRADAY_STATUS_ON_IDLE` 用于控制盘中“暂无明显异动”的状态卡。云端盘中监控工作流默认开启：监控正常运行但没有达到异动门槛时，每个市场每天最多发送一张状态卡，避免群里长时间没有系统反馈。

`PAPER_TRADING_ENABLED` 用于控制模拟跟单。云端工作流默认开启；A股默认模拟本金为 `10000` 人民币，美股默认模拟本金为 `10000` 美元，可分别用 `PAPER_TRADING_CN_CAPITAL` 和 `PAPER_TRADING_US_CAPITAL` 覆盖。模拟跟单只记录策略调仓、持仓市值和盈亏，不连接券商、不下真实订单。

`PAPER_TRADING_RISK_CONTROL_ENABLED` 用于控制模拟跟单的盘中止盈止损纪律，云端盘中监控默认开启。默认纪律线为：亏损达到 `PAPER_TRADING_STOP_LOSS_PCT=5` 时模拟止损；盈利达到 `PAPER_TRADING_TAKE_PROFIT_PCT=8` 时模拟止盈；最高浮盈达到 `PAPER_TRADING_TRAILING_TAKE_PROFIT_ARM_PCT=8` 后，若回撤达到 `PAPER_TRADING_TRAILING_TAKE_PROFIT_DRAWDOWN_PCT=4`，则触发移动止盈。以上只更新模拟账本并推送飞书处理卡，不会真实下单。

## 4. 手动测试

在 GitHub 仓库页面进入：

```text
Actions -> Stock Strategy Feishu Manual Push -> Run workflow
```

推荐先选择：

```text
all-preopen
```

如果飞书群收到 A股策略 和 美股策略 两张卡片，说明云端推送链路已经打通。

## 5. 状态保存

工作流会通过 GitHub Actions cache 保存：

```text
data/daily_card_state.json
data/intraday_alert_state.json
data/paper_trade_state.json
```

关键卡片、盘中监控和模拟跟单账本会通过 cache 保存状态，避免高频盘中任务覆盖盘前/复盘状态。GitHub Actions cache 不是数据库，但足够支撑当前轻量级策略推送和模拟盘测试。

## 6. 注意事项

- GitHub scheduled workflow 不是实时定时器，可能有几分钟延迟；关键卡片已经配置固定补跑和看门狗补发来提高到达率，但如果 GitHub 整体队列严重延迟，仍可能出现晚于目标时间送达的情况。
- 如果仓库长期没有活动，GitHub 可能暂停定时工作流，需要在 Actions 页面重新启用。
- 如果飞书机器人设置了 IP 白名单，GitHub Actions 的出口 IP 不固定，不建议使用固定 IP 白名单；如必须使用白名单，建议改用云服务器或云函数并绑定固定出口。
- 本地 Windows 任务计划器和 GitHub Actions 不建议长期同时开启同一类任务，否则可能重复推送。
