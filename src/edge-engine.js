const DEFAULT_RULES = {
  minEdge: 0.03,
  minRoi: 0.08,
  maxSpread: 0.08,
  minVolume: 0,
  kellyFraction: 0.25,
  maxStakeFraction: 0.03
};

export function analyzeEdges(snapshot, predictions = {}, options = {}) {
  const rules = {
    ...DEFAULT_RULES,
    ...options
  };
  const bankroll = parsePositiveNumber(options.bankroll, 1000);
  const decisions = [];

  for (const market of snapshot.markets ?? []) {
    for (const outcome of market.outcomes ?? []) {
      const modelProbability = findPrediction(predictions, market, outcome);
      decisions.push(analyzeOutcome({ market, outcome, modelProbability, bankroll, rules }));
    }
  }

  return decisions.sort((left, right) => {
    if (left.action !== right.action) {
      return left.action === "BUY" ? -1 : 1;
    }
    return Number(right.score ?? -Infinity) - Number(left.score ?? -Infinity);
  });
}

export function summarizeEdges(decisions) {
  const buy = decisions.filter((decision) => decision.action === "BUY");
  const watch = decisions.filter((decision) => decision.action === "WATCH");
  const skip = decisions.filter((decision) => decision.action === "SKIP");

  return {
    total: decisions.length,
    buy: buy.length,
    watch: watch.length,
    skip: skip.length,
    topBuys: buy.slice(0, 20)
  };
}

function analyzeOutcome({ market, outcome, modelProbability, bankroll, rules }) {
  const price = parseProbability(outcome.impliedProbability);
  const spread = parseNullableNumber(outcome.spread);
  const volume = parseNullableNumber(market.volumeNum ?? market.volume) ?? 0;
  const reasons = [];

  if (modelProbability === null) {
    reasons.push("missing model probability");
  }
  if (price === null) {
    reasons.push("missing market price");
  }
  if (market.closed === true || market.active === false) {
    reasons.push("market is not active");
  }
  if (spread !== null && spread > rules.maxSpread) {
    reasons.push(`spread ${formatPercent(spread)} > ${formatPercent(rules.maxSpread)}`);
  }
  if (volume < rules.minVolume) {
    reasons.push(`volume ${volume} < ${rules.minVolume}`);
  }

  const edge = modelProbability !== null && price !== null ? round(modelProbability - price, 4) : null;
  const roi = edge !== null && price > 0 ? round(edge / price, 4) : null;
  const fullKelly = edge !== null && price < 1 ? Math.max(0, edge / (1 - price)) : 0;
  const cappedKelly = Math.min(fullKelly * rules.kellyFraction, rules.maxStakeFraction);
  const stake = round(bankroll * cappedKelly, 2);

  if (edge !== null && edge < rules.minEdge) {
    reasons.push(`edge ${formatPercent(edge)} < ${formatPercent(rules.minEdge)}`);
  }
  if (roi !== null && roi < rules.minRoi) {
    reasons.push(`roi ${formatPercent(roi)} < ${formatPercent(rules.minRoi)}`);
  }
  if (stake <= 0) {
    reasons.push("kelly stake is zero");
  }

  const action = reasons.length === 0 ? "BUY" : edge !== null && edge > 0 ? "WATCH" : "SKIP";

  return {
    action,
    score: edge !== null && roi !== null ? round(edge * 100 + roi, 4) : null,
    marketSlug: market.slug,
    marketQuestion: market.question,
    marketUrl: market.url,
    outcome: outcome.name,
    tokenId: outcome.tokenId,
    marketPrice: price,
    modelProbability,
    edge,
    roi,
    spread,
    volume,
    fullKelly: round(fullKelly, 4),
    recommendedStakeFraction: round(cappedKelly, 4),
    recommendedStake: stake,
    reasons
  };
}

function findPrediction(predictions, market, outcome) {
  const marketKeys = [
    market.slug,
    market.question,
    market.id
  ].filter(Boolean);

  const outcomeKeys = [
    outcome.name,
    outcome.tokenId
  ].filter(Boolean);

  for (const marketKey of marketKeys) {
    const marketPredictions = predictions[marketKey];
    if (!marketPredictions || typeof marketPredictions !== "object") {
      continue;
    }

    for (const outcomeKey of outcomeKeys) {
      const probability = parseProbability(marketPredictions[outcomeKey]);
      if (probability !== null) {
        return probability;
      }
    }
  }

  return null;
}

function parseProbability(value) {
  const number = parseNullableNumber(value);
  if (number === null || number < 0 || number > 1) {
    return null;
  }
  return number;
}

function parsePositiveNumber(value, fallback) {
  const number = parseNullableNumber(value);
  return number !== null && number > 0 ? number : fallback;
}

function parseNullableNumber(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatPercent(value) {
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function round(value, decimals) {
  if (!Number.isFinite(value)) {
    return null;
  }

  return Number(value.toFixed(decimals));
}
