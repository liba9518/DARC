export function buildScoreStrategy(signal) {
  const expectedHome = Number(signal.huggingface?.expectedGoals?.H);
  const expectedAway = Number(signal.huggingface?.expectedGoals?.A);

  if (!Number.isFinite(expectedHome) || !Number.isFinite(expectedAway)) {
    return {
      available: false,
      bettable: false,
      reason: "缺少可用预期进球数据"
    };
  }

  const scorelines = [];
  for (let home = 0; home <= 7; home += 1) {
    for (let away = 0; away <= 7; away += 1) {
      scorelines.push({
        home,
        away,
        probability: poisson(home, expectedHome) * poisson(away, expectedAway)
      });
    }
  }

  scorelines.sort((left, right) => right.probability - left.probability);
  const top = scorelines.slice(0, 3).map((item) => ({
    ...item,
    probability: round(item.probability, 4)
  }));
  const totalGoals = expectedHome + expectedAway;

  return {
    available: true,
    bettable: false,
    betReason: "没有对应比分赔率和样本外校准，禁止给出比分下注建议",
    modelQuality: "EXPERIMENTAL",
    expectedGoals: {
      home: round(expectedHome, 2),
      away: round(expectedAway, 2),
      total: round(totalGoals, 2)
    },
    topScorelines: top,
    primaryScore: `${top[0].home}-${top[0].away}`,
    confidence: top[0].probability >= 0.16 ? "LOW" : "VERY_LOW",
    totalGoalsLean: totalGoals >= 2.75 ? "偏大" : totalGoals <= 2.15 ? "偏小" : "中性"
  };
}

export function buildTotalsStrategy(signal, { line = 2.5 } = {}) {
  const expectedHome = Number(signal.huggingface?.expectedGoals?.H);
  const expectedAway = Number(signal.huggingface?.expectedGoals?.A);

  if (!Number.isFinite(expectedHome) || !Number.isFinite(expectedAway)) {
    return {
      available: false,
      bettable: false,
      reason: "缺少可用预期进球数据"
    };
  }

  const totalLambda = expectedHome + expectedAway;
  const maxUnderGoals = Math.floor(line);
  let underProbability = 0;
  for (let goals = 0; goals <= maxUnderGoals; goals += 1) {
    underProbability += poisson(goals, totalLambda);
  }

  const overProbability = 1 - underProbability;
  const bttsYes = (1 - Math.exp(-expectedHome)) * (1 - Math.exp(-expectedAway));
  const direction = overProbability >= 0.60
    ? "OVER"
    : underProbability >= 0.60
      ? "UNDER"
      : "NEUTRAL";

  return {
    available: true,
    bettable: false,
    betReason: "没有对应大小球赔率，无法计算期望收益，禁止给出下注建议",
    modelQuality: "EXPERIMENTAL",
    line,
    direction,
    expectedTotalGoals: round(totalLambda, 2),
    overProbability: round(overProbability, 4),
    underProbability: round(underProbability, 4),
    bttsYesProbability: round(bttsYes, 4),
    goalBands: {
      zeroToOne: round(poisson(0, totalLambda) + poisson(1, totalLambda), 4),
      twoToThree: round(poisson(2, totalLambda) + poisson(3, totalLambda), 4),
      fourPlus: round(1 - [0, 1, 2, 3].reduce((sum, goals) => sum + poisson(goals, totalLambda), 0), 4)
    }
  };
}

function poisson(k, lambda) {
  return Math.exp(-lambda) * (lambda ** k) / factorial(k);
}

function factorial(value) {
  let result = 1;
  for (let index = 2; index <= value; index += 1) {
    result *= index;
  }
  return result;
}

function round(value, decimals) {
  return Number(Number(value).toFixed(decimals));
}
