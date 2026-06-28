import { normalizeTeamName } from "../team-data.js";

const BASE_URL = "https://worldcup.lyihub.com";
const DEFAULT_MODELS = ["deepseek", "openai", "claude", "gemini", "glm", "kimi"];

export async function collectLyihub({
  now = new Date(),
  lookaheadHours = 48,
  liveLookbackHours = 4,
  maxMatches = 12,
  includeDetails = true,
  fetchImpl = globalThis.fetch
} = {}) {
  const collectedAt = new Date().toISOString();
  const index = await fetchJson(`${BASE_URL}/data/index.json`, fetchImpl);
  const matches = Array.isArray(index.matches) ? index.matches : [];
  const modelStats = calculateModelStats(matches);
  const endTime = now.getTime() + lookaheadHours * 60 * 60 * 1000;
  const startTime = now.getTime() - liveLookbackHours * 60 * 60 * 1000;
  const todayKey = beijingDateKey(now);

  const upcoming = matches
    .filter((match) => {
      const kickoff = new Date(match.kickoff_at).getTime();
      const isToday = beijingDateKey(match.kickoff_at) === todayKey;
      const isUpcomingWindow = kickoff >= startTime && kickoff <= endTime && !hasFinalScore(match.score);
      return isToday || isUpcomingWindow;
    })
    .sort((left, right) => new Date(left.kickoff_at) - new Date(right.kickoff_at))
    .slice(0, Math.max(maxMatches, matches.filter((match) =>
      beijingDateKey(match.kickoff_at) === todayKey
    ).length));

  const enriched = [];
  for (const match of upcoming) {
    let detail = null;
    if (includeDetails && match.has_predict) {
      detail = await fetchJson(`${BASE_URL}/data/matches/${encodeURIComponent(match.match_id)}.json`, fetchImpl);
    }

    const odds = extractHadOdds(detail?.match?.odds);
    enriched.push({
      matchId: String(match.match_id),
      kickoffAt: match.kickoff_at,
      stage: match.stage,
      teamA: normalizeTeamName(match.team_a),
      teamB: normalizeTeamName(match.team_b),
      teamAZh: match.team_a,
      teamBZh: match.team_b,
      venue: match.venue,
      status: getMatchStatus(match, now),
      score: match.score ?? detail?.match?.score ?? null,
      votes: match.bets ?? { H: [], D: [], A: [] },
      resolvedVotes: resolveVotes(match),
      comments: match.comment ?? {},
      modelProbability: weightedVoteProbability(match, modelStats),
      modelCalibrationMatches: countCompletedMatches(matches),
      hadOdds: odds,
      oddsCheckedAt: odds ? collectedAt : null,
      oddsProbability: odds ? decimalOddsToProbability(odds) : null,
      weather: detail?.match?.weather ?? null,
      dynamics: extractDynamics(detail),
      subjectiveSummary: extractSubjectiveSummary(detail),
      sourceUrl: `${BASE_URL}/match.html?id=${encodeURIComponent(match.match_id)}`
    });
  }

  return {
    source: "lyihub",
    generatedAt: index.generated_at ?? new Date().toISOString(),
    oddsCheckedAt: collectedAt,
    oddsFingerprint: buildOddsFingerprint(enriched, todayKey),
    scheduleFingerprint: buildScheduleFingerprint(enriched, todayKey),
    todayMatchCount: enriched.filter((match) => beijingDateKey(match.kickoffAt) === todayKey).length,
    modelStats,
    matches: enriched
  };
}

function buildOddsFingerprint(matches, todayKey) {
  return matches
    .filter((match) => match.hadOdds && beijingDateKey(match.kickoffAt) === todayKey)
    .map((match) => [
      match.matchId,
      match.hadOdds.H,
      match.hadOdds.D,
      match.hadOdds.A
    ].join(":"))
    .sort()
    .join("|");
}

function buildScheduleFingerprint(matches, todayKey) {
  return matches
    .filter((match) => beijingDateKey(match.kickoffAt) === todayKey)
    .map((match) => [
      match.matchId,
      match.kickoffAt,
      match.teamA,
      match.teamB,
      match.status,
      match.score?.team_a ?? "",
      match.score?.team_b ?? ""
    ].join(":"))
    .sort()
    .join("|");
}

function beijingDateKey(value) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(new Date(value));
}

function getMatchStatus(match, now) {
  if (hasFinalScore(match.score)) {
    return "finished";
  }
  const kickoff = new Date(match.kickoff_at).getTime();
  return kickoff <= now.getTime() ? "live" : "upcoming";
}

export function calculateModelStats(matches) {
  const stats = Object.fromEntries(DEFAULT_MODELS.map((model) => [
    model,
    { predictions: 0, correct: 0, accuracy: 0.5, weight: 0.5 }
  ]));

  for (const match of matches) {
    if (!hasFinalScore(match.score)) {
      continue;
    }

    const result = match.score.team_a > match.score.team_b
      ? "H"
      : match.score.team_a < match.score.team_b
        ? "A"
        : "D";

    for (const model of DEFAULT_MODELS) {
      const predictedSide = inferModelSide(match, model);
      if (!predictedSide) {
        continue;
      }
      stats[model].predictions += 1;
      if (predictedSide === result) {
        stats[model].correct += 1;
      }
    }
  }

  for (const stat of Object.values(stats)) {
    stat.accuracy = stat.predictions > 0 ? round(stat.correct / stat.predictions, 4) : 0.5;
    stat.weight = round((stat.correct + 2) / (stat.predictions + 4), 4);
  }

  return stats;
}

function weightedVoteProbability(match, modelStats) {
  const scores = { H: 0.25, D: 0.25, A: 0.25 };
  let voteCount = 0;

  for (const model of DEFAULT_MODELS) {
    const side = inferModelSide(match, model);
    if (side) {
      scores[side] += modelStats[model]?.weight ?? 0.5;
      voteCount += 1;
    }
  }

  return voteCount > 0 ? normalizeProbability(scores) : null;
}

function countCompletedMatches(matches) {
  return matches.filter((match) => hasFinalScore(match.score)).length;
}

function resolveVotes(match) {
  const votes = { H: [], D: [], A: [] };
  for (const model of DEFAULT_MODELS) {
    const side = inferModelSide(match, model);
    if (side) {
      votes[side].push(model);
    }
  }
  return votes;
}

function inferModelSide(match, model) {
  const originalSide = ["H", "D", "A"].find((side) => match.bets?.[side]?.includes(model)) ?? null;
  const comment = String(match.comment?.[model] ?? "").trim();
  if (!comment) {
    return originalSide;
  }

  if (/不败|平局|打平|和局|坐和望赢/.test(comment)) {
    return originalSide;
  }

  const firstClause = comment.split(/[，。；,.;\n]/)[0];
  const hasTeamA = firstClause.includes(match.team_a);
  const hasTeamB = firstClause.includes(match.team_b);
  if (hasTeamA !== hasTeamB) {
    return hasTeamA ? "H" : "A";
  }

  return originalSide;
}

function extractHadOdds(odds = []) {
  const had = odds.find((row) => row.pool_code === "HAD");
  if (!had) {
    return null;
  }

  const result = {
    H: toPositiveNumber(had.H),
    D: toPositiveNumber(had.D),
    A: toPositiveNumber(had.A)
  };

  return Object.values(result).every(Boolean) ? result : null;
}

function decimalOddsToProbability(odds) {
  return normalizeProbability({
    H: 1 / odds.H,
    D: 1 / odds.D,
    A: 1 / odds.A
  });
}

function extractSubjectiveSummary(detail) {
  const text = findFirstString(detail, [
    "fan_subjective_prediction_md",
    "subjective_prediction_md",
    "prediction_summary"
  ]);
  if (!text) {
    return null;
  }

  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  return lines.find((line) => line.includes("最终一句话"))
    ?? lines.find((line) => line.includes("我更看好"))
    ?? lines.at(-1)
    ?? null;
}

function extractDynamics(detail) {
  const profiles = detail?.team_profiles ?? {};
  return {
    teamA: {
      advantages: arrayOfStrings(profiles.A?.["主要优势"]).slice(0, 2),
      risks: arrayOfStrings(profiles.A?.["主要风险"]).slice(0, 2),
      style: profiles.A?.["球队风格"] ?? null
    },
    teamB: {
      advantages: arrayOfStrings(profiles.B?.["主要优势"]).slice(0, 2),
      risks: arrayOfStrings(profiles.B?.["主要风险"]).slice(0, 2),
      style: profiles.B?.["球队风格"] ?? null
    }
  };
}

function arrayOfStrings(value) {
  return Array.isArray(value) ? value.filter((item) => typeof item === "string" && item.trim()) : [];
}

function findFirstString(value, keys) {
  if (!value || typeof value !== "object") {
    return null;
  }

  for (const key of keys) {
    if (typeof value[key] === "string" && value[key].trim()) {
      return value[key].trim();
    }
  }

  for (const nested of Object.values(value)) {
    const found = findFirstString(nested, keys);
    if (found) {
      return found;
    }
  }

  return null;
}

function hasFinalScore(score) {
  return Number.isFinite(score?.team_a) && Number.isFinite(score?.team_b);
}

async function fetchJson(url, fetchImpl) {
  const response = await fetchImpl(url, {
    headers: { accept: "application/json" }
  });
  if (!response.ok) {
    throw new Error(`lyihub request failed: ${response.status} ${url}`);
  }
  return response.json();
}

function normalizeProbability(probabilities) {
  const total = Object.values(probabilities).reduce((sum, value) => sum + Number(value || 0), 0);
  if (!total) {
    return { H: 1 / 3, D: 1 / 3, A: 1 / 3 };
  }

  return Object.fromEntries(
    Object.entries(probabilities).map(([key, value]) => [key, round(Number(value) / total, 4)])
  );
}

function toPositiveNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function round(value, decimals) {
  return Number(Number(value).toFixed(decimals));
}
