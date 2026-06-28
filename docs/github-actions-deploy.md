# GitHub Actions 云端部署清单

这份清单用于把世界杯赛前策略自动推送部署到 GitHub Actions。部署后，即使本机电脑关机，云端仍会按北京时间自动执行。

## 执行内容

- 工作流文件：`.github/workflows/feishu-auto-push.yml`
- 入口命令：`npm run feishu:auto-push`
- 执行批次：北京时间 `00:00`、`08:00`、`16:00`
- 推送卡片：胜负平、比分、大小球、胜负平二串

## GitHub 配置步骤

1. 把当前仓库推送到 GitHub。
2. 打开 GitHub 仓库的 `Settings -> Secrets and variables -> Actions`。
3. 添加两个仓库级 Secrets：
   - `FEISHU_WEBHOOK_URL`
   - `FEISHU_BOT_SECRET`
4. 打开仓库的 `Actions` 页面，确认 GitHub Actions 已启用。
5. 进入 `Feishu Auto Push` 工作流，点击 `Run workflow` 手动运行一次。

## 首次运行检查

首次手动运行后，检查日志里是否完成以下步骤：

- `Install dependencies`
- `Check scripts`
- `Restore push state`
- `Run auto push`
- 四张飞书卡全部返回成功

如果 `Run auto push` 失败，优先检查两个 Secrets 是否填写正确，以及飞书机器人是否仍允许 Webhook 推送。

## 定时触发时间

GitHub Actions 使用 UTC cron，工作流中已经换算为北京时间三批次：

- `0 16 * * *` UTC -> 北京时间 `00:00`
- `0 0 * * *` UTC -> 北京时间 `08:00`
- `0 8 * * *` UTC -> 北京时间 `16:00`

代码内部也会用 `Asia/Shanghai` 判断日期、今日赛事、批次窗口和去重状态。

## 状态去重

GitHub Actions 每次运行都是新的云端机器，因此工作流使用 `actions/cache` 保存这两个状态文件：

- `data/last-pushed-odds.json`
- `data/feishu-push-progress.json`

这样同一批次重复触发时可以跳过已成功推送的策略；如果某张卡中途失败，下一次运行会继续补发未成功的卡片。

## 本地备用方案

本机关机时应以 GitHub Actions 为主。如果还想在本机开机时做备用推送，可以安装 Windows 任务计划：

```powershell
.\scripts\install-feishu-auto-push.ps1
```

本地任务计划不是云端部署的必要条件。
