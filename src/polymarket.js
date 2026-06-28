const DEFAULT_GAMMA_URL = "https://gamma-api.polymarket.com";
const DEFAULT_CLOB_URL = "https://clob.polymarket.com";
const DEFAULT_DATA_URL = "https://data-api.polymarket.com";
const DEFAULT_RELAYER_URL = "https://relayer-v2.polymarket.com";

export class PolymarketApiError extends Error {
  constructor(message, { status, url, body } = {}) {
    super(message);
    this.name = "PolymarketApiError";
    this.status = status;
    this.url = url;
    this.body = body;
  }
}

export class PolymarketClient {
  constructor({
    gammaUrl = DEFAULT_GAMMA_URL,
    clobUrl = DEFAULT_CLOB_URL,
    dataUrl = DEFAULT_DATA_URL,
    relayerUrl = DEFAULT_RELAYER_URL,
    relayerApiKey = getEnv("RELAYER_API_KEY"),
    relayerApiKeyAddress = getEnv("RELAYER_API_KEY_ADDRESS"),
    timeoutMs = 15000,
    fetchImpl = globalThis.fetch
  } = {}) {
    if (!fetchImpl) {
      throw new Error("A fetch implementation is required. Use Node.js 18+ or pass fetchImpl.");
    }

    this.gammaUrl = stripTrailingSlash(gammaUrl);
    this.clobUrl = stripTrailingSlash(clobUrl);
    this.dataUrl = stripTrailingSlash(dataUrl);
    this.relayerUrl = stripTrailingSlash(relayerUrl);
    this.relayerApiKey = relayerApiKey;
    this.relayerApiKeyAddress = relayerApiKeyAddress;
    this.timeoutMs = timeoutMs;
    this.fetch = fetchImpl;
  }

  async listEvents(params = {}) {
    return this.getGamma("/events", {
      active: true,
      closed: false,
      limit: 50,
      ...params
    });
  }

  async getEventBySlug(slug, params = {}) {
    return this.getGamma(`/events/slug/${encodeURIComponent(slug)}`, params);
  }

  async listMarkets(params = {}) {
    const markets = await this.getGamma("/markets", {
      closed: false,
      limit: 50,
      ...params
    });
    return Array.isArray(markets) ? markets.map(normalizeMarket) : markets;
  }

  async getMarketBySlug(slug, params = {}) {
    const market = await this.getGamma(`/markets/slug/${encodeURIComponent(slug)}`, params);
    return normalizeMarket(market);
  }

  async search(query, params = {}) {
    if (!query) {
      throw new Error("search query is required");
    }

    return this.getGamma("/public-search", {
      q: query,
      limit_per_type: 10,
      ...params
    });
  }

  async getOrderBook(tokenId) {
    return this.getClob("/book", { token_id: tokenId });
  }

  async getMidpoint(tokenId) {
    return this.getClob("/midpoint", { token_id: tokenId });
  }

  async getSpread(tokenId) {
    return this.getClob("/spread", { token_id: tokenId });
  }

  async getLastTradePrice(tokenId) {
    return this.getClob("/last-trade-price", { token_id: tokenId });
  }

  async getRelayerNonce({ address = this.relayerApiKeyAddress, type = "SAFE" } = {}) {
    requireAddress(address, "address");
    return this.getRelayer("/nonce", { address, type });
  }

  async getRelayPayload({ address = this.relayerApiKeyAddress, type = "SAFE" } = {}) {
    requireAddress(address, "address");
    return this.getRelayer("/relay-payload", { address, type });
  }

  async isWalletDeployed({ address = this.relayerApiKeyAddress, type = "SAFE" } = {}) {
    requireAddress(address, "address");
    return this.getRelayer("/deployed", { address, type });
  }

  async listRelayerApiKeys() {
    return this.getRelayer("/relayer/api/keys", {}, { auth: true });
  }

  async listRelayerTransactions(params = {}) {
    return this.getRelayer("/transactions", params, { auth: true });
  }

  async getRelayerTransaction(id) {
    if (!id) {
      throw new Error("transaction id is required");
    }

    return this.getRelayer("/transaction", { id });
  }

  async submitRelayerTransaction(payload) {
    validateRelayerTransaction(payload);
    return this.postRelayer("/submit", payload, {}, { auth: true });
  }

  async getMarketPricingBySlug(slug) {
    const market = await this.getMarketBySlug(slug);
    const tokenIds = market.clobTokenIdsArray ?? [];
    const outcomes = market.outcomesArray ?? [];

    const tokens = await Promise.all(
      tokenIds.map(async (tokenId, index) => {
        const [midpoint, spread, lastTrade] = await Promise.all([
          this.getMidpoint(tokenId).catch(toErrorPayload),
          this.getSpread(tokenId).catch(toErrorPayload),
          this.getLastTradePrice(tokenId).catch(toErrorPayload)
        ]);

        return {
          tokenId,
          outcome: outcomes[index] ?? null,
          midpoint,
          spread,
          lastTrade
        };
      })
    );

    return { market, tokens };
  }

  async getGamma(path, params = {}) {
    return this.request(this.gammaUrl, path, params);
  }

  async getClob(path, params = {}) {
    return this.request(this.clobUrl, path, params);
  }

  async getData(path, params = {}) {
    return this.request(this.dataUrl, path, params);
  }

  async getUserPositions(user, params = {}) {
    requireAddress(user, "user");
    return this.getData("/positions", { user, ...params });
  }

  async getUserPositionValue(user, params = {}) {
    requireAddress(user, "user");
    return this.getData("/value", { user, ...params });
  }

  async getRelayer(path, params = {}, { auth = false } = {}) {
    return this.request(this.relayerUrl, path, params, {
      headers: auth ? this.relayerAuthHeaders() : {}
    });
  }

  async postRelayer(path, body, params = {}, { auth = false } = {}) {
    return this.request(this.relayerUrl, path, params, {
      method: "POST",
      body,
      headers: auth ? this.relayerAuthHeaders() : {}
    });
  }

  relayerAuthHeaders() {
    if (!this.relayerApiKey || !this.relayerApiKeyAddress) {
      throw new Error("RELAYER_API_KEY and RELAYER_API_KEY_ADDRESS are required for this request");
    }

    return {
      RELAYER_API_KEY: this.relayerApiKey,
      RELAYER_API_KEY_ADDRESS: this.relayerApiKeyAddress
    };
  }

  async request(baseUrl, path, params = {}, init = {}) {
    const url = buildUrl(baseUrl, path, params);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    const hasJsonBody = init.body !== undefined && init.body !== null && typeof init.body !== "string";

    try {
      const response = await this.fetch(url, {
        ...init,
        method: init.method ?? "GET",
        headers: {
          accept: "application/json",
          ...(hasJsonBody ? { "content-type": "application/json" } : {}),
          ...(init.headers ?? {})
        },
        body: hasJsonBody ? JSON.stringify(init.body) : init.body,
        signal: controller.signal
      });

      const bodyText = await response.text();
      const body = parseResponseBody(bodyText);

      if (!response.ok) {
        throw new PolymarketApiError(`Polymarket API request failed with ${response.status}`, {
          status: response.status,
          url,
          body
        });
      }

      return body;
    } catch (error) {
      if (error.name === "AbortError") {
        throw new PolymarketApiError("Polymarket API request timed out", { url });
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }
}

export function normalizeMarket(market) {
  if (!market || typeof market !== "object") {
    return market;
  }

  return {
    ...market,
    outcomesArray: parseJsonField(market.outcomes),
    outcomePricesArray: parseJsonField(market.outcomePrices),
    clobTokenIdsArray: parseJsonField(market.clobTokenIds)
  };
}

function buildUrl(baseUrl, path, params) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const url = new URL(`${stripTrailingSlash(baseUrl)}${normalizedPath}`);

  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === null || value === "") {
      continue;
    }

    if (Array.isArray(value)) {
      for (const item of value) {
        if (item !== undefined && item !== null && item !== "") {
          url.searchParams.append(key, String(item));
        }
      }
      continue;
    }

    url.searchParams.set(key, String(value));
  }

  return url.toString();
}

function parseResponseBody(bodyText) {
  if (!bodyText) {
    return null;
  }

  try {
    return JSON.parse(bodyText);
  } catch {
    return bodyText;
  }
}

function parseJsonField(value) {
  if (Array.isArray(value) || value === null || value === undefined) {
    return value;
  }

  if (typeof value !== "string") {
    return value;
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return [];
  }

  if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
    try {
      return JSON.parse(trimmed);
    } catch {
      return value;
    }
  }

  return value.includes(",") ? value.split(",").map((item) => item.trim()) : value;
}

function stripTrailingSlash(value) {
  return String(value).replace(/\/+$/, "");
}

function toErrorPayload(error) {
  return {
    error: error.message,
    status: error.status ?? null
  };
}

function getEnv(name) {
  return typeof process !== "undefined" ? process.env?.[name] : undefined;
}

function requireAddress(value, fieldName) {
  if (!/^0x[a-fA-F0-9]{40}$/.test(value ?? "")) {
    throw new Error(`${fieldName} must be a 0x-prefixed Ethereum address`);
  }
}

function validateRelayerTransaction(payload) {
  if (!payload || typeof payload !== "object") {
    throw new Error("relayer transaction payload is required");
  }

  for (const field of ["from", "to", "proxyWallet"]) {
    requireAddress(payload[field], field);
  }

  for (const field of ["data", "nonce", "signature", "signatureParams", "type"]) {
    if (payload[field] === undefined || payload[field] === null || payload[field] === "") {
      throw new Error(`${field} is required`);
    }
  }

  if (!["SAFE", "PROXY"].includes(payload.type)) {
    throw new Error("type must be SAFE or PROXY");
  }
}
