# 世界杯策略推送工具

这是一个面向世界杯赛前策略的 Node.js 工具链，用于采集 FIFA 官方世界杯赛程，并在比赛未开赛前生成当天赛事预测和飞书策略卡。

项目只做数据采集、策略展示和人工研究辅助，不会自动下单或执行真实交易。

## 核心能力

- FIFA 官方赛程、比分、状态采集
- Hugging Face Poisson 预测本地复刻
- 胜负平、比分、大小球、胜负平二串四张飞书卡
- 北京时间三批次自动推送
- GitHub Actions 云端执行，支持本机关机后继续运行

## 常用命令

```bash
npm run check
npm test
npm run fusion:snapshot
npm run fusion:report
npm run feishu:preview
npm run feishu:auto-push
```

手动执行完整推送链路：

```bash
npm.cmd run fusion:snapshot -- data/fusion-signals.json 48 20
npm.cmd run feishu:push-scheduled
```

## 云端自动推送

本机关机也要继续自动推送时，使用 GitHub Actions。

工作流文件：

```text
.github/workflows/worldcup-feishu-auto-push.yml
```

运行批次均按北京时间：

- `00:00`：覆盖 `00:00-08:00` 开赛赛事
- `08:00`：覆盖 `08:00-16:00` 开赛赛事
- `16:00`：覆盖 `16:00-次日00:00` 开赛赛事

GitHub 仓库需要配置两个 Secrets：

- `FEISHU_WEBHOOK_URL`
- `FEISHU_BOT_SECRET`

完整部署清单见：

```text
docs/github-actions-deploy.md
```

## 本地备用任务

如果希望本机开机时也能作为备用执行器，可以安装 Windows 任务计划：

```powershell
.\scripts\install-feishu-auto-push.ps1
```

本地任务计划不是云端部署的必要条件；电脑关机时只能依赖 GitHub Actions 或其他云端运行环境。

## 策略边界

- FIFA 官方 `calendar/matches` 是赛程、开赛时间、比分和比赛状态唯一赛程主源。
- 自动推送只按 FIFA 当天官方赛程筛选未开赛赛事。
- 预测方向来自本地模型，不再依赖欧盘、Lyihub 或 Polymarket 采集。
- 没有投注赔率时，只展示模型方向，不给下注建议。
- 没有合格信号时明确不下注。

更多策略和推送规则见：

```text
docs/data-fusion-feishu.md
```

## 数据文件

运行时数据默认写入 `data/`，其中 JSON、JSONL 和临时文件被 `.gitignore` 忽略，避免把快照和推送状态误提交。

GitHub Actions 会通过 cache 保存云端推送状态，用于同一北京时间批次去重和失败补发。
