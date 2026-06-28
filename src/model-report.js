import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const ledgerPath = resolve(process.argv[2] ?? "data/prediction-ledger.jsonl");
const snapshotPath = resolve(process.argv[3] ?? "data/fusion-signals.json");

if (!existsSync(ledgerPath)) {
  console.log("No prediction ledger found.");
  process.exit(0);
}

const snapshot = JSON.parse(readFileSync(snapshotPath, "utf8"));
const finished = new Map(
  snapshot.signals
    .filter((signal) => signal.status === "finished" && signal.score)
    .map((signal) => [signal.matchId, signal])
);
const latest = new Map();

for (const line of readFileSync(ledgerPath, "utf8").split(/\r?\n/).filter(Boolean)) {
  const entry = JSON.parse(line);
  for (const signal of entry.signals ?? []) {
    if (new Date(entry.generatedAt) >= new Date(signal.kickoffAt)) continue;
    latest.set(signal.matchId, { ...signal, generatedAt: entry.generatedAt });
  }
}

const rows = [];
for (const [matchId, prediction] of latest) {
  const result = finished.get(matchId);
  if (!result) continue;
  const actualSide = result.score.team_a > result.score.team_b
    ? "H"
    : result.score.team_a < result.score.team_b
      ? "A"
      : "D";
  const brier = ["H", "D", "A"].reduce((sum, side) =>
    sum + (prediction.probability[side] - (side === actualSide ? 1 : 0)) ** 2
  , 0);
  const roi = prediction.signal === "RESEARCH" && prediction.sportsbookOdds
    ? (prediction.preferredSide === actualSide ? prediction.sportsbookOdds - 1 : -1)
    : null;
  rows.push({ matchId, brier, roi });
}

if (rows.length === 0) {
  console.log("No settled ledger predictions found.");
  process.exit(0);
}

const brier = rows.reduce((sum, row) => sum + row.brier, 0) / rows.length;
const bets = rows.filter((row) => row.roi !== null);
const roi = bets.length > 0
  ? bets.reduce((sum, row) => sum + row.roi, 0) / bets.length
  : null;

console.log(`Settled matches: ${rows.length}`);
console.log(`Multiclass Brier score: ${brier.toFixed(4)} lower is better`);
console.log(`Research bets: ${bets.length}`);
console.log(`Flat-stake ROI: ${roi === null ? "n/a" : `${(roi * 100).toFixed(1)}%`}`);
