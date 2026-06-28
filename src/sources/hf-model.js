import { createHash } from "node:crypto";
import { resolveTeam } from "../team-data.js";

export function predictWithHfModel(teamAName, teamBName) {
  const teamA = resolveTeam(teamAName);
  const teamB = resolveTeam(teamBName);
  const abilityA = abilityProfile(teamA.en, teamA.rank);
  const abilityB = abilityProfile(teamB.en, teamB.rank);
  const h2h = fallbackH2h(teamA.en, teamB.en, teamA.rank, teamB.rank);
  const rankEdge = (teamB.rank - teamA.rank) / 48;
  const h2hEdge = (h2h.winsA - h2h.winsB) / Math.max(h2h.played, 4);

  const xgA = clamp(
    0.36 + abilityA.attack / 76 + abilityA.midfield / 260 - abilityB.defense / 190
      + rankEdge * 0.30 + h2hEdge * 0.22,
    0.25,
    3.8
  );
  const xgB = clamp(
    0.36 + abilityB.attack / 76 + abilityB.midfield / 260 - abilityA.defense / 190
      - rankEdge * 0.30 - h2hEdge * 0.22,
    0.25,
    3.8
  );

  return {
    source: "hf-replicated-poisson",
    quality: "low",
    reason: "Replicates the public Space rank/ability/Poisson fallback; not a live exported prediction.",
    probability: poissonProbabilities(xgA, xgB),
    expectedGoals: {
      H: round(xgA, 2),
      A: round(xgB, 2)
    },
    ability: {
      H: abilityA,
      A: abilityB
    }
  };
}

function abilityProfile(team, rank) {
  const base = (55 - rank) / 54;
  return {
    attack: round(clamp(50 + base * 39 + stableInt(team, "atk", 13) - 6, 42, 97), 1),
    defense: round(clamp(50 + base * 37 + stableInt(team, "def", 13) - 6, 42, 97), 1),
    midfield: round(clamp(49 + base * 38 + stableInt(team, "mid", 15) - 7, 40, 97), 1),
    stamina: round(clamp(54 + base * 29 + stableInt(team, "sta", 15) - 7, 42, 96), 1),
    tactics: round(clamp(49 + base * 37 + stableInt(team, "tac", 13) - 6, 40, 97), 1)
  };
}

function fallbackH2h(teamA, teamB, rankA, rankB) {
  const played = 2 + stableInt(teamA, teamB, "played", 12);
  const edge = clamp(0.5 + (rankB - rankA) / 72, 0.18, 0.82);
  const draws = Math.round(played * 0.24);
  const winsA = Math.round((played - draws) * edge);
  return {
    played,
    winsA,
    winsB: played - draws - winsA,
    draws
  };
}

function poissonProbabilities(lambdaA, lambdaB, maxGoals = 8) {
  let home = 0;
  let draw = 0;
  let away = 0;
  let total = 0;

  for (let goalsA = 0; goalsA <= maxGoals; goalsA += 1) {
    const probabilityA = poisson(goalsA, lambdaA);
    for (let goalsB = 0; goalsB <= maxGoals; goalsB += 1) {
      const probability = probabilityA * poisson(goalsB, lambdaB);
      total += probability;
      if (goalsA > goalsB) {
        home += probability;
      } else if (goalsA < goalsB) {
        away += probability;
      } else {
        draw += probability;
      }
    }
  }

  return {
    H: round(home / total, 4),
    D: round(draw / total, 4),
    A: round(away / total, 4)
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

function stableInt(...args) {
  const modulo = args.pop();
  const digest = createHash("sha256").update(args.join("|"), "utf8").digest("hex");
  return Number(BigInt(`0x${digest.slice(0, 14)}`) % BigInt(modulo));
}

function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value));
}

function round(value, decimals) {
  return Number(Number(value).toFixed(decimals));
}
