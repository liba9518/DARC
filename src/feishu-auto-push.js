import { spawn } from "node:child_process";
import { resolve } from "node:path";

const snapshotPath = resolve(process.argv[2] ?? "data/fusion-signals.json");
const lookaheadHours = Number(process.argv[3] ?? 48);
const maxMatches = Number(process.argv[4] ?? 20);
const batchKey = process.argv[5] ?? inferBatchKey(new Date());

await runNode([
  resolve("src/fusion-snapshot.js"),
  snapshotPath,
  String(lookaheadHours),
  String(maxMatches)
]);

await runNode([
  resolve("src/feishu-push-on-odds-change.js"),
  snapshotPath,
  "data/last-pushed-odds.json",
  "data/feishu-push-progress.json",
  batchKey
]);

console.log(`Auto push completed for Beijing batch ${batchKey}.`);

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
        rejectRun(new Error(`Command exited with code ${code}`));
      }
    });
  });
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
