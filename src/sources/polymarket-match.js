import { normalizeName } from "../team-data.js";

export async function collectPolymarketMatch(client, match) {
  const query = `${match.teamA} ${match.teamB}`;
  const searchResults = await client.search(query, {
    events_status: "active",
    limit_per_type: 20
  });

  const kickoffDate = String(match.kickoffAt).slice(0, 10);
  const event = findMatchEvent(searchResults.events ?? [], match.teamA, match.teamB, kickoffDate);
  if (!event) {
    return {
      source: "polymarket",
      matched: false,
      query,
      probability: null,
      markets: {}
    };
  }

  const mappedMarkets = {
    H: findOutcomeMarket(event.markets, match.teamA, "win"),
    D: findOutcomeMarket(event.markets, null, "draw"),
    A: findOutcomeMarket(event.markets, match.teamB, "win")
  };

  const markets = {};
  for (const side of ["H", "D", "A"]) {
    const market = mappedMarkets[side];
    if (!market) {
      continue;
    }
    markets[side] = await hydrateMarketPrice(client, market);
  }

  const rawProbability = Object.fromEntries(
    ["H", "D", "A"].map((side) => [side, markets[side]?.price ?? null])
  );
  const probability = normalizeAvailableProbability(rawProbability);

  return {
    source: "polymarket",
    matched: Boolean(probability),
    query,
    eventTitle: event.title,
    eventSlug: event.slug,
    eventUrl: `https://polymarket.com/event/${event.slug}`,
    rawProbability,
    probability,
    markets
  };
}

function findMatchEvent(events, teamA, teamB, kickoffDate) {
  const normalizedA = normalizeName(teamA);
  const normalizedB = normalizeName(teamB);

  return [...events]
    .filter((event) => {
      const text = normalizeName(`${event.title} ${event.slug}`);
      return text.includes(normalizedA) && text.includes(normalizedB);
    })
    .sort((left, right) => {
      const leftDateMatch = String(left.slug).includes(kickoffDate) ? 1 : 0;
      const rightDateMatch = String(right.slug).includes(kickoffDate) ? 1 : 0;
      return rightDateMatch - leftDateMatch;
    })[0] ?? null;
}

function findOutcomeMarket(markets = [], team, type) {
  if (type === "draw") {
    return markets.find((market) => normalizeName(market.question).includes("end in a draw")) ?? null;
  }

  const normalizedTeam = normalizeName(team);
  return markets.find((market) => {
    const question = normalizeName(market.question);
    return question.startsWith(`will ${normalizedTeam} win `);
  }) ?? null;
}

async function hydrateMarketPrice(client, market) {
  const outcomes = parseArray(market.outcomes);
  const prices = parseArray(market.outcomePrices);
  const tokenIds = parseArray(market.clobTokenIds);
  const yesIndex = outcomes.findIndex((outcome) => normalizeName(outcome) === "yes");
  const tokenId = yesIndex >= 0 ? tokenIds[yesIndex] : null;
  const gammaPrice = toProbability(yesIndex >= 0 ? prices[yesIndex] : null);

  let midpoint = null;
  let spread = null;
  if (tokenId) {
    const [midpointResult, spreadResult] = await Promise.all([
      client.getMidpoint(tokenId).catch(() => null),
      client.getSpread(tokenId).catch(() => null)
    ]);
    midpoint = toProbability(midpointResult?.mid_price);
    spread = toProbability(spreadResult?.spread);
  }

  return {
    question: market.question,
    slug: market.slug,
    url: `https://polymarket.com/market/${market.slug}`,
    tokenId,
    price: midpoint ?? gammaPrice,
    midpoint,
    gammaPrice,
    spread
  };
}

function normalizeAvailableProbability(probabilities) {
  if (Object.values(probabilities).some((value) => value === null)) {
    return null;
  }

  const total = Object.values(probabilities).reduce((sum, value) => sum + value, 0);
  if (!total) {
    return null;
  }

  return Object.fromEntries(
    Object.entries(probabilities).map(([key, value]) => [key, round(value / total, 4)])
  );
}

function parseArray(value) {
  if (Array.isArray(value)) {
    return value;
  }
  if (typeof value !== "string" || !value.trim()) {
    return [];
  }
  try {
    return JSON.parse(value);
  } catch {
    return [];
  }
}

function toProbability(value) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 && number <= 1 ? number : null;
}

function round(value, decimals) {
  return Number(Number(value).toFixed(decimals));
}
