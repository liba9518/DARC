import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const predictionsPath = resolve(process.argv[2] ?? "predictions/worldcup.example.json");
const resultsPath = resolve(process.argv[3] ?? "results/worldcup.example.json");

const predictions = JSON.parse(readFileSync(predictionsPath, "utf8"));
const results = JSON.parse(readFileSync(resultsPath, "utf8"));
const rows = scorePredictions(predictions, results);

if (rows.length === 0) {
  console.log("No matching predictions/results found.");
  process.exit(0);
}

const meanBrier = rows.reduce((sum, row) => sum + row.brier, 0) / rows.length;
console.log(`Scored outcomes: ${rows.length}`);
console.log(`Mean Brier score: ${meanBrier.toFixed(4)} lower is better`);

for (const row of rows.sort((left, right) => right.brier - left.brier).slice(0, 20)) {
  console.log(`${row.market} | ${row.outcome} | p=${row.predicted} result=${row.actual} brier=${row.brier.toFixed(4)}`);
}

function scorePredictions(predictionsByMarket, resultsByMarket) {
  const rows = [];

  for (const [market, outcomes] of Object.entries(predictionsByMarket)) {
    const resultOutcomes = resultsByMarket[market];
    if (!resultOutcomes) {
      continue;
    }

    for (const [outcome, predicted] of Object.entries(outcomes)) {
      if (resultOutcomes[outcome] === undefined) {
        continue;
      }

      const probability = Number(predicted);
      const actual = Number(resultOutcomes[outcome]);
      if (!Number.isFinite(probability) || !Number.isFinite(actual)) {
        continue;
      }

      rows.push({
        market,
        outcome,
        predicted: probability,
        actual,
        brier: (probability - actual) ** 2
      });
    }
  }

  return rows;
}
