import { createHmac } from "node:crypto";
import { summarizeFusion } from "./fusion-engine.js";
import { buildScoreStrategy, buildTotalsStrategy } from "./score-engine.js";

export function buildFeishuResultCard(snapshot, { maxSignals = 20, scope = "today", batchKey = null } = {}) {
  const summary = summarizeFusion(snapshot);
  const selected = sortByReferenceOdds(
    selectResultPredictionSignals(summary.signals, snapshot.generatedAt, scope, batchKey)
  ).slice(0, maxSignals);
  const elements = [
    markdownElement("**[星耀系统世界杯预测]**"),
    introElement(snapshot, selected, [
      "**预测说明：** 赛程和开赛时间以国际足联官方数据为准。",
      "**筛选原则：** 只选模型意见一致、历史样本充足、具备明显优势的比赛。",
      "**结果说明：** 每场直接给出“本场精选”或“本场放弃”。"
    ], scope),
    dailyNewMatchesElement(selected)
  ];

  if (selected.length === 0) elements.push(emptyTodayElement());

  for (const signal of selected) {
    elements.push({ tag: "hr" });
    elements.push(markdownElement(resultContent(signal)));
  }
  elements.push(cardFooter(selected));

  return interactiveCard(
    "世界杯胜负平预测",
    "purple",
    elements
  );
}

export function buildFeishuScoreCard(snapshot, { maxSignals = 20, scope = "today", batchKey = null } = {}) {
  const selected = selectSignals(snapshot.signals ?? [], snapshot.generatedAt, scope, batchKey).slice(0, maxSignals);
  const elements = [
    introElement(snapshot, selected, [
      "**模型标准：** 比分来自预期进球分布，仅作赛果路径参考。",
      "**下注门禁：** 没有对应比分赔率和样本外校准时，一律不提供比分下注建议。"
    ])
  ];

  if (selected.length === 0) elements.push(emptyTodayElement());

  for (const signal of selected) {
    const score = buildScoreStrategy(signal);
    elements.push({ tag: "hr" });
    elements.push(markdownElement(scoreContent(signal, score)));
  }
  elements.push(cardFooter(selected));

  return interactiveCard("世界杯比分预测", "orange", elements);
}

export function buildFeishuTotalsCard(snapshot, { maxSignals = 20, scope = "today", batchKey = null } = {}) {
  const selected = selectSignals(snapshot.signals ?? [], snapshot.generatedAt, scope, batchKey).slice(0, maxSignals);
  const elements = [
    introElement(snapshot, selected, [
      "**盘口线：** 2.5 球。",
      "**下注门禁：** 没有可验证的大小球赔率就无法计算期望收益，因此只展示方向，不给下注建议。"
    ])
  ];

  if (selected.length === 0) elements.push(emptyTodayElement());

  for (const signal of selected) {
    const totals = buildTotalsStrategy(signal);
    elements.push({ tag: "hr" });
    elements.push(markdownElement(totalsContent(signal, totals)));
  }
  elements.push(cardFooter(selected));

  return interactiveCard("世界杯大小球预测", "purple", elements);
}

export function buildFeishuResultParlayCard(snapshot, { scope = "today", batchKey = null } = {}) {
  const scoped = selectSignals(snapshot.signals ?? [], snapshot.generatedAt, scope, batchKey);
  const useUpcomingFallback = scoped.filter((signal) => signal.status === "upcoming").length < 2;
  const selected = useUpcomingFallback
    ? selectSignals(snapshot.signals ?? [], snapshot.generatedAt, "upcoming", batchKey)
    : scoped;
  const eligible = selected.filter(isParlayEligible);
  const qualified = buildResultParlays(eligible).at(0);
  const featured = qualified ?? buildDailyFeaturedParlays(selected).at(0);
  const elements = [
    introElement(snapshot, selected, [
      `**合格单场：** ${eligible.length} 场`,
      "**每日策略：** 每天只精选 1 组；优先两场正期望 RESEARCH 信号，否则按独立模型概率、一致性、校准样本和跨组去相关选择最高胜率组合。",
      "**风险提醒：** 兜底精选不等于正期望；二串必须两场全部命中，模型概率不保证赛果。"
    ], useUpcomingFallback ? "upcoming" : scope)
  ];

  if (!featured) {
    elements.push(markdownElement(
      "**【每日精选】暂无可组成二串的两场未开赛比赛**\n至少需要两场不同小组、具备独立模型概率的比赛；不为凑单使用失真数据。"
    ));
  }

  if (featured) {
    const qualifiedLabel = featured.qualified ? "合格二串" : "每日精选观察二串";
    const verdict = featured.qualified
      ? "达到正期望研究门槛，仍需人工复核阵容和临场赔率"
      : "按胜率优先强制精选，但未达到正期望门槛，仅作观察，不建议加注";
    elements.push({ tag: "hr" });
    elements.push(markdownElement([
      `**【${qualifiedLabel}】${featured.first.pickLabel} + ${featured.second.pickLabel}**`,
      `${featured.first.matchLabel}：${featured.first.pickLabel} @ ${formatOdds(featured.first.odds)}`,
      `官方开赛时间：${formatBeijingTime(featured.first.signal.kickoffAt)}`,
      `${featured.second.matchLabel}：${featured.second.pickLabel} @ ${formatOdds(featured.second.odds)}`,
      `官方开赛时间：${formatBeijingTime(featured.second.signal.kickoffAt)}`,
      `**综合赔率：${formatOdds(featured.combinedOdds)}**`,
      `保守联合命中率：${formatPercent(featured.combinedProbability)}`,
      `理论期望收益：${formatSignedPercent(featured.expectedValue)}`,
      `**【策略结论】${verdict}**`
    ].join("\n")));
  }
  elements.push(cardFooter(selected));

  return interactiveCard("世界杯胜负平二串", "red", elements);
}

export const buildFeishuCard = buildFeishuResultCard;

export async function sendFeishuWebhook({
  webhookUrl,
  secret,
  payload,
  fetchImpl = globalThis.fetch
}) {
  if (!webhookUrl) {
    throw new Error("FEISHU_WEBHOOK_URL is required");
  }

  const body = { ...payload };
  if (secret) {
    const timestamp = Math.floor(Date.now() / 1000);
    body.timestamp = String(timestamp);
    body.sign = createFeishuSignature(timestamp, secret);
  }

  const response = await fetchImpl(webhookUrl, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body)
  });
  const text = await response.text();
  let result;
  try {
    result = JSON.parse(text);
  } catch {
    result = { raw: text };
  }

  if (!response.ok || !isSuccess(result)) {
    throw new Error(`Feishu webhook failed: HTTP ${response.status} ${JSON.stringify(result)}`);
  }
  return result;
}

export function createFeishuSignature(timestamp, secret) {
  const stringToSign = `${timestamp}\n${secret}`;
  return createHmac("sha256", stringToSign).update("").digest("base64");
}

function resultContent(signal) {
  const common = [
    `**${signal.teamAZh} 对阵 ${signal.teamBZh}**`,
    `官方开赛时间：${formatBeijingTime(signal.kickoffAt)} · ${statusLabel(signal)}`
  ];

  if (signal.status === "finished") {
    return [...common,
      `**【实际胜负】${actualResult(signal)}**`,
      `实际比分：${formatActualScore(signal)}`
    ].join("\n");
  }

  if (signal.status === "live") {
    return [...common,
      `当前比分：${formatActualScore(signal)}`,
      "**【下注结论】进行中，不追单**"
    ].join("\n");
  }

  return [...common,
    `**【预测结果】${resultPickLabel(signal)}**`,
    `胜出机会：${formatPercent(signal.probability[signal.preferredSide])}`,
    `参考赔率：${formatOdds(signal.sportsbookOdds)}`,
    `模型把握：${plainAgreement(signal)} · 历史检验：${signal.calibrationMatches} 场`,
    `**【最终结论】${resultDecision(signal)}**`
  ].join("\n");
}

function scoreContent(signal, score) {
  const common = [
    `**${signal.teamAZh} vs ${signal.teamBZh}**`,
    `官方开赛时间：${formatBeijingTime(signal.kickoffAt)} · ${statusLabel(signal)}`
  ];
  if (signal.status === "finished") {
    return [...common, `**【实际比分】${formatActualScore(signal)}**`].join("\n");
  }
  if (signal.status === "live") {
    return [...common, `当前比分：${formatActualScore(signal)}`, "**【下注结论】进行中，不追单**"].join("\n");
  }
  if (!score.available) {
    return [...common, `**【下注结论】数据不足，不下注**`, score.reason].join("\n");
  }
  return [...common,
    `**【比分方向】${score.primaryScore}**`,
    `备选比分：${score.topScorelines.slice(1).map((item) => `${item.home}-${item.away}`).join("、")}`,
    `预期进球：${signal.teamAZh} ${score.expectedGoals.home} · ${signal.teamBZh} ${score.expectedGoals.away} · 合计 ${score.expectedGoals.total}`,
    `最高单一比分概率：${formatPercent(score.topScorelines[0].probability)}`,
    `**【下注结论】${score.betReason}**`
  ].join("\n");
}

function totalsContent(signal, totals) {
  const common = [
    `**${signal.teamAZh} vs ${signal.teamBZh}**`,
    `官方开赛时间：${formatBeijingTime(signal.kickoffAt)} · ${statusLabel(signal)}`
  ];
  if (signal.status === "finished") {
    return [...common,
      `**【实际大小球】${actualTotalsLabel(signal, 2.5)}**`,
      `实际比分：${formatActualScore(signal)}`
    ].join("\n");
  }
  if (signal.status === "live") {
    return [...common, `当前比分：${formatActualScore(signal)}`, "**【下注结论】进行中，不追单**"].join("\n");
  }
  if (!totals.available) {
    return [...common, "**【下注结论】数据不足，不下注**", totals.reason].join("\n");
  }
  return [...common,
    `**【大小球方向】${totalsDirection(totals)}**`,
    `预期总进球：${totals.expectedTotalGoals}`,
    `大 2.5 概率：${formatPercent(totals.overProbability)} · 小 2.5 概率：${formatPercent(totals.underProbability)}`,
    `双方进球概率：${formatPercent(totals.bttsYesProbability)}`,
    `进球区间：0-1 球 ${formatPercent(totals.goalBands.zeroToOne)} · 2-3 球 ${formatPercent(totals.goalBands.twoToThree)} · 4+ 球 ${formatPercent(totals.goalBands.fourPlus)}`,
    `**【下注结论】${totals.betReason}**`
  ].join("\n");
}

function introElement(snapshot, selected, extraLines, scope = "today") {
  const matchCountLine = scope === "upcoming"
    ? `**未开赛比赛：** ${selected.length} 场`
    : `**今日官方比赛：** ${snapshot.sourceStatus?.fifa?.todayMatchCount ?? selected.length} 场 · 卡片收录 ${selected.length} 场`;
  return markdownElement([
    `**国际足联赛程检查：** ${formatBeijingTime(snapshot.sourceStatus?.fifa?.checkedAt ?? snapshot.generatedAt)}`,
    `**欧盘检查时间：** ${oddsCheckTime(snapshot)}`,
    matchCountLine,
    ...extraLines
  ].join("\n"));
}

function interactiveCard(title, template, elements) {
  return {
    msg_type: "interactive",
    card: {
      config: { wide_screen_mode: true, enable_forward: true },
      header: {
        template,
        title: { tag: "plain_text", content: title }
      },
      elements
    }
  };
}

function markdownElement(content) {
  return {
    tag: "div",
    text: { tag: "lark_md", content }
  };
}

function isSuccess(result) {
  return result?.code === 0
    || result?.StatusCode === 0
    || result?.status === "success"
    || result?.msg === "success";
}

function isParlayEligible(signal) {
  return signal.status === "upcoming"
    && signal.signal === "RESEARCH"
    && Number(signal.expectedValue) >= 0.08
    && Number(signal.sportsbookOdds) > 1
    && Number.isFinite(Number(signal.probability?.[signal.preferredSide]));
}

function buildResultParlays(signals) {
  const combos = [];
  for (let firstIndex = 0; firstIndex < signals.length; firstIndex += 1) {
    for (let secondIndex = firstIndex + 1; secondIndex < signals.length; secondIndex += 1) {
      const first = signals[firstIndex];
      const second = signals[secondIndex];
      if (first.group && second.group && first.group === second.group) continue;

      const firstLeg = parlayLeg(first);
      const secondLeg = parlayLeg(second);
      const combinedOdds = firstLeg.odds * secondLeg.odds;
      const combinedProbability = firstLeg.probability * secondLeg.probability * 0.90;
      const expectedValue = combinedProbability * combinedOdds - 1;
      if (combinedProbability < 0.25 || expectedValue < 0.08) continue;

      combos.push({
        first: firstLeg,
        second: secondLeg,
        combinedOdds,
        combinedProbability,
        expectedValue,
        qualified: true
      });
    }
  }
  return combos.sort((left, right) =>
    right.combinedProbability - left.combinedProbability
    || right.expectedValue - left.expectedValue
  );
}

function buildDailyFeaturedParlays(signals) {
  const qualityTiers = [
    (signal) => isFeaturedCandidate(signal, { minProbability: 0.60, minSources: 2, requireAgreement: true }),
    (signal) => isFeaturedCandidate(signal, { minProbability: 0.55, minSources: 1, requireAgreement: false }),
    (signal) => isFeaturedCandidate(signal, { minProbability: 0, minSources: 1, requireAgreement: false })
  ];

  for (const predicate of qualityTiers) {
    const combos = buildFeaturedPairs(signals.filter(predicate));
    if (combos.length > 0) return combos;
  }
  return [];
}

function isFeaturedCandidate(signal, { minProbability, minSources, requireAgreement }) {
  const probability = Number(signal.probability?.[signal.preferredSide]);
  return signal.status === "upcoming"
    && Number.isFinite(probability)
    && probability >= minProbability
    && Number(signal.sourceCount) >= minSources
    && Number(signal.calibrationMatches) >= 30
    && (!requireAgreement || Number(signal.sourceAgreement) >= 2);
}

function buildFeaturedPairs(signals) {
  const combos = [];
  for (let firstIndex = 0; firstIndex < signals.length; firstIndex += 1) {
    for (let secondIndex = firstIndex + 1; secondIndex < signals.length; secondIndex += 1) {
      const first = signals[firstIndex];
      const second = signals[secondIndex];
      if (first.group && second.group && first.group === second.group) continue;

      const firstLeg = parlayLeg(first);
      const secondLeg = parlayLeg(second);
      const hasOdds = firstLeg.odds > 1 && secondLeg.odds > 1;
      const combinedOdds = hasOdds ? firstLeg.odds * secondLeg.odds : null;
      const combinedProbability = firstLeg.probability * secondLeg.probability * 0.85;
      const expectedValue = hasOdds ? combinedProbability * combinedOdds - 1 : null;
      combos.push({
        first: firstLeg,
        second: secondLeg,
        combinedOdds,
        combinedProbability,
        expectedValue,
        qualified: false
      });
    }
  }
  return combos.sort((left, right) =>
    right.combinedProbability - left.combinedProbability
    || Number(right.expectedValue ?? -Infinity) - Number(left.expectedValue ?? -Infinity)
  );
}

function parlayLeg(signal) {
  return {
    signal,
    matchLabel: `${signal.teamAZh} vs ${signal.teamBZh}`,
    pickLabel: signal.preferredSide === "D" ? "平局" : `${signal.preferredOutcome}胜`,
    odds: Number(signal.sportsbookOdds) > 1 ? Number(signal.sportsbookOdds) : null,
    probability: Number(signal.probability[signal.preferredSide])
  };
}

function resultDecision(signal) {
  const pick = resultPickLabel(signal);
  if (signal.signal === "RESEARCH") {
    return `本场精选，明确看好${pick}`;
  }
  if (signal.signal === "WATCH") return `预测${pick}，但优势不够，不列入精选`;
  if (signal.signal === "INFO") return `预测${pick}，但资料不足，不列入精选`;
  return `预测${pick}，但回报不合算，不列入精选`;
}

function resultPickLabel(signal) {
  if (signal.preferredSide === "D") return "双方战平";
  return `${signal.preferredOutcome}获胜`;
}

function plainAgreement(signal) {
  const agreement = Number(signal.sourceAgreement);
  const sourceCount = Number(signal.sourceCount);
  if (sourceCount >= 2 && agreement === sourceCount) return "很稳";
  if (agreement >= 2) return "较稳";
  return "一般";
}

function totalsDirection(totals) {
  if (totals.direction === "OVER") return "偏大 2.5";
  if (totals.direction === "UNDER") return "偏小 2.5";
  return "方向不明确";
}

function formatBeijingTime(value) {
  if (!value) return "暂无";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date(value));
}

function oddsCheckTime(snapshot) {
  return formatBeijingTime(
    snapshot.sourceStatus?.lyihub?.oddsCheckedAt
    ?? snapshot.sourceStatus?.lyihub?.generatedAt
    ?? snapshot.generatedAt
  );
}

function formatPercent(value) {
  return value === null || value === undefined || !Number.isFinite(Number(value))
    ? "暂无"
    : `${(Number(value) * 100).toFixed(1)}%`;
}

function formatSignedPercent(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "暂无";
  const number = Number(value) * 100;
  return `${number >= 0 ? "+" : ""}${number.toFixed(1)}%`;
}

function formatOdds(value) {
  return value === null || value === undefined || !Number.isFinite(Number(value))
    ? "暂无"
    : Number(value).toFixed(2);
}

function statusLabel(signal) {
  if (signal.status === "live") return "进行中";
  if (signal.status === "finished") return "已结束";
  return "未开赛";
}

function actualResult(signal) {
  if (!signal.score) return "待确认";
  if (signal.score.team_a > signal.score.team_b) return `${signal.teamAZh}获胜`;
  if (signal.score.team_a < signal.score.team_b) return `${signal.teamBZh}获胜`;
  return "平局";
}

function formatActualScore(signal) {
  if (!signal.score) return "待确认";
  return `${signal.teamAZh} ${signal.score.team_a}-${signal.score.team_b} ${signal.teamBZh}`;
}

function actualTotalsLabel(signal, line) {
  if (!signal.score) return "待确认";
  const total = Number(signal.score.team_a) + Number(signal.score.team_b);
  return `${total > line ? `大 ${line}` : `小 ${line}`}（共 ${total} 球）`;
}

function dynamicSummary(signal) {
  const parts = [];
  const homeRisk = signal.dynamics?.teamA?.risks?.[0];
  const awayRisk = signal.dynamics?.teamB?.risks?.[0];
  if (homeRisk) parts.push(`${signal.teamAZh}：${homeRisk}`);
  if (awayRisk) parts.push(`${signal.teamBZh}：${awayRisk}`);
  return parts.join("；") || "暂无新增动态";
}

function cardFooter(signals) {
  const polymarketUrl = signals.find((signal) => signal.polymarket?.eventUrl)?.polymarket?.eventUrl
    ?? "https://polymarket.com/sports/soccer";
  const aiAnalysisUrl = signals.find((signal) => signal.lyihub?.sourceUrl)?.lyihub?.sourceUrl
    ?? "https://worldcup.lyihub.com/";
  return {
    tag: "action",
    actions: [
      {
        tag: "button",
        text: { tag: "plain_text", content: "查看 Polymarket" },
        type: "primary",
        url: polymarketUrl
      },
      {
        tag: "button",
        text: { tag: "plain_text", content: "查看 AI 分析" },
        type: "default",
        url: aiAnalysisUrl
      }
    ]
  };
}

function dailyNewMatchesElement(signals) {
  if (signals.length === 0) return markdownElement("**每日新赛事：** 暂无");
  const rows = signals.map((signal, index) =>
    `${index + 1}. ${formatBeijingTime(signal.kickoffAt)} ${signal.teamAZh} 对阵 ${signal.teamBZh} · ${statusLabel(signal)}`
  );
  return markdownElement([
    "**每日新赛事（北京时间 / 国际足联官方赛程）**",
    ...rows
  ].join("\n"));
}

function sortByReferenceOdds(signals) {
  return [...signals].sort((left, right) => {
    const leftOdds = Number(left.sportsbookOdds);
    const rightOdds = Number(right.sportsbookOdds);
    const leftRank = Number.isFinite(leftOdds) && leftOdds > 1 ? leftOdds : Infinity;
    const rightRank = Number.isFinite(rightOdds) && rightOdds > 1 ? rightOdds : Infinity;
    return leftRank - rightRank
      || new Date(left.kickoffAt) - new Date(right.kickoffAt);
  });
}

function selectResultPredictionSignals(signals, referenceTime, scope, batchKey) {
  return selectSignals(signals, referenceTime, scope, batchKey)
    .filter((signal) => signal.status === "upcoming");
}

function todaySignals(signals, referenceTime) {
  const referenceKey = beijingDateKey(referenceTime ?? new Date());
  return signals
    .filter((signal) => beijingDateKey(signal.kickoffAt) === referenceKey)
    .sort((left, right) => new Date(left.kickoffAt) - new Date(right.kickoffAt));
}

function selectSignals(signals, referenceTime, scope, batchKey = null) {
  if (scope === "upcoming") {
    return signals
      .filter((signal) => signal.status === "upcoming")
      .sort((left, right) => new Date(left.kickoffAt) - new Date(right.kickoffAt));
  }
  if (scope === "batch") {
    const window = buildBatchWindow(referenceTime, batchKey);
    return signals
      .filter((signal) => signal.status === "upcoming")
      .filter((signal) => {
        const kickoff = new Date(signal.kickoffAt).getTime();
        return Number.isFinite(kickoff)
          && kickoff >= window.start
          && kickoff < window.end
          && kickoff >= Date.now();
      })
      .sort((left, right) => new Date(left.kickoffAt) - new Date(right.kickoffAt));
  }
  return todaySignals(signals, referenceTime);
}

function buildBatchWindow(referenceTime, batchKey) {
  const dayKey = beijingDateKey(referenceTime ?? new Date());
  const start = new Date(`${dayKey}T00:00:00+08:00`).getTime();
  const offsetHours = batchKey === "00" ? 0 : batchKey === "08" ? 8 : 16;
  return {
    start: start + offsetHours * 60 * 60 * 1000,
    end: start + (offsetHours + 8) * 60 * 60 * 1000
  };
}

function beijingDateKey(value) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(new Date(value));
}

function emptyTodayElement() {
  return markdownElement("**今天没有 FIFA 官方世界杯比赛。**");
}
