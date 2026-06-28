import { PolymarketClient } from "./polymarket.js";

const client = new PolymarketClient();
const query = process.argv.slice(2).join(" ") || "world cup";

const searchResults = await client.search(query, {
  events_status: "active",
  limit_per_type: 5
});

const events = searchResults.events ?? [];
const firstEvent = events[0];

console.log(`Search: ${query}`);
console.log(`Events found: ${events.length}`);

if (!firstEvent) {
  process.exit(0);
}

console.log(`Top event: ${firstEvent.title ?? firstEvent.slug}`);
console.log(`Slug: ${firstEvent.slug}`);

const firstMarket = firstEvent.markets?.[0];
if (!firstMarket?.slug) {
  process.exit(0);
}

const pricing = await client.getMarketPricingBySlug(firstMarket.slug);

console.log(`Market: ${pricing.market.question ?? pricing.market.slug}`);
for (const token of pricing.tokens) {
  console.log(
    [
      `- ${token.outcome ?? token.tokenId}`,
      `mid=${token.midpoint?.mid_price ?? "n/a"}`,
      `spread=${token.spread?.spread ?? "n/a"}`,
      `last=${token.lastTrade?.price ?? "n/a"}`
    ].join(" ")
  );
}
