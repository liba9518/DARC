import { normalizeTeamName, resolveTeam } from "../team-data.js";

const FIFA_CALENDAR_URL = "https://api.fifa.com/api/v3/calendar/matches";
const WORLD_CUP_COMPETITION_ID = "17";
const WORLD_CUP_SEASON_ID = "285023";

export async function collectFifaWorldCupSchedule({
  now = new Date(),
  lookaheadHours = 48,
  fetchImpl = globalThis.fetch
} = {}) {
  const from = startOfBeijingDay(now);
  const to = new Date(Math.max(
    from.getTime() + 24 * 60 * 60 * 1000,
    now.getTime() + lookaheadHours * 60 * 60 * 1000
  ));
  const windows = buildDailyWindows(from, to);
  const results = [];
  const urls = [];
  for (const window of windows) {
    const url = new URL(FIFA_CALENDAR_URL);
    url.searchParams.set("from", fifaDateTime(window.from));
    url.searchParams.set("to", fifaDateTime(window.to));
    url.searchParams.set("language", "en");
    url.searchParams.set("count", "500");
    urls.push(url.toString());
    results.push(...await fetchCalendarWindow(url, fetchImpl));
  }

  const uniqueResults = [...new Map(
    results.map((match) => [String(match.IdMatch), match])
  ).values()];
  const matches = uniqueResults
    .filter((match) => {
      const kickoff = new Date(match.Date);
      return kickoff >= from && kickoff <= to;
    })
    .filter((match) =>
      String(match.IdCompetition) === WORLD_CUP_COMPETITION_ID
      && String(match.IdSeason) === WORLD_CUP_SEASON_ID
    )
    .map(normalizeFifaMatch)
    .sort((left, right) => new Date(left.kickoffAt) - new Date(right.kickoffAt));

  return {
    source: "fifa-official",
    checkedAt: new Date().toISOString(),
    url: urls.join(","),
    competitionId: WORLD_CUP_COMPETITION_ID,
    seasonId: WORLD_CUP_SEASON_ID,
    matches,
    todayMatchCount: matches.filter((match) =>
      beijingDateKey(match.kickoffAt) === beijingDateKey(now)
    ).length,
    scheduleFingerprint: buildOfficialScheduleFingerprint(matches, now)
  };
}

async function fetchCalendarWindow(url, fetchImpl) {
  const response = await fetchImpl(url, {
    headers: { accept: "application/json" }
  });
  if (!response.ok) {
    throw new Error(`FIFA schedule request failed: HTTP ${response.status}`);
  }
  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error(`FIFA schedule returned invalid JSON: ${text.slice(0, 120)}`);
  }
  if (!Array.isArray(payload?.Results)) {
    throw new Error("FIFA schedule response is missing Results");
  }
  return payload.Results;
}

export function mergeOfficialSchedule(officialMatches, supplementalMatches, {
  now = new Date(),
  maxMatches = 20
} = {}) {
  const todayKey = beijingDateKey(now);
  const merged = officialMatches.map((official) => {
    const supplemental = findSupplementalMatch(official, supplementalMatches);
    return {
      ...(supplemental ?? emptySupplement()),
      matchId: official.matchId,
      supplementalMatchId: supplemental?.matchId ?? null,
      kickoffAt: official.kickoffAt,
      stage: official.stage,
      group: official.group,
      teamA: official.teamA,
      teamB: official.teamB,
      teamAZh: supplemental?.teamAZh ?? official.teamAZh,
      teamBZh: supplemental?.teamBZh ?? official.teamBZh,
      venue: official.venue ?? supplemental?.venue ?? null,
      status: official.status,
      score: official.score,
      official: {
        source: "FIFA",
        idMatch: official.matchId,
        matchNumber: official.matchNumber,
        checkedAt: official.checkedAt,
        sourceUrl: "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/scores-fixtures"
      }
    };
  });

  const today = merged.filter((match) => beijingDateKey(match.kickoffAt) === todayKey);
  const future = merged.filter((match) => beijingDateKey(match.kickoffAt) !== todayKey);
  return [...today, ...future.slice(0, Math.max(0, maxMatches - today.length))];
}

export function buildOfficialScheduleFingerprint(matches, referenceTime = new Date()) {
  const todayKey = beijingDateKey(referenceTime);
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

function normalizeFifaMatch(match) {
  const teamA = normalizeTeamName(match.Home?.ShortClubName ?? match.Home?.Abbreviation);
  const teamB = normalizeTeamName(match.Away?.ShortClubName ?? match.Away?.Abbreviation);
  const score = numericScore(match.HomeTeamScore, match.AwayTeamScore);
  return {
    matchId: String(match.IdMatch),
    kickoffAt: match.Date,
    stage: localizedDescription(match.StageName),
    group: localizedDescription(match.GroupName),
    teamA,
    teamB,
    teamAZh: resolveTeam(teamA).zh,
    teamBZh: resolveTeam(teamB).zh,
    venue: localizedDescription(match.Stadium?.Name) || null,
    status: fifaStatus(match.MatchStatus),
    score,
    matchNumber: match.MatchNumber ?? null,
    checkedAt: new Date().toISOString()
  };
}

function fifaStatus(value) {
  const status = Number(value);
  if (status === 0) return "finished";
  if (status === 1) return "upcoming";
  return "live";
}

function numericScore(home, away) {
  return Number.isFinite(Number(home)) && Number.isFinite(Number(away))
    ? { team_a: Number(home), team_b: Number(away) }
    : null;
}

function localizedDescription(values) {
  if (!Array.isArray(values)) return "";
  return values.find((value) => value?.Locale?.toLowerCase().startsWith("en"))?.Description
    ?? values[0]?.Description
    ?? "";
}

function findSupplementalMatch(official, matches) {
  return matches.find((match) =>
    match.teamA === official.teamA && match.teamB === official.teamB
  ) ?? matches.find((match) =>
    match.teamA === official.teamB && match.teamB === official.teamA
  ) ?? null;
}

function emptySupplement() {
  return {
    weather: null,
    dynamics: { teamA: {}, teamB: {} },
    modelProbability: null,
    modelCalibrationMatches: 0,
    hadOdds: null,
    oddsCheckedAt: null,
    oddsProbability: null,
    comments: {},
    subjectiveSummary: null,
    sourceUrl: null
  };
}

function startOfBeijingDay(value) {
  const key = beijingDateKey(value);
  return new Date(`${key}T00:00:00+08:00`);
}

function fifaDateTime(value) {
  return new Date(value).toISOString().replace(/\.\d{3}Z$/, "Z");
}

function buildDailyWindows(from, to) {
  const windows = [];
  let cursor = new Date(from);
  while (cursor < to) {
    const end = new Date(cursor.getTime() + 24 * 60 * 60 * 1000);
    windows.push({ from: cursor, to: end });
    cursor = end;
  }
  return windows;
}

function beijingDateKey(value) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(new Date(value));
}
