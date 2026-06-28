import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { loadEnvFile } from "./env.js";
import {
  buildFeishuResultCard,
  buildFeishuResultParlayCard,
  buildFeishuScoreCard,
  buildFeishuTotalsCard,
  sendFeishuWebhook
} from "./feishu.js";

loadEnvFile();

const inputPath = resolve(process.argv[2] ?? "data/fusion-signals.json");
const requestedCards = new Set(
  (process.argv[3] ?? "result,score,totals,parlay").split(",").map((value) => value.trim()).filter(Boolean)
);
const scope = process.argv[4] ?? "upcoming";
const batchKey = process.argv[5] ?? null;
const snapshot = JSON.parse(readFileSync(inputPath, "utf8"));
const payloads = [
  { name: "result", payload: buildFeishuResultCard(snapshot, { scope, batchKey }) },
  { name: "score", payload: buildFeishuScoreCard(snapshot, { scope, batchKey }) },
  { name: "totals", payload: buildFeishuTotalsCard(snapshot, { scope, batchKey }) },
  { name: "parlay", payload: buildFeishuResultParlayCard(snapshot, { scope, batchKey }) }
].filter((item) => requestedCards.has(item.name));

for (let index = 0; index < payloads.length; index += 1) {
  const item = payloads[index];
  if (index > 0) {
    await sleep(2500);
  }
  const result = await sendWithRetry(item.payload);
  console.log(`Feishu ${item.name} card push succeeded: ${JSON.stringify(result)}`);
}

async function sendWithRetry(payload) {
  let lastError;
  for (let attempt = 0; attempt < 5; attempt += 1) {
    try {
      return await sendFeishuWebhook({
        webhookUrl: process.env.FEISHU_WEBHOOK_URL,
        secret: process.env.FEISHU_BOT_SECRET,
        payload
      });
    } catch (error) {
      lastError = error;
      const message = String(error.message);
      const retryable = message.includes("11232")
        || message.includes("fetch failed")
        || message.includes("ECONNRESET")
        || message.includes("ETIMEDOUT");
      if (!retryable || attempt === 4) {
        throw error;
      }
      await sleep(5000 * (attempt + 1));
    }
  }
  throw lastError;
}

function sleep(ms) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}
