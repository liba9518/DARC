# Quiver + 韩股/美股飞书策略部署

本仓库以 `ZhuLinsen/daily_stock_analysis` 为主框架，保留其 AI 分析、15 套策略、WebUI、Docker 和飞书推送能力；同时增加独立的另类数据策略雷达：

- 美股：Quiver Quant 官方 API（国会交易、内部人交易、政府合同、场外/暗池、Quiver News）。
- 韩股：使用 Yahoo Finance `.KS` / `.KQ` 后缀代码获取日线行情和 KOSPI / KOSDAQ 指数。
- AI供应链：读取 `wesson9527/chokepoint-atlas` 生成的研究包、赛道评分、候选公司和催化剂。
- 推送：股票策略云端必须使用 `STOCK_FEISHU_WEBHOOK_URL`、股票签名密钥和关键词；不再回退通用 `FEISHU_WEBHOOK_URL`，避免与世界杯机器人串群。
- 容错：Quiver 或韩股/美股数据源失败时降级并继续推送。

## 1. 配置

复制 `.env.example` 为 `.env`，至少填写：

```env
STOCK_LIST=AAPL,NVDA,TSLA,600519,300750

# daily_stock_analysis 的 AI 模型（任选一种）
OPENAI_API_KEY=your_key
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
OPENAI_MODEL=your_model

# 飞书群自定义机器人
STOCK_FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/your_stock_hook
# STOCK_FEISHU_WEBHOOK_SECRET=your_stock_signing_secret
# STOCK_FEISHU_WEBHOOK_KEYWORD=股票日报

# 通用飞书机器人；如果同时部署世界杯等其他机器人，不建议股票策略复用这一组
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/your_hook
# FEISHU_WEBHOOK_SECRET=your_signing_secret
# FEISHU_WEBHOOK_KEYWORD=股票日报

# Quiver API
QUIVER_API_TOKEN=your_quiver_bearer_token
ALT_DATA_MAX_ITEMS=8
ALT_DATA_SCHEDULE_TIME=17:45
ALT_DATA_RUN_IMMEDIATELY=true

# Chokepoint Atlas输出；多个路径用分号分隔
CHOKEPOINT_ATLAS_PATHS=data/chokepoint-atlas
CHOKEPOINT_ATLAS_MAX_AGE_DAYS=45

# 每日两张精选卡片
US_STRATEGY_POOL=NVDA,TSLA,AAPL,MSFT,AMZN,GOOGL,META,COIN,MSTR,SPY,QQQ,AMD,AVGO
KR_STRATEGY_POOL=005930.KS,000660.KS,373220.KS,005380.KS,035420.KS,051910.KS,006400.KS,035720.KQ,247540.KQ,091990.KQ
US_DAILY_CARD_PICK_COUNT=0
KR_DAILY_CARD_PICK_COUNT=0
KR_CARD_SCHEDULE_TIME=07:40
US_CARD_SCHEDULE_TIME=21:10
KR_REVIEW_SCHEDULE_TIME=14:50
US_REVIEW_SCHEDULE_TIME=06:30
DAILY_CARD_RETENTION_BONUS=4
US_MIN_DOLLAR_VOLUME=10000000
KR_MIN_DAILY_TURNOVER_KRW=5000000000
FEISHU_STRATEGY_WATCHDOG_ENABLED=true

# 主分析任务
SCHEDULE_ENABLED=true
SCHEDULE_TIME=18:00
SCHEDULE_RUN_IMMEDIATELY=false
```

`QUIVER_API_TOKEN` 需要在 Quiver API 账户中获取；不同套餐可访问的数据集不同。没有 Token 时，主分析和 A 股行情仍可运行。

`*_DAILY_CARD_PICK_COUNT=0` 表示不固定推荐数量，只要候选池内标的满足触发条件就推送；如需限制单次最多展示数量，可改成对应市场的具体正整数。

## 2. 生成 Chokepoint Atlas 数据

该项目不是实时行情 API，而是结构化供应链研究工具。建议单独克隆，生成结果后让策略雷达采集输出目录：

```powershell
git clone https://github.com/wesson9527/chokepoint-atlas.git external\chokepoint-atlas

# 单研究线
.\.venv\Scripts\python.exe external\chokepoint-atlas\scripts\build_research_pack.py `
  --input external\chokepoint-atlas\examples\ai_factory_lane_input.json `
  --output data\chokepoint-atlas\ai-factory

# 多研究线比较
.\.venv\Scripts\python.exe external\chokepoint-atlas\scripts\compare_lanes.py `
  --input external\chokepoint-atlas\examples\lane_compare_input.json `
  --output data\chokepoint-atlas\lane-ranking
```

策略雷达会递归读取：

- `research_pack.json`
- `lane_ranking.json`
- `lane_compare_input.json`
- `ai_factory_lane_input.json`

并提取赛道、系统瓶颈、综合评分、优先级、候选公司、催化剂和研究日期。过期研究不会被当作实时信号，而会显示“资料待更新”。

## 3. 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 先看内容，不推送
.\.venv\Scripts\python.exe scripts\push_strategy_digest.py --dry-run

# 测试真实飞书推送
.\.venv\Scripts\python.exe scripts\push_strategy_digest.py

# 主 AI 分析
.\.venv\Scripts\python.exe main.py --stocks AAPL,NVDA,600519

# 两个常驻定时任务（分别开两个终端）
.\.venv\Scripts\python.exe main.py --schedule
.\.venv\Scripts\python.exe scripts\push_strategy_digest.py --schedule

# 美股/韩股两张每日策略卡片
.\.venv\Scripts\python.exe scripts\push_binance_long_signals.py --side both --symbols MU,SAND
.\.venv\Scripts\python.exe scripts\push_binance_long_signals.py --side long --symbols MU,SAND
.\.venv\Scripts\python.exe scripts\push_binance_long_signals.py --side short --symbols MU,SAND

# 收盘复盘与次日预备策略
.\.venv\Scripts\python.exe scripts\push_post_close_review.py --market kr
.\.venv\Scripts\python.exe scripts\push_post_close_review.py --market us
```

每日精选采用以下稳定性约束：

- 先判断 SPY / KOSPI 的顺风、震荡或逆风环境。
- 只优先纳入价格、20日线和60日线方向一致的标的。
- 使用相对基准强度，而不是只比较绝对涨幅。
- 设置成交额门槛，排除流动性不足的候选。
- 对单日暴涨、月度过热、高波动和较大回撤扣分。
- 给予上期入选标的小幅保留分，只有更强候选形成明显优势才换入。
- 相同行情日期且名单不变时自动跳过，避免重复推送。

卡片中的“确定性 A/B/C”表示多个独立条件的一致程度，不代表收益承诺。

云端盘前推送使用北京时间：

- 韩股：07:40，对应韩国开盘前约 20 分钟。
- 美股：20:50、21:10、21:25，三次都在北京时间 21:30 开盘前完成。
- 信号只使用上一完整交易日数据，不读取尚未收盘的日 K 线。

收盘后复盘闭环：

- 韩股 14:50：统计当天精选表现、上涨命中数、市场环境，并生成次日预备名单。
- 美股北京时间 06:30、06:40、06:50：兼容夏令时与冬令时，确保在正式收盘以后执行。
- 复盘会记录保留、新进入和暂时移出的标的。
- 次日预备名单只用于研究准备；韩股 / 美股盘前任务会重新计算并确认最终名单。
- 相同收盘日期和复盘结论不会重复发送。
- 云端看门狗会在关键窗口内检查当天是否已有成功推送记录；如果 GitHub 定时任务延迟或漏跑，会自动补发一次，已成功推送过则不会重复刷屏。

## 4. Docker

```powershell
docker compose -f docker\docker-compose.yml up -d --build analyzer strategy-digest daily-cards
docker compose -f docker\docker-compose.yml logs -f strategy-digest
```

## 5. 飞书机器人

在目标群聊中依次打开“群设置 → 群机器人 → 添加机器人 → 自定义机器人”，复制 Webhook URL。

- 开启股票机器人签名校验：优先填写 `STOCK_FEISHU_WEBHOOK_SECRET`。
- 开启股票机器人关键词：优先填写 `STOCK_FEISHU_WEBHOOK_KEYWORD`。
- 开启 IP 白名单：将部署机器的出口 IP 加入白名单。

完整 AI 报告也可使用飞书 App Bot；独立策略雷达当前使用群 Webhook，便于低依赖部署。

## 6. 数据与授权边界

- Quiver 使用官方 Bearer API，不抓取登录页面或绕过权限。
- `a-stock-data` 原始说明保存在 `vendor/a-stock-data/`，其 Apache-2.0 许可要求保留来源说明。
- `chokepoint-atlas` 当前仓库未提供明确 LICENSE，因此本项目只读取其用户生成的 JSON 输出，不复制或再分发其源码。
- 另类数据观察分只用于排序，不能视为买卖建议。
# 当前状态：仅推送 Binance 股票合约信号

当前飞书机器人已经收敛为只抓取并推送 Binance 股票合约 / TradFi equity perpetual 多空信号，不扫描 BTC、ETH、SOL 等加密货币合约。旧的美股 / 韩股普通股票盘前卡、收盘复盘卡、盘中监控不再由 `.github/workflows/feishu-strategy-push.yml`、`scripts/run_stock_task.ps1` 或 `scripts/push_strategy_watchdog.py` 触发。合约推送入口见 `docs/binance-contract-data.md`。
