import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import {
  buildFeishuResultCard,
  buildFeishuResultParlayCard,
  buildFeishuScoreCard,
  buildFeishuTotalsCard
} from "./feishu.js";

const inputPath = resolve(process.argv[2] ?? "data/fusion-signals.json");
const outputPath = resolve(process.argv[3] ?? "data/feishu-result-card.json");
const scoreOutputPath = resolve(process.argv[4] ?? "data/feishu-score-card.json");
const totalsOutputPath = resolve(process.argv[5] ?? "data/feishu-totals-card.json");
const parlayOutputPath = resolve(process.argv[6] ?? "data/feishu-result-parlay-card.json");
const snapshot = JSON.parse(readFileSync(inputPath, "utf8"));
const resultCard = buildFeishuResultCard(snapshot);
const scoreCard = buildFeishuScoreCard(snapshot);
const totalsCard = buildFeishuTotalsCard(snapshot);
const parlayCard = buildFeishuResultParlayCard(snapshot);

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(outputPath, `${JSON.stringify(resultCard, null, 2)}\n`, "utf8");
writeFileSync(scoreOutputPath, `${JSON.stringify(scoreCard, null, 2)}\n`, "utf8");
writeFileSync(totalsOutputPath, `${JSON.stringify(totalsCard, null, 2)}\n`, "utf8");
writeFileSync(parlayOutputPath, `${JSON.stringify(parlayCard, null, 2)}\n`, "utf8");

console.log(`Saved result card preview to ${outputPath}`);
console.log(`Saved score card preview to ${scoreOutputPath}`);
console.log(`Saved totals card preview to ${totalsOutputPath}`);
console.log(`Saved result parlay card preview to ${parlayOutputPath}`);
