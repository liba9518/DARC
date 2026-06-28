import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { PolymarketClient } from "./polymarket.js";
import { WORLD_CUP_QUERIES, collectWorldCupMarkets } from "./world-cup-markets.js";

const outputPath = resolve(process.argv[2] ?? "data/polymarket-worldcup-markets.json");
const queries = process.argv.slice(3);
const client = new PolymarketClient();

const snapshot = await collectWorldCupMarkets(client, {
  queries: queries.length > 0 ? queries : WORLD_CUP_QUERIES
});

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(outputPath, `${JSON.stringify(snapshot, null, 2)}\n`, "utf8");

console.log(`Saved ${snapshot.marketCount} World Cup markets to ${outputPath}`);
