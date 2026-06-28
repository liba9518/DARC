# 世界杯策略卡与飞书推送

本文说明世界杯赛前策略卡的数据来源、下注边界、北京时间批次和飞书自动推送规则。

## 数据主线

- FIFA 官方 `calendar/matches` 数据是赛程、官方开赛时间、比分和比赛状态的主源。
- Lyihub 只补充欧盘、模型票选、天气和球队动态。
- Hugging Face 本地复刻模型只用于独立模型概率参考。
- Polymarket 只作为市场价格参考，不进入模型概率。
- 采集失败时不得覆盖有效快照，也不得更新整体成功状态。

北京时间当天的 FIFA 官方比赛必须完整进入快照，包括已结束、进行中和未开赛比赛；不能因为缺少预测、欧盘或 Polymarket 市场而漏场。

## 概率和下注边界

模型概率只融合独立预测源，不混入欧盘或 Polymarket 市场价格。欧盘只用于计算隐含概率、概率优势和期望收益。

胜负平信号只有同时满足以下条件才标记为 `RESEARCH`：

- 至少两个独立模型源；
- 模型方向一致；
- 校准样本数量达到配置门槛；
- 模型概率优势达到配置门槛；
- 期望收益为正且达到配置门槛；
- 市场价格差异和流动性风险在配置范围内。

`WATCH`、`SKIP` 和 `INFO` 都不代表下注建议。比分和大小球没有对应赔率时，只展示模型方向，不给下注建议。

## 四张飞书卡

每次推送固定生成四张卡：

1. 世界杯胜负平预测
2. 世界杯比分预测
3. 世界杯大小球预测
4. 世界杯胜负平二串

二串只组合两个单场 `RESEARCH` 正期望信号，同组比赛不组合，并使用保守联合概率折扣。没有合格组合时明确显示不下注。

每张卡尾部固定保留：

- 查看 Polymarket
- 查看 AI 分析

## 北京时间三批次

每天按北京时间运行三批：

- `00:00` 批次：重点覆盖 `00:00-08:00` 开赛赛事
- `08:00` 批次：重点覆盖 `08:00-16:00` 开赛赛事
- `16:00` 批次：重点覆盖 `16:00-次日00:00` 开赛赛事

所有日期边界、今日筛选、开赛时间和推送批次都使用 `Asia/Shanghai`，不使用 UTC 或服务器本地日期。

## 手动运行

先生成快照，再按变化推送：

```bash
npm.cmd run fusion:snapshot -- data/fusion-signals.json 48 20
npm.cmd run feishu:push-if-odds-changed
```

也可以用单一入口：

```bash
npm.cmd run feishu:auto-push
```

`feishu:auto-push` 会先生成最新快照，再按当前北京时间批次执行推送检查。

## 推送可靠性

- 今日官方赛程、比分、比赛状态或欧盘 H/D/A 赔率变化时才更新推送。
- 同一批次已成功推送且状态未变化时跳过。
- 推送使用卡片级断点。
- 四张卡全部成功后才更新整体成功状态。
- 中途失败时，下一次只补发未成功卡片。
- 任何推送流程都不会执行真实交易。

## 云端自动推送

本机关机也要继续执行时，使用 GitHub Actions：

- 部署清单：`docs/github-actions-deploy.md`
- 工作流文件：`.github/workflows/feishu-auto-push.yml`
- GitHub Secrets：
  - `FEISHU_WEBHOOK_URL`
  - `FEISHU_BOT_SECRET`

工作流会在北京时间 `00:00`、`08:00`、`16:00` 自动运行，并通过 GitHub Actions cache 保留推送状态。

## 验证命令

```bash
npm.cmd run check
npm.cmd test
npm.cmd run feishu:preview
npm.cmd run model:report
```

比赛结算后，可用 `model:report` 复盘 Brier Score、`RESEARCH` 信号数量和等额下注 ROI。在样本不足前，所有模型信号都应视为研究结论，不是自动交易指令。
