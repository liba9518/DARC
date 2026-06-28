export const WORLD_CUP_QUERIES = [
  "world cup",
  "fifa world cup",
  "2026 world cup",
  "world cup winner",
  "world cup group",
  "world cup golden boot"
];

export async function collectWorldCupMarkets(client, {
  queries = WORLD_CUP_QUERIES,
  limitPerType = 10,
  maxMarkets = 80,
  includePricing = true
} = {}) {
  const eventMap = new Map();
  const marketMap = new Map();

  for (const query of queries) {
    const results = await client.search(query, {
      events_status: "active",
      limit_per_type: limitPerType
    });

    for (const event of results.events ?? []) {
      addEvent(eventMap, event, query);
      for (const market of event.markets ?? []) {
        addMarket(marketMap, market, event, query);
      }
    }

    for (const market of results.markets ?? []) {
      addMarket(marketMap, market, null, query);
    }
  }

  const markets = Array.from(marketMap.values())
    .filter(isLikelyWorldCupMarket)
    .slice(0, maxMarkets);

  const pricedMarkets = [];
  for (const market of markets) {
    if (!includePricing || !market.slug) {
      pricedMarkets.push(toMarketSnapshot(market));
      continue;
    }

    pricedMarkets.push(await getPricedMarketSnapshot(client, market));
  }

  return {
    generatedAt: new Date().toISOString(),
    source: "polymarket",
    queries,
    eventCount: eventMap.size,
    marketCount: pricedMarkets.length,
    events: Array.from(eventMap.values()).map(toEventSnapshot),
    markets: pricedMarkets
  };
}

export function summarizeSnapshot(snapshot) {
  const markets = [...(snapshot.markets ?? [])].sort((left, right) => {
    return Number(right.volumeNum ?? 0) - Number(left.volumeNum ?? 0);
  });

  return {
    generatedAt: snapshot.generatedAt,
    marketCount: snapshot.marketCount ?? markets.length,
    topMarkets: markets.slice(0, 20).map((market) => ({
      question: market.question,
      slug: market.slug,
      volume: market.volume,
      outcomes: [...(market.outcomes ?? [])]
        .sort((left, right) => Number(right.normalizedProbability ?? 0) - Number(left.normalizedProbability ?? 0))
        .map((outcome) => ({
          name: outcome.name,
          impliedProbability: outcome.impliedProbability,
          normalizedProbability: outcome.normalizedProbability,
          priceSource: outcome.priceSource
        }))
    }))
  };
}

async function getPricedMarketSnapshot(client, market) {
  try {
    const pricing = await client.getMarketPricingBySlug(market.slug);
    return toMarketSnapshot({
      ...market,
      ...pricing.market,
      pricingTokens: pricing.tokens
    });
  } catch (error) {
    return {
      ...toMarketSnapshot(market),
      pricingError: error.message
    };
  }
}

function addEvent(eventMap, event, query) {
  const key = event.slug ?? event.id ?? event.title;
  if (!key) {
    return;
  }

  const existing = eventMap.get(key);
  eventMap.set(key, {
    ...existing,
    ...event,
    matchedQueries: addMatchedQuery(existing?.matchedQueries, query)
  });
}

function addMarket(marketMap, market, event, query) {
  const key = market.slug ?? market.id ?? market.question;
  if (!key) {
    return;
  }

  const existing = marketMap.get(key);
  marketMap.set(key, {
    ...existing,
    ...market,
    eventSlug: market.eventSlug ?? event?.slug ?? existing?.eventSlug ?? null,
    eventTitle: market.eventTitle ?? event?.title ?? existing?.eventTitle ?? null,
    matchedQueries: addMatchedQuery(existing?.matchedQueries, query)
  });
}

function addMatchedQuery(existing = [], query) {
  return Array.from(new Set([...existing, query]));
}

function isLikelyWorldCupMarket(market) {
  const text = [
    market.question,
    market.title,
    market.slug,
    market.description,
    market.eventTitle,
    market.eventSlug
  ].filter(Boolean).join(" ").toLowerCase();

  return text.includes("world cup") || text.includes("fifa");
}

function toEventSnapshot(event) {
  return {
    id: event.id ?? null,
    slug: event.slug ?? null,
    title: event.title ?? event.question ?? null,
    description: event.description ?? null,
    volume: event.volume ?? event.volumeNum ?? null,
    liquidity: event.liquidity ?? event.liquidityNum ?? null,
    startDate: event.startDate ?? null,
    endDate: event.endDate ?? null,
    matchedQueries: event.matchedQueries ?? [],
    url: event.slug ? `https://polymarket.com/event/${event.slug}` : null
  };
}

function toMarketSnapshot(market) {
  const outcomes = extractOutcomeSnapshots(market);

  return {
    id: market.id ?? null,
    slug: market.slug ?? null,
    question: market.question ?? market.title ?? null,
    eventSlug: market.eventSlug ?? market.events?.[0]?.slug ?? null,
    eventTitle: market.eventTitle ?? market.events?.[0]?.title ?? null,
    description: market.description ?? null,
    category: market.category ?? null,
    active: market.active ?? null,
    closed: market.closed ?? null,
    volume: market.volume ?? market.volumeNum ?? null,
    volumeNum: parseNullableNumber(market.volumeNum ?? market.volume),
    liquidity: market.liquidity ?? market.liquidityNum ?? null,
    endDate: market.endDate ?? market.endDateIso ?? null,
    matchedQueries: market.matchedQueries ?? [],
    outcomes,
    url: market.slug ? `https://polymarket.com/market/${market.slug}` : null
  };
}

function extractOutcomeSnapshots(market) {
  const outcomeNames = market.outcomesArray ?? parseJsonField(market.outcomes) ?? [];
  const outcomePrices = market.outcomePricesArray ?? parseJsonField(market.outcomePrices) ?? [];
  const tokenIds = market.clobTokenIdsArray ?? parseJsonField(market.clobTokenIds) ?? [];
  const pricingTokens = market.pricingTokens ?? [];

  const count = Math.max(outcomeNames.length, outcomePrices.length, tokenIds.length, pricingTokens.length);
  const outcomes = [];

  for (let index = 0; index < count; index += 1) {
    const token = pricingTokens[index] ?? {};
    const directPrice = pickPrice([
      token.midpoint?.mid_price,
      token.lastTrade?.price,
      outcomePrices[index]
    ]);

    outcomes.push({
      name: token.outcome ?? outcomeNames[index] ?? null,
      tokenId: token.tokenId ?? tokenIds[index] ?? null,
      impliedProbability: directPrice.value,
      normalizedProbability: null,
      priceSource: directPrice.source,
      midpoint: parseNullableNumber(token.midpoint?.mid_price),
      spread: parseNullableNumber(token.spread?.spread),
      lastTrade: parseNullableNumber(token.lastTrade?.price)
    });
  }

  const probabilitySum = outcomes.reduce((sum, outcome) => {
    return sum + Number(outcome.impliedProbability ?? 0);
  }, 0);

  if (probabilitySum > 0) {
    for (const outcome of outcomes) {
      outcome.normalizedProbability = roundProbability(Number(outcome.impliedProbability ?? 0) / probabilitySum);
    }
  }

  return outcomes;
}

function pickPrice(values) {
  const labels = ["midpoint", "lastTrade", "market"];
  for (let index = 0; index < values.length; index += 1) {
    const parsed = parseNullableNumber(values[index]);
    if (parsed !== null) {
      return {
        value: roundProbability(parsed),
        source: labels[index]
      };
    }
  }

  return {
    value: null,
    source: null
  };
}

function parseJsonField(value) {
  if (Array.isArray(value) || value === null || value === undefined) {
    return value;
  }

  if (typeof value !== "string") {
    return value;
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return [];
  }

  try {
    return JSON.parse(trimmed);
  } catch {
    return value.includes(",") ? value.split(",").map((item) => item.trim()) : [value];
  }
}

function parseNullableNumber(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function roundProbability(value) {
  return Number.isFinite(value) ? Number(value.toFixed(4)) : null;
}
