import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { PolymarketClient } from "./polymarket.js";

loadEnvFile();

const client = new PolymarketClient();
const address = process.env.RELAYER_API_KEY_ADDRESS;
const type = process.argv[2] || "SAFE";

if (!address) {
  console.error("RELAYER_API_KEY_ADDRESS is required");
  process.exit(1);
}

console.log(`Relayer address owner: ${address}`);
console.log(`Wallet type: ${type}`);

const [nonce, relayPayload, deployed] = await Promise.all([
  client.getRelayerNonce({ address, type }),
  client.getRelayPayload({ address, type }),
  client.isWalletDeployed({ address, type })
]);

console.log("Nonce:", nonce);
console.log("Relay payload:", relayPayload);
console.log("Deployed:", deployed);

if (process.env.RELAYER_API_KEY && process.env.RELAYER_API_KEY !== "<your-api-key>") {
  const keys = await client.listRelayerApiKeys();
  console.log("Relayer API keys:", keys);
} else {
  console.log("Skipping authenticated key check: RELAYER_API_KEY is not configured.");
}

function loadEnvFile(path = resolve(".env")) {
  if (!existsSync(path)) {
    return;
  }

  const contents = readFileSync(path, "utf8");
  for (const line of contents.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }

    const separatorIndex = trimmed.indexOf("=");
    if (separatorIndex === -1) {
      continue;
    }

    const key = trimmed.slice(0, separatorIndex).trim();
    const value = trimmed.slice(separatorIndex + 1).trim().replace(/^["']|["']$/g, "");
    if (key && process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
}
