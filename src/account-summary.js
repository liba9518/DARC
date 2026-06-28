import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { PolymarketClient } from "./polymarket.js";

loadEnvFile();

const user = process.argv[2] ?? process.env.RELAYER_API_KEY_ADDRESS;
if (!user) {
  console.error("Usage: node src/account-summary.js 0xYourWallet");
  console.error("Or set RELAYER_API_KEY_ADDRESS in .env");
  process.exit(1);
}

const client = new PolymarketClient();
const [positions, values] = await Promise.all([
  client.getUserPositions(user, { limit: 100, sizeThreshold: 0 }),
  client.getUserPositionValue(user)
]);

const totalValue = Array.isArray(values)
  ? values.reduce((sum, row) => sum + Number(row.value ?? 0), 0)
  : Number(values?.value ?? 0);

const sortedPositions = [...(positions ?? [])].sort((left, right) => {
  return Number(right.currentValue ?? 0) - Number(left.currentValue ?? 0);
});

console.log(`User: ${user}`);
console.log(`Total position value: ${formatUsd(totalValue)}`);
console.log(`Positions: ${sortedPositions.length}`);

for (const position of sortedPositions.slice(0, 20)) {
  console.log("");
  console.log(position.title ?? position.slug ?? position.conditionId);
  console.log(`Outcome: ${position.outcome}`);
  console.log(`Size: ${position.size} | Avg: ${formatPrice(position.avgPrice)} | Current: ${formatPrice(position.curPrice)}`);
  console.log(`Value: ${formatUsd(position.currentValue)} | PnL: ${formatUsd(position.cashPnl)} (${formatPercent(position.percentPnl)})`);
}

function loadEnvFile(path = resolve(".env")) {
  if (!existsSync(path)) {
    return;
  }

  const contents = readFileSync(path, "utf8");
  for (const line of contents.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }

    const separatorIndex = trimmed.indexOf("=");
    if (separatorIndex === -1) {
      continue;
    }

    const key = trimmed.slice(0, separatorIndex).trim();
    const value = trimmed.slice(separatorIndex + 1).trim().replace(/^["']|["']$/g, "");
    if (key && process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
}

function formatUsd(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `$${number.toFixed(2)}` : "n/a";
}

function formatPrice(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(3) : "n/a";
}

function formatPercent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)}%` : "n/a";
}
