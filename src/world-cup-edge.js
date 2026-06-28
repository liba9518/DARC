import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { analyzeEdges, summarizeEdges } from "./edge-engine.js";

const snapshotPath = resolve(process.argv[2] ?? "data/polymarket-worldcup-markets.json");
const predictionsPath = resolve(process.argv[3] ?? "predictions/worldcup.example.json");
const bankroll = Number(process.argv[4] ?? process.env.BANKROLL ?? 1000);

const snapshot = JSON.parse(readFileSync(snapshotPath, "utf8"));
const predictions = JSON.parse(readFileSync(predictionsPath, "utf8"));
const decisions = analyzeEdges(snapshot, predictions, { bankroll });
const summary = summarizeEdges(decisions);

console.log(`Snapshot: ${snapshot.generatedAt}`);
console.log(`Bankroll: ${bankroll}`);
console.log(`Decisions: ${summary.buy} buy, ${summary.watch} watch, ${summary.skip} skip`);

if (summary.topBuys.length === 0) {
  console.log("");
  console.log("No BUY signals. That is useful: forcing trades is usually how edge disappears.");
}

for (const decision of summary.topBuys) {
  console.log("");
  console.log(`${decision.marketQuestion}`);
  console.log(`${decision.marketUrl}`);
  console.log(`Outcome: ${decision.outcome}`);
  console.log(`Market: ${formatPercent(decision.marketPrice)} | Model: ${formatPercent(decision.modelProbability)} | Edge: ${formatPercent(decision.edge)} | ROI: ${formatPercent(decision.roi)}`);
  console.log(`Stake: ${decision.recommendedStake} (${formatPercent(decision.recommendedStakeFraction)} bankroll)`);
}

const watchlist = decisions.filter((decision) => decision.action === "WATCH" && decision.edge > 0).slice(0, 10);
if (watchlist.length > 0) {
  console.log("");
  console.log("Watchlist:");
  for (const decision of watchlist) {
    console.log(`- ${decision.outcome} | ${decision.marketQuestion} | edge ${formatPercent(decision.edge)} | ${decision.reasons.join("; ")}`);
  }
}

function formatPercent(value) {
  if (value === null || value === undefined) {
    return "n/a";
  }

  return `${(Number(value) * 100).toFixed(1)}%`;
}
