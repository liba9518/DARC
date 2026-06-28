import test from "node:test";
import assert from "node:assert/strict";
import { collectFifaWorldCupSchedule, mergeOfficialSchedule } from "../src/sources/fifa.js";

test("FIFA schedule is filtered to the official 2026 World Cup season", async () => {
  const payload = {
    Results: [
      fifaMatch({ id: "1", status: 0, homeScore: 2, awayScore: 1 }),
      fifaMatch({ id: "2", status: 1, date: "2026-06-21T19:00:00Z" }),
      { ...fifaMatch({ id: "3", status: 1 }), IdCompetition: "999" }
    ]
  };
  const result = await collectFifaWorldCupSchedule({
    now: new Date("2026-06-21T09:00:00Z"),
    fetchImpl: async () => ({
      ok: true,
      text: async () => JSON.stringify(payload)
    })
  });

  assert.equal(result.matches.length, 2);
  assert.equal(result.matches[0].status, "finished");
  assert.deepEqual(result.matches[0].score, { team_a: 2, team_b: 1 });
  assert.equal(result.matches[1].status, "upcoming");
});

test("official matches remain present without supplemental prediction data", () => {
  const official = [{
    matchId: "400",
    kickoffAt: "2026-06-21T12:00:00Z",
    stage: "First Stage",
    group: "Group G",
    teamA: "Japan",
    teamB: "Tunisia",
    teamAZh: "日本",
    teamBZh: "突尼斯",
    venue: null,
    status: "upcoming",
    score: null,
    checkedAt: "2026-06-21T09:00:00Z"
  }];

  const merged = mergeOfficialSchedule(official, [], {
    now: new Date("2026-06-21T09:00:00Z")
  });
  assert.equal(merged.length, 1);
  assert.equal(merged[0].matchId, "400");
  assert.equal(merged[0].modelProbability, null);
});

function fifaMatch({
  id,
  status,
  date = "2026-06-21T04:00:00Z",
  homeScore = null,
  awayScore = null
}) {
  return {
    IdCompetition: "17",
    IdSeason: "285023",
    IdMatch: id,
    Date: date,
    MatchStatus: status,
    HomeTeamScore: homeScore,
    AwayTeamScore: awayScore,
    Home: { ShortClubName: "Japan", Abbreviation: "JPN" },
    Away: { ShortClubName: "Tunisia", Abbreviation: "TUN" },
    StageName: [{ Locale: "en-GB", Description: "First Stage" }],
    GroupName: [{ Locale: "en-GB", Description: "Group G" }],
    Stadium: { Name: [] }
  };
}
