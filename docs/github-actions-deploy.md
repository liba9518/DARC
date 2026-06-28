# GitHub Actions 云端部署清单

这份清单用于把世界杯赛前策略自动推送部署到 GitHub Actions。部署后，即使本机电脑关机，云端仍会按北京时间自动执行。

## 执行内容

- 工作流文件：`.github/workflows/worldcup-feishu-auto-push.yml`
- 入口命令：`npm run feishu:auto-push`
- 执行批次：北京时间 `00:00`、`08:00`、`16:00`
- 赛程来源：FIFA 官方世界杯 `calendar/matches`
- 推送范围：每个批次推送北京时间当天所有仍未开赛的官方赛事预测
- 推送卡片：胜负平、比分、大小球、胜负平二串

## GitHub 配置步骤

1. 打开 GitHub 仓库的 `Settings -> Secrets and variables -> Actions`。
2. 添加两个仓库级 `Repository secrets`：
   - `FEISHU_WEBHOOK_URL`
   - `FEISHU_BOT_SECRET`
3. 打开仓库的 `Actions` 页面。
4. 进入 `World Cup Feishu Auto Push` 工作流。
5. 点击 `Run workflow`，分支选择 `main`，手动运行一次。

## 首次运行检查

首次手动运行后，检查日志里是否完成以下步骤：

- `Checkout automation branch`
- `Install dependencies`
- `Check scripts`
- `Restore push state`
- `Validate Feishu secrets`
- `Run auto push`

如果 `Validate Feishu secrets` 失败，优先检查两个 Secrets 是否在 `Repository secrets` 中，且名称完全一致。

## 定时触发时间

GitHub Actions 使用 UTC cron，工作流已经换算为北京时间三批次：

- `0 16 * * *` UTC -> 北京时间 `00:00`
- `0 0 * * *` UTC -> 北京时间 `08:00`
- `0 8 * * *` UTC -> 北京时间 `16:00`

代码内部也使用 `Asia/Shanghai` 判断日期、今日赛事、批次和去重状态。

## 状态去重

GitHub Actions 每次运行都是新的云端机器，因此工作流使用 `actions/cache` 保存状态文件：

- `data/last-pushed-odds.json`
- `data/feishu-push-progress.json`

文件名保留旧名称用于兼容；当前语义是 FIFA 官方赛程批次推送状态，不再表示赔率变化。

## 本地备用方案

本机关机时以 GitHub Actions 为主。如果还想在本机开机时做备用推送，可以安装 Windows 任务计划：

```powershell
.\scripts\install-feishu-auto-push.ps1
```

本地任务计划不是云端部署的必要条件。
