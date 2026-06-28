import test from "node:test";
import assert from "node:assert/strict";
import {
  buildFeishuResultCard,
  buildFeishuResultParlayCard,
  buildFeishuScoreCard,
  buildFeishuTotalsCard
} from "../src/feishu.js";

test("all cards keep fixed footer buttons", () => {
  const snapshot = sampleSnapshot([sampleSignal("a", "RESEARCH", "Group A")]);
  for (const build of [
    buildFeishuResultCard,
    buildFeishuScoreCard,
    buildFeishuTotalsCard,
    buildFeishuResultParlayCard
  ]) {
    const card = build(snapshot);
    assert.deepEqual(
      card.card.elements.at(-1).actions.map((action) => action.text.content),
      ["查看 Polymarket", "查看 AI 分析"]
    );
  }
});

test("result card uses the win-draw-loss title and plain Chinese copy", () => {
  const snapshot = sampleSnapshot([sampleSignal("a", "RESEARCH", "Group A")]);
  snapshot.signals[0].teamAZh = "甲队";
  snapshot.signals[0].teamBZh = "乙队";
  snapshot.signals[0].preferredOutcome = "甲队";
  const card = buildFeishuResultCard(snapshot);
  const content = card.card.elements
    .map((element) => element.text?.content ?? "")
    .join("\n");

  assert.equal(card.card.header.title.content, "世界杯胜负平预测");
  assert.equal(card.card.header.template, "purple");
  assert.match(content, /甲队 对阵 乙队/);
  assert.match(content, /【预测结果】甲队获胜/);
  assert.match(content, /【最终结论】本场精选，明确看好甲队获胜/);
  assert.doesNotMatch(content, /[A-Za-z]/);
});

test("result card starts with the Xingyao system title", () => {
  const card = buildFeishuResultCard(sampleSnapshot([sampleSignal("a", "RESEARCH", "Group A")]));
  assert.equal(card.card.elements[0].text.content, "**[星耀系统世界杯预测]**");
});

test("result card includes a daily new matches section", () => {
  const snapshot = sampleSnapshot([
    sampleSignal("a", "RESEARCH", "Group A"),
    sampleSignal("b", "WATCH", "Group B")
  ]);
  snapshot.signals[0].teamAZh = "甲队";
  snapshot.signals[0].teamBZh = "乙队";
  snapshot.signals[1].teamAZh = "丙队";
  snapshot.signals[1].teamBZh = "丁队";

  const card = buildFeishuResultCard(snapshot);
  const content = card.card.elements
    .map((element) => element.text?.content ?? "")
    .join("\n");

  assert.match(content, /每日新赛事/);
  assert.match(content, /甲队 对阵 乙队/);
  assert.match(content, /丙队 对阵 丁队/);
});

test("result card orders predictions by reference odds", () => {
  const highOdds = sampleSignal("a", "RESEARCH", "Group A");
  highOdds.teamAZh = "高赔队";
  highOdds.teamBZh = "对手甲";
  highOdds.preferredOutcome = "高赔队";
  highOdds.sportsbookOdds = 2.40;

  const lowOdds = sampleSignal("b", "RESEARCH", "Group B");
  lowOdds.teamAZh = "低赔队";
  lowOdds.teamBZh = "对手乙";
  lowOdds.preferredOutcome = "低赔队";
  lowOdds.sportsbookOdds = 1.35;

  const card = buildFeishuResultCard(sampleSnapshot([highOdds, lowOdds]));
  const content = card.card.elements
    .map((element) => element.text?.content ?? "")
    .join("\n");

  assert.ok(content.indexOf("低赔队 对阵 对手乙") < content.indexOf("高赔队 对阵 对手甲"));
});

test("result card only includes upcoming predictions", () => {
  const upcoming = sampleSignal("a", "RESEARCH", "Group A");
  upcoming.teamAZh = "UPCOMING_HOME";
  upcoming.teamBZh = "UPCOMING_AWAY";
  upcoming.preferredOutcome = "UPCOMING_HOME";

  const finished = sampleSignal("b", "RESEARCH", "Group B");
  finished.teamAZh = "FINISHED_HOME";
  finished.teamBZh = "FINISHED_AWAY";
  finished.preferredOutcome = "FINISHED_HOME";
  finished.status = "finished";
  finished.score = { team_a: 1, team_b: 0 };

  const live = sampleSignal("c", "RESEARCH", "Group C");
  live.teamAZh = "LIVE_HOME";
  live.teamBZh = "LIVE_AWAY";
  live.preferredOutcome = "LIVE_HOME";
  live.status = "live";
  live.score = { team_a: 0, team_b: 0 };

  const card = buildFeishuResultCard(sampleSnapshot([finished, live, upcoming]));
  const content = card.card.elements
    .map((element) => element.text?.content ?? "")
    .join("\n");

  assert.match(content, /UPCOMING_HOME/);
  assert.doesNotMatch(content, /FINISHED_HOME/);
  assert.doesNotMatch(content, /LIVE_HOME/);
});

test("result card today-upcoming scope only includes today's unstarted official matches", () => {
  const originalNow = Date.now;
  Date.now = () => new Date("2026-06-21T09:00:00Z").getTime();
  try {
    const todayUpcoming = sampleSignal("a", "INFO", "Group A");
    todayUpcoming.teamAZh = "TODAY_UPCOMING_HOME";
    todayUpcoming.teamBZh = "TODAY_UPCOMING_AWAY";
    todayUpcoming.kickoffAt = "2026-06-21T12:00:00Z";

    const tomorrowUpcoming = sampleSignal("b", "INFO", "Group B");
    tomorrowUpcoming.teamAZh = "TOMORROW_HOME";
    tomorrowUpcoming.teamBZh = "TOMORROW_AWAY";
    tomorrowUpcoming.kickoffAt = "2026-06-22T12:00:00Z";

    const alreadyStarted = sampleSignal("c", "INFO", "Group C");
    alreadyStarted.teamAZh = "STARTED_HOME";
    alreadyStarted.teamBZh = "STARTED_AWAY";
    alreadyStarted.kickoffAt = "2026-06-21T08:00:00Z";

    const card = buildFeishuResultCard(
      sampleSnapshot([todayUpcoming, tomorrowUpcoming, alreadyStarted]),
      { scope: "today-upcoming" }
    );
    const content = card.card.elements
      .map((element) => element.text?.content ?? "")
      .join("\n");

    assert.match(content, /TODAY_UPCOMING_HOME/);
    assert.doesNotMatch(content, /TOMORROW_HOME/);
    assert.doesNotMatch(content, /STARTED_HOME/);
  } finally {
    Date.now = originalNow;
  }
});

test("parlay card only shows combinations from two research signals", () => {
  const snapshot = sampleSnapshot([
    sampleSignal("a", "RESEARCH", "Group A"),
    sampleSignal("b", "RESEARCH", "Group B"),
    sampleSignal("c", "SKIP", "Group C")
  ]);
  const card = buildFeishuResultParlayCard(snapshot);
  const text = card.card.elements
    .filter((element) => element.tag === "div")
    .map((element) => element.text.content)
    .join("\n");

  assert.match(text, /【合格二串】/);
  assert.doesNotMatch(text, /队c胜/);
});

test("parlay card emits exactly one highest-probability featured pair as fallback", () => {
  const strongest = sampleSignal("a", "WATCH", "Group A");
  strongest.probability.H = 0.82;
  strongest.sportsbookOdds = 1.30;
  strongest.expectedValue = 0.066;

  const second = sampleSignal("b", "SKIP", "Group B");
  second.probability.H = 0.76;
  second.sportsbookOdds = 1.32;
  second.expectedValue = 0.0032;

  const weaker = sampleSignal("c", "SKIP", "Group C");
  weaker.probability.H = 0.61;
  weaker.sportsbookOdds = 1.55;
  weaker.expectedValue = -0.0545;

  const card = buildFeishuResultParlayCard(sampleSnapshot([strongest, second, weaker]));
  const text = card.card.elements
    .filter((element) => element.tag === "div")
    .map((element) => element.text.content)
    .join("\n");

  assert.equal((text.match(/【每日精选观察二串】/g) ?? []).length, 1);
  assert.match(text, /队a胜 \+ 队b胜/);
  assert.doesNotMatch(text, /队c胜/);
  assert.match(text, /未达到正期望门槛/);
});

function sampleSnapshot(signals) {
  return {
    generatedAt: "2026-06-21T09:00:00Z",
    sourceStatus: {
      fifa: { checkedAt: "2026-06-21T09:00:00Z", todayMatchCount: signals.length },
      lyihub: { oddsCheckedAt: "2026-06-21T09:00:00Z" }
    },
    signals
  };
}

function sampleSignal(id, signal, group) {
  return {
    matchId: id,
    kickoffAt: "2026-06-21T12:00:00Z",
    group,
    teamAZh: `队${id}`,
    teamBZh: `对手${id}`,
    status: "upcoming",
    score: null,
    probability: { H: 0.70, D: 0.20, A: 0.10 },
    preferredSide: "H",
    preferredOutcome: `队${id}`,
    sportsbookOdds: 1.80,
    sportsbookProbability: 0.55,
    expectedValue: 0.26,
    edge: 0.15,
    sourceAgreement: 2,
    sourceCount: 2,
    calibrationMatches: 40,
    signal,
    confidence: "MEDIUM",
    reasons: [],
    recommendedStakeFraction: 0.01,
    dynamics: {},
    huggingface: { expectedGoals: { H: 1.6, A: 0.7 } },
    polymarket: {},
    lyihub: {}
  };
}
