import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { summarizeSnapshot } from "./world-cup-markets.js";

const inputPath = resolve(process.argv[2] ?? "data/polymarket-worldcup-markets.json");
const snapshot = JSON.parse(readFileSync(inputPath, "utf8"));
const summary = summarizeSnapshot(snapshot);

console.log(`Snapshot: ${summary.generatedAt}`);
console.log(`Markets: ${summary.marketCount}`);

for (const market of summary.topMarkets) {
  console.log("");
  console.log(market.question);
  console.log(`https://polymarket.com/market/${market.slug}`);

  for (const outcome of market.outcomes.slice(0, 8)) {
    const implied = formatPercent(outcome.impliedProbability);
    const normalized = formatPercent(outcome.normalizedProbability);
    console.log(`- ${outcome.name}: ${implied} implied, ${normalized} normalized (${outcome.priceSource ?? "no price"})`);
  }
}

function formatPercent(value) {
  if (value === null || value === undefined) {
    return "n/a";
  }

  return `${(Number(value) * 100).toFixed(1)}%`;
}
