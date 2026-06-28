import { existsSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { spawn } from "node:child_process";

const snapshotPath = resolve(process.argv[2] ?? "data/fusion-signals.json");
const statePath = resolve(process.argv[3] ?? "data/last-pushed-odds.json");
const progressPath = resolve(process.argv[4] ?? "data/feishu-push-progress.json");
const batchKey = process.argv[5] ?? inferBatchKey(new Date());
const snapshot = JSON.parse(readFileSync(snapshotPath, "utf8"));
const pushingDateKey = beijingDateKey(snapshot.generatedAt);
const scheduleFingerprint = snapshot.sourceStatus?.fifa?.scheduleFingerprint ?? "";
const batchWindow = buildBatchWindow(snapshot.generatedAt, batchKey);
const upcomingFingerprint = buildUpcomingFingerprint(snapshot, batchWindow);
const cardSchemaVersion = "daily-upcoming-v1";
const fingerprint = [
  pushingDateKey,
  batchKey,
  scheduleFingerprint,
  upcomingFingerprint,
  cardSchemaVersion
].join("||");
const cardNames = ["result", "score", "totals", "parlay"];

validateSnapshot(snapshot);

if (!scheduleFingerprint && !upcomingFingerprint) {
  console.log("No official schedule or upcoming-match fingerprint found; skipping push.");
  process.exit(0);
}

const previous = existsSync(statePath)
  ? JSON.parse(readFileSync(statePath, "utf8"))
  : null;

if (previous?.fingerprint === fingerprint) {
  console.log("Today's upcoming World Cup strategy already pushed; skipping duplicate Feishu push.");
  process.exit(0);
}

const savedProgress = existsSync(progressPath)
  ? JSON.parse(readFileSync(progressPath, "utf8"))
  : null;
const completedCards = new Set(
  savedProgress?.fingerprint === fingerprint ? savedProgress.completedCards ?? [] : []
);

for (const cardName of cardNames) {
  if (completedCards.has(cardName)) continue;
  await runNode([
    resolve("src/feishu-push.js"),
    snapshotPath,
    cardName,
    "batch",
    batchKey
  ]);
  completedCards.add(cardName);
  writeFileSync(progressPath, `${JSON.stringify({
    fingerprint,
    completedCards: [...completedCards],
    batchKey,
    updatedAt: new Date().toISOString()
  }, null, 2)}\n`, "utf8");
}

writeFileSync(statePath, `${JSON.stringify({
  fingerprint,
  dateKey: pushingDateKey,
  scheduleFingerprint,
  upcomingFingerprint,
  cardSchemaVersion,
  batchKey,
  batchWindow,
  pushedAt: new Date().toISOString(),
  oddsCheckedAt: snapshot.sourceStatus?.lyihub?.oddsCheckedAt ?? null
}, null, 2)}\n`, "utf8");
if (existsSync(progressPath)) unlinkSync(progressPath);

console.log("Daily upcoming World Cup strategy pushed and state updated.");

function runNode(args) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(process.execPath, args, {
      cwd: process.cwd(),
      stdio: "inherit",
      env: process.env
    });
    child.on("error", rejectRun);
    child.on("exit", (code) => {
      if (code === 0) {
        resolveRun();
      } else {
        rejectRun(new Error(`Feishu push exited with code ${code}`));
      }
    });
  });
}

function validateSnapshot(value) {
  if (!value.sourceStatus?.fifa?.checkedAt) {
    throw new Error("FIFA official schedule health check is missing");
  }
  const todayKey = beijingDateKey(value.generatedAt);
  const signalCount = (value.signals ?? []).filter((signal) =>
    beijingDateKey(signal.kickoffAt) === todayKey
  ).length;
  const officialCount = Number(value.sourceStatus.fifa.todayMatchCount);
  if (signalCount !== officialCount) {
    throw new Error(`Official schedule mismatch: FIFA=${officialCount}, snapshot=${signalCount}`);
  }
  if (value.sourceStatus?.polymarket?.collectionErrors > 0) {
    throw new Error("Polymarket collection is incomplete");
  }
}

function beijingDateKey(value) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(new Date(value));
}

function buildUpcomingFingerprint(value, window) {
  return (value.signals ?? [])
    .filter((signal) => {
      if (signal.status !== "upcoming") return false;
      const kickoff = new Date(signal.kickoffAt).getTime();
      return Number.isFinite(kickoff)
        && kickoff >= window.start
        && kickoff < window.end
        && kickoff >= Date.now();
    })
    .map((signal) => [
      signal.matchId,
      signal.kickoffAt,
      signal.teamA,
      signal.teamB,
      signal.status,
      signal.score?.team_a ?? "",
      signal.score?.team_b ?? ""
    ].join(":"))
    .sort()
    .join("|");
}

function inferBatchKey(now) {
  const hour = Number(new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    hour12: false
  }).format(now));
  if (hour < 8) return "00";
  if (hour < 16) return "08";
  return "16";
}

function buildBatchWindow(referenceTime, batchKey) {
  const dayKey = beijingDateKey(referenceTime);
  const start = new Date(`${dayKey}T00:00:00+08:00`);
  const offsetHours = batchKey === "00" ? 0 : batchKey === "08" ? 8 : 16;
  const windowStart = new Date(start.getTime() + offsetHours * 60 * 60 * 1000);
  const windowEnd = new Date(windowStart.getTime() + 8 * 60 * 60 * 1000);
  return {
    start: windowStart.getTime(),
    end: windowEnd.getTime(),
    startIso: windowStart.toISOString(),
    endIso: windowEnd.toISOString()
  };
}
