import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { analyzeEdges, summarizeEdges } from "./edge-engine.js";

const snapshotPath = resolve(process.argv[2] ?? "data/polymarket-worldcup-markets.json");
const predictionsPath = resolve(process.argv[3] ?? "predictions/worldcup.example.json");
const bankroll = Number(process.argv[4] ?? process.env.BANKROLL ?? 1000);
const outputPath = resolve(process.argv[5] ?? "data/worldcup-trade-plan.json");
const policyPath = resolve(process.argv[6] ?? "config/risk-policy.json");

const snapshot = JSON.parse(readFileSync(snapshotPath, "utf8"));
const predictions = JSON.parse(readFileSync(predictionsPath, "utf8"));
const policy = JSON.parse(readFileSync(policyPath, "utf8"));

const decisions = analyzeEdges(snapshot, predictions, { ...policy, bankroll });
const summary = summarizeEdges(decisions);
const orders = buildOrderPlan(summary.topBuys, { bankroll, policy });
const plan = {
  generatedAt: new Date().toISOString(),
  sourceSnapshot: snapshotPath,
  predictions: predictionsPath,
  policy: policyPath,
  bankroll,
  dryRun: policy.dryRun !== false,
  requireManualConfirmation: policy.requireManualConfirmation !== false,
  status: "REVIEW_ONLY",
  warning: "This file is an order plan, not an execution instruction. Review each order manually before trading.",
  summary: {
    buySignals: summary.buy,
    watchSignals: summary.watch,
    skipSignals: summary.skip,
    plannedOrders: orders.length,
    plannedStake: round(orders.reduce((sum, order) => sum + order.stake, 0), 2),
    plannedStakeFraction: round(orders.reduce((sum, order) => sum + order.stake, 0) / bankroll, 4)
  },
  orders
};

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(outputPath, `${JSON.stringify(plan, null, 2)}\n`, "utf8");

console.log(`Signals: ${summary.buy} buy, ${summary.watch} watch, ${summary.skip} skip`);
console.log(`Planned orders: ${orders.length}`);
console.log(`Planned stake: ${plan.summary.plannedStake} (${formatPercent(plan.summary.plannedStakeFraction)} bankroll)`);
console.log(`Saved review-only plan to ${outputPath}`);

function buildOrderPlan(decisions, { bankroll, policy }) {
  const maxOrders = Math.max(0, Number(policy.maxOrdersPerPlan ?? 8));
  const maxPlanStake = bankroll * Number(policy.maxPlanStakeFraction ?? 0.12);
  const slippageCap = Number(policy.slippageCap ?? 0.01);
  const tickSize = Number(policy.tickSize ?? 0.01);
  const orders = [];
  let plannedStake = 0;

  for (const decision of decisions) {
    if (orders.length >= maxOrders) {
      break;
    }

    const marketPrice = Number(decision.marketPrice);
    const modelProbability = Number(decision.modelProbability);
    if (!Number.isFinite(marketPrice) || marketPrice <= 0 || !Number.isFinite(modelProbability)) {
      continue;
    }

    const edgeCapPrice = modelProbability - Number(policy.minEdge ?? 0.03);
    const slippageCapPrice = marketPrice + slippageCap;
    const maxPrice = roundDownToTick(Math.min(edgeCapPrice, slippageCapPrice), tickSize);
    if (maxPrice <= 0 || maxPrice >= 1) {
      continue;
    }

    const remainingPlanStake = maxPlanStake - plannedStake;
    const stake = round(Math.min(decision.recommendedStake, remainingPlanStake), 2);
    if (stake <= 0) {
      break;
    }

    const size = round(stake / maxPrice, 4);
    plannedStake += stake;

    orders.push({
      action: "BUY",
      orderType: "LIMIT_REVIEW_ONLY",
      marketSlug: decision.marketSlug,
      marketQuestion: decision.marketQuestion,
      marketUrl: decision.marketUrl,
      outcome: decision.outcome,
      tokenId: decision.tokenId,
      marketPrice,
      modelProbability,
      edge: decision.edge,
      roi: decision.roi,
      maxPrice,
      size,
      stake,
      stakeFraction: round(stake / bankroll, 4),
      guardrails: {
        dryRun: policy.dryRun !== false,
        requireManualConfirmation: policy.requireManualConfirmation !== false,
        maxPriceFormula: "min(modelProbability - minEdge, marketPrice + slippageCap)"
      }
    });
  }

  return orders;
}

function roundDownToTick(value, tickSize) {
  return round(Math.floor(value / tickSize) * tickSize, 4);
}

function round(value, decimals) {
  if (!Number.isFinite(value)) {
    return null;
  }

  return Number(value.toFixed(decimals));
}

function formatPercent(value) {
  return `${(Number(value) * 100).toFixed(1)}%`;
}
