import { appendFileSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { buildFusionSignal } from "./fusion-engine.js";
import { PolymarketClient } from "./polymarket.js";
import { collectLyihub } from "./sources/lyihub.js";
import { predictWithHfModel } from "./sources/hf-model.js";
import { collectHfSpaceMetadata } from "./sources/hf-space.js";
import { collectPolymarketMatch } from "./sources/polymarket-match.js";
import { collectFifaWorldCupSchedule, mergeOfficialSchedule } from "./sources/fifa.js";

const outputPath = resolve(process.argv[2] ?? "data/fusion-signals.json");
const lookaheadHours = Number(process.argv[3] ?? 48);
const maxMatches = Number(process.argv[4] ?? 10);
const policyPath = resolve(process.argv[5] ?? "config/fusion-policy.json");
const policy = JSON.parse(readFileSync(policyPath, "utf8"));
const client = new PolymarketClient();

const fifa = await collectFifaWorldCupSchedule({
  lookaheadHours
});
const lyihub = await collectLyihub({
  lookaheadHours,
  maxMatches: Math.max(maxMatches, fifa.matches.length),
  includeDetails: true
});
const hfSpace = await collectHfSpaceMetadata();
const matches = mergeOfficialSchedule(fifa.matches, lyihub.matches, {
  maxMatches
});

const signals = [];
for (const match of matches) {
  const hfPrediction = predictWithHfModel(match.teamA, match.teamB);
  const polymarket = await collectPolymarketMatch(client, match);

  signals.push(buildFusionSignal(match, { hfPrediction, polymarket, policy }));
}

const snapshot = {
  generatedAt: new Date().toISOString(),
  lookaheadHours,
  policy,
  sourceStatus: {
    fifa: {
      source: fifa.source,
      checkedAt: fifa.checkedAt,
      sourceUrl: fifa.url,
      competitionId: fifa.competitionId,
      seasonId: fifa.seasonId,
      todayMatchCount: fifa.todayMatchCount,
      matchCount: fifa.matches.length,
      scheduleFingerprint: fifa.scheduleFingerprint
    },
    lyihub: {
      generatedAt: lyihub.generatedAt,
      oddsCheckedAt: lyihub.oddsCheckedAt,
      oddsFingerprint: lyihub.oddsFingerprint,
      scheduleFingerprint: fifa.scheduleFingerprint,
      todayMatchCount: fifa.todayMatchCount,
      matchCount: matches.length,
      modelStats: lyihub.modelStats
    },
    huggingface: {
      ...hfSpace,
      mode: "replicated-public-formula",
      quality: "low",
      note: "The Space does not expose a stable JSON prediction API; its public rank/ability/Poisson formula is replicated locally."
    },
    polymarket: {
      matchedMatches: signals.filter((signal) => signal.polymarket?.matched).length,
      collectionErrors: signals.filter((signal) => signal.polymarket?.error).length
    }
  },
  signals
};

mkdirSync(dirname(outputPath), { recursive: true });
const temporaryPath = `${outputPath}.tmp`;
writeFileSync(temporaryPath, `${JSON.stringify(snapshot, null, 2)}\n`, "utf8");
renameSync(temporaryPath, outputPath);
appendPredictionLedger(snapshot, resolve("data/prediction-ledger.jsonl"));

console.log(`Saved ${signals.length} fused match signals to ${outputPath}`);
console.log(`Polymarket matches: ${snapshot.sourceStatus.polymarket.matchedMatches}/${signals.length}`);

function appendPredictionLedger(value, ledgerPath) {
  const upcoming = value.signals.filter((signal) => signal.status === "upcoming");
  if (upcoming.length === 0) return;
  appendFileSync(ledgerPath, `${JSON.stringify({
    generatedAt: value.generatedAt,
    scheduleFingerprint: value.sourceStatus.fifa.scheduleFingerprint,
    signals: upcoming.map((signal) => ({
      matchId: signal.matchId,
      kickoffAt: signal.kickoffAt,
      teamA: signal.teamA,
      teamB: signal.teamB,
      probability: signal.probability,
      preferredSide: signal.preferredSide,
      sportsbookOdds: signal.sportsbookOdds,
      expectedValue: signal.expectedValue,
      signal: signal.signal
    }))
  })}\n`, "utf8");
}
