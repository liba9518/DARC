# 胜率提升流程

目标不是每天都有交易，而是只在“你的真实概率 > 市场价格 + 安全边际”时出手。

## 1. 先拉市场

```bash
npm run worldcup:snapshot
npm run worldcup:report
```

## 2. 写自己的概率

复制 `predictions/worldcup.example.json`，新建自己的预测文件，例如：

```text
predictions/worldcup.json
```

格式：

```json
{
  "market-slug": {
    "Outcome name": 0.17
  }
}
```

`market-slug` 和 `Outcome name` 可以从 `data/polymarket-worldcup-markets.json` 或 `npm run worldcup:report` 里找到。

## 3. 只买正期望

```bash
npm run worldcup:edge -- data/polymarket-worldcup-markets.json predictions/worldcup.json 1000
```

输出含义：

- `Market`：市场价格，近似市场共识概率
- `Model`：你填的独立预测概率
- `Edge`：`Model - Market`
- `ROI`：按当前价格估算的期望收益率
- `Stake`：分数 Kelly 仓位建议，默认最多 3% bankroll

## 4. 过滤规则

默认规则偏保守：

- edge 至少 3%
- ROI 至少 8%
- spread 不超过 8%
- 单笔仓位最多 3% bankroll
- Kelly 只用四分之一，避免模型过度自信

## 5. 胜率纪律

- 没有 BUY 信号就不交易。
- 不为了“看起来确定”而买低赔率，关键是期望值，不是命中率本身。
- 每次预测先写概率，再看结果；不要赛后改口。
- 复盘 Brier score 和 ROI，发现某类市场长期亏损就停掉。
- 新闻、伤病、赛程、阵容确认前后要重新估概率。

## 6. 赛后复盘

在 `results/worldcup.json` 里填真实结果：

```json
{
  "market-slug": {
    "Outcome name": 1,
    "Other outcome": 0
  }
}
```

然后评分：

```bash
npm run worldcup:score -- predictions/worldcup.json results/worldcup.json
```

Brier score 越低越好。长期胜率提升来自这里：只保留你能稳定校准得比市场更好的市场类型。
