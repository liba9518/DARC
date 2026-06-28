# 交易安全边界

我可以帮你做：

- 拉取 Polymarket 世界杯市场数据
- 计算市场隐含概率
- 结合你的独立预测概率筛选正期望机会
- 生成 REVIEW_ONLY 限价单计划
- 做模拟盘、复盘、仓位和风险控制

我不会做：

- 无人值守自动买入
- 替你绕过地区、身份、平台限制
- 存储或要求你粘贴私钥
- 在没有你逐笔确认的情况下提交真实订单

## 为什么不直接自动买

预测市场交易涉及资金风险、合规限制、流动性冲击、滑点和模型错误。真正提高长期胜率的方式不是更快下单，而是更严格地过滤：

- 只有正期望才买
- 只用限价单
- 单笔风险小
- 每天和每类市场有上限
- 赛后用实际结果复盘模型校准

## 账户充值后怎么做

1. 确认你所在地区和账户使用符合 Polymarket 的规则。
2. 保管好私钥，不要发给我或写入仓库。
3. 运行市场快照和信号分析。
4. 生成 `data/worldcup-trade-plan.json`。
5. 你逐笔检查后，自己在 Polymarket 或你信任的钱包/客户端里执行。

```bash
npm run worldcup:snapshot
npm run worldcup:edge -- data/polymarket-worldcup-markets.json predictions/worldcup.json 1000
npm run worldcup:plan -- data/polymarket-worldcup-markets.json predictions/worldcup.json 1000
```
