# 飞书策略云端自动推送

这份说明用于把飞书策略推送从本地 Windows 任务计划器迁移到 GitHub Actions。迁移后，即使本地电脑关机、断网，云端仍会按计划抓取数据并推送飞书机器人。

## 1. 工作流入口

工作流文件：

```text
.github/workflows/feishu-strategy-push.yml
```

启用后会自动执行：

- A股盘前策略：周一到周五 09:10，北京时间。
- A股收盘复盘：周一到周五 15:20，北京时间。
- 美股盘前策略：周一到周五 21:10，北京时间。
- 美股收盘复盘：北京时间周二到周六 06:30，对应美股周一到周五收盘后。
- A股盘中监控：交易时段窗口内每 15 分钟检查一次，只在达到异动门槛时推送。
- 美股盘中监控：覆盖夏令时和冬令时交易窗口，每 15 分钟检查一次，只在达到异动门槛时推送。

## 2. 必填密钥

在 GitHub 仓库页面进入：

```text
Settings -> Secrets and variables -> Actions -> Secrets
```

添加：

```text
FEISHU_WEBHOOK_URL
```

如果飞书机器人开启了签名校验，再添加：

```text
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
FEISHU_WEBHOOK_KEYWORD
```

不配置时，工作流会使用仓库内置默认值。

## 4. 手动测试

在 GitHub 仓库页面进入：

```text
Actions -> Feishu strategy push -> Run workflow
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
```

这些状态用于减少重复推送和盘中重复提醒。GitHub Actions cache 不是数据库，但足够支撑当前轻量级策略推送。

## 6. 注意事项

- GitHub scheduled workflow 不是实时定时器，可能有几分钟延迟。
- 如果仓库长期没有活动，GitHub 可能暂停定时工作流，需要在 Actions 页面重新启用。
- 如果飞书机器人设置了 IP 白名单，GitHub Actions 的出口 IP 不固定，不建议使用固定 IP 白名单；如必须使用白名单，建议改用云服务器或云函数并绑定固定出口。
- 本地 Windows 任务计划器和 GitHub Actions 不建议长期同时开启同一类任务，否则可能重复推送。
