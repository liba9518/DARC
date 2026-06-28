import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { summarizeFusion } from "./fusion-engine.js";

const inputPath = resolve(process.argv[2] ?? "data/fusion-signals.json");
const snapshot = JSON.parse(readFileSync(inputPath, "utf8"));
const summary = summarizeFusion(snapshot);

console.log(`Generated: ${summary.generatedAt}`);
console.log(`RESEARCH ${summary.counts.RESEARCH} | WATCH ${summary.counts.WATCH} | SKIP ${summary.counts.SKIP} | INFO ${summary.counts.INFO}`);

for (const signal of summary.signals) {
  console.log("");
  console.log(`[${signal.signal}/${signal.confidence}] ${signal.teamAZh} vs ${signal.teamBZh}`);
  console.log(`Kickoff: ${signal.kickoffAt}`);
  console.log(`Direction: ${signal.preferredOutcome}`);
  console.log(`Fusion: ${formatPercent(signal.probability[signal.preferredSide])} | Market: ${formatPercent(signal.marketPrice)} | Edge: ${formatPercent(signal.edge)}`);
  console.log(`H/D/A: ${formatPercent(signal.probability.H)} / ${formatPercent(signal.probability.D)} / ${formatPercent(signal.probability.A)}`);
  console.log(`Sources: ${signal.sourceAgreement}/${signal.sourceCount} agree | disagreement ${formatPercent(signal.disagreement)}`);
  console.log(`Reason: ${signal.reasons.join("; ")}`);
}

function formatPercent(value) {
  return value === null || value === undefined ? "n/a" : `${(Number(value) * 100).toFixed(1)}%`;
}
