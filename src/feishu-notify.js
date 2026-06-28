import { loadEnvFile } from "./env.js";
import { sendFeishuWebhook } from "./feishu.js";

loadEnvFile();

const title = process.argv[2] ?? "World Cup auto push failed";
const summary = process.argv[3] ?? "Check the GitHub Actions run logs.";
const runUrl = process.env.GITHUB_RUN_URL ?? "";

const lines = [
  title,
  summary,
  runUrl ? `Run: ${runUrl}` : null
].filter(Boolean);

await sendFeishuWebhook({
  webhookUrl: process.env.FEISHU_WEBHOOK_URL,
  secret: process.env.FEISHU_BOT_SECRET,
  payload: {
    msg_type: "text",
    content: {
      text: lines.join("\n")
    }
  }
});

console.log("Feishu failure notification sent.");
