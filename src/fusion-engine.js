const MODEL_WEIGHTS = {
  lyihub: 0.70,
  huggingface: 0.30
};

export function buildFusionSignal(match, { hfPrediction, polymarket, policy = {} }) {
  const weights = {
    ...MODEL_WEIGHTS,
    ...(policy.modelWeights ?? {})
  };
  const sources = [
    sourceEntry("lyihub", match.modelProbability, weights.lyihub, "历史表现加权的多模型投票"),
    sourceEntry("huggingface", hfPrediction?.probability, weights.huggingface, "独立排名/进球分布模型")
  ].filter((source) => source.probability);

  const probability = weightedAverage(sources);
  const preferredSide = maxSide(probability);
  const sportsbookOdds = numericOrNull(match.hadOdds?.[preferredSide]);
  const sportsbookProbability = numericOrNull(match.oddsProbability?.[preferredSide]);
  const polymarketPrice = numericOrNull(polymarket?.probability?.[preferredSide]);
  const marketPrice = sportsbookProbability ?? polymarketPrice;
  const edge = marketPrice === null
    ? null
    : round(probability[preferredSide] - marketPrice, 4);
  const expectedValue = sportsbookOdds === null
    ? null
    : round(probability[preferredSide] * sportsbookOdds - 1, 4);
  const disagreement = sourceDisagreement(sources, preferredSide);
  const agreement = sources.filter((source) => maxSide(source.probability) === preferredSide).length;
  const spread = polymarket?.markets?.[preferredSide]?.spread ?? null;
  const calibrationMatches = Number(match.modelCalibrationMatches ?? 0);
  const assessment = assessSignal({
    edge,
    expectedValue,
    agreement,
    sourceCount: sources.length,
    disagreement,
    spread,
    calibrationMatches,
    sportsbookOdds,
    policy
  });
  const recommendedStakeFraction = calculateStakeFraction(
    probability[preferredSide],
    sportsbookOdds,
    assessment.signal,
    policy
  );

  return {
    matchId: match.matchId,
    kickoffAt: match.kickoffAt,
    stage: match.stage,
    group: match.group ?? null,
    teamA: match.teamA,
    teamB: match.teamB,
    teamAZh: match.teamAZh,
    teamBZh: match.teamBZh,
    venue: match.venue,
    status: match.status,
    score: match.score,
    official: match.official,
    weather: match.weather,
    dynamics: match.dynamics,
    probability,
    preferredSide,
    preferredOutcome: sideLabel(preferredSide, match),
    marketPrice,
    edge,
    expectedValue,
    sportsbookOdds,
    sportsbookProbability,
    polymarketPrice,
    fairOdds: probability[preferredSide] > 0
      ? round(1 / probability[preferredSide], 3)
      : null,
    spread,
    sourceCount: sources.length,
    sourceAgreement: agreement,
    disagreement,
    calibrationMatches,
    signal: assessment.signal,
    confidence: assessment.confidence,
    reasons: assessment.reasons,
    recommendedStakeFraction,
    sources,
    polymarket,
    lyihub: {
      hadOdds: match.hadOdds,
      comments: match.comments,
      subjectiveSummary: match.subjectiveSummary,
      sourceUrl: match.sourceUrl
    },
    huggingface: hfPrediction
  };
}

export function summarizeFusion(snapshot) {
  const signals = [...(snapshot.signals ?? [])].sort((left, right) => {
    const priority = { RESEARCH: 3, WATCH: 2, SKIP: 1, INFO: 0 };
    return (priority[right.signal] - priority[left.signal])
      || Number(right.expectedValue ?? -1) - Number(left.expectedValue ?? -1);
  });

  return {
    generatedAt: snapshot.generatedAt,
    counts: Object.fromEntries(
      ["RESEARCH", "WATCH", "SKIP", "INFO"].map((signal) => [
        signal,
        signals.filter((item) => item.signal === signal).length
      ])
    ),
    signals
  };
}

function sourceEntry(id, probability, weight, description) {
  return {
    id,
    weight,
    description,
    probability
  };
}

function weightedAverage(sources) {
  if (sources.length === 0) {
    return { H: 1 / 3, D: 1 / 3, A: 1 / 3 };
  }
  const totalWeight = sources.reduce((sum, source) => sum + source.weight, 0);
  const result = { H: 0, D: 0, A: 0 };

  for (const source of sources) {
    for (const side of ["H", "D", "A"]) {
      result[side] += source.probability[side] * source.weight / totalWeight;
    }
  }

  return Object.fromEntries(
    Object.entries(result).map(([key, value]) => [key, round(value, 4)])
  );
}

function sourceDisagreement(sources, side) {
  if (sources.length < 2) {
    return 1;
  }
  const values = sources.map((source) => source.probability[side]);
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance = values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length;
  return round(Math.sqrt(variance), 4);
}

function assessSignal({
  edge,
  expectedValue,
  agreement,
  sourceCount,
  disagreement,
  spread,
  calibrationMatches,
  sportsbookOdds,
  policy
}) {
  const minSources = Number(policy.minModelSources ?? 2);
  const minAgreement = Number(policy.minAgreement ?? 2);
  const maxDisagreement = Number(policy.maxDisagreement ?? 0.12);
  const maxSpread = Number(policy.maxSpread ?? 0.05);
  const minProbabilityEdge = Number(policy.minProbabilityEdge ?? 0.03);
  const minExpectedValue = Number(policy.minExpectedValue ?? 0.08);
  const watchExpectedValue = Number(policy.watchExpectedValue ?? 0.03);
  const minCalibrationMatches = Number(policy.minCalibrationMatches ?? 30);
  const reasons = [];

  if (sourceCount < minSources) reasons.push(`独立模型源少于 ${minSources} 个`);
  if (agreement < minAgreement) reasons.push("独立模型方向不一致");
  if (disagreement > maxDisagreement) reasons.push("独立模型概率分歧过大");
  if (calibrationMatches < minCalibrationMatches) reasons.push(`历史校准样本少于 ${minCalibrationMatches} 场`);
  if (spread !== null && spread > maxSpread) reasons.push(`Polymarket 价差超过 ${formatPercent(maxSpread)}`);

  if (sportsbookOdds === null || edge === null || expectedValue === null) {
    return {
      signal: "INFO",
      confidence: "LOW",
      reasons: [...reasons, "缺少完整欧盘，无法验证正期望"]
    };
  }

  const qualityPass = sourceCount >= minSources
    && agreement >= minAgreement
    && disagreement <= maxDisagreement
    && calibrationMatches >= minCalibrationMatches
    && (spread === null || spread <= maxSpread);

  if (qualityPass && edge >= minProbabilityEdge && expectedValue >= minExpectedValue) {
    return {
      signal: "RESEARCH",
      confidence: disagreement <= 0.08 ? "HIGH" : "MEDIUM",
      reasons: [
        ...reasons,
        `模型概率高于欧盘隐含概率 ${formatPercent(edge)}`,
        `理论期望收益 ${formatPercent(expectedValue)}`
      ]
    };
  }

  if (qualityPass && expectedValue >= watchExpectedValue) {
    return {
      signal: "WATCH",
      confidence: "MEDIUM",
      reasons: [...reasons, `理论期望收益 ${formatPercent(expectedValue)}，未达到下注研究阈值`]
    };
  }

  return {
    signal: "SKIP",
    confidence: "LOW",
    reasons: [
      ...reasons,
      expectedValue <= 0 ? "当前欧赔为负期望" : "正期望或模型质量未达到门槛"
    ]
  };
}

function calculateStakeFraction(probability, decimalOdds, signal, policy) {
  if (signal !== "RESEARCH" || decimalOdds === null || decimalOdds <= 1) {
    return 0;
  }
  const fullKelly = Math.max(
    0,
    (probability * decimalOdds - 1) / (decimalOdds - 1)
  );
  return round(Math.min(
    fullKelly * Number(policy.kellyFraction ?? 0.25),
    Number(policy.maxStakeFraction ?? 0.01)
  ), 4);
}

function maxSide(probability) {
  return ["H", "D", "A"].sort((left, right) => probability[right] - probability[left])[0];
}

function sideLabel(side, match) {
  if (side === "H") return match.teamAZh ?? match.teamA;
  if (side === "A") return match.teamBZh ?? match.teamB;
  return "平局";
}

function numericOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatPercent(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function round(value, decimals) {
  return Number(Number(value).toFixed(decimals));
}
