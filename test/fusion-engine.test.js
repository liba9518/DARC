import test from "node:test";
import assert from "node:assert/strict";
import { buildFusionSignal } from "../src/fusion-engine.js";

test("market prices do not leak into independent model probability", () => {
  const match = baseMatch();
  const first = buildFusionSignal(match, {
    hfPrediction: hfPrediction(),
    polymarket: polymarket(0.95),
    policy: policy()
  });
  const second = buildFusionSignal(match, {
    hfPrediction: hfPrediction(),
    polymarket: polymarket(0.20),
    policy: policy()
  });

  assert.deepEqual(first.probability, second.probability);
  assert.equal(first.signal, "RESEARCH");
  assert.ok(first.expectedValue >= 0.08);
});

test("missing odds cannot produce a research signal", () => {
  const match = { ...baseMatch(), hadOdds: null, oddsProbability: null };
  const signal = buildFusionSignal(match, {
    hfPrediction: hfPrediction(),
    polymarket: polymarket(0.20),
    policy: policy()
  });
  assert.equal(signal.signal, "INFO");
  assert.equal(signal.recommendedStakeFraction, 0);
});

function baseMatch() {
  return {
    matchId: "1",
    kickoffAt: "2026-06-21T12:00:00Z",
    stage: "First Stage",
    group: "Group G",
    teamA: "Japan",
    teamB: "Tunisia",
    teamAZh: "日本",
    teamBZh: "突尼斯",
    status: "upcoming",
    score: null,
    weather: null,
    dynamics: {},
    modelProbability: { H: 0.70, D: 0.20, A: 0.10 },
    modelCalibrationMatches: 40,
    hadOdds: { H: 2.00, D: 3.20, A: 4.50 },
    oddsProbability: { H: 0.50, D: 0.28, A: 0.22 },
    comments: {},
    sourceUrl: null
  };
}

function hfPrediction() {
  return {
    probability: { H: 0.60, D: 0.25, A: 0.15 },
    expectedGoals: { H: 1.6, A: 0.8 }
  };
}

function polymarket(homePrice) {
  return {
    matched: true,
    probability: { H: homePrice, D: 0.25, A: 1 - homePrice - 0.25 },
    markets: {}
  };
}

function policy() {
  return {
    modelWeights: { lyihub: 0.7, huggingface: 0.3 },
    minProbabilityEdge: 0.03,
    minExpectedValue: 0.08,
    watchExpectedValue: 0.03,
    maxDisagreement: 0.12,
    minModelSources: 2,
    minAgreement: 2,
    minCalibrationMatches: 30,
    kellyFraction: 0.25,
    maxStakeFraction: 0.01
  };
}
