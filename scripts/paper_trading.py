"""Paper trading ledger for strategy-card follow tests.

The ledger is intentionally simulation-only: it never talks to brokers and never
places real orders. It records fractional model positions so a small test account
can follow high-priced A-share and US candidates deterministically.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PAPER_STATE_PATH = ROOT / "data" / "paper_trade_state.json"


def paper_trading_enabled() -> bool:
    return os.getenv("PAPER_TRADING_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def paper_risk_control_enabled() -> bool:
    return os.getenv("PAPER_TRADING_RISK_CONTROL_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _env_float(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


def load_paper_state() -> dict[str, Any]:
    try:
        return json.loads(PAPER_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_paper_state(state: dict[str, Any]) -> None:
    PAPER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PAPER_STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(PAPER_STATE_PATH)


def _market_config(market: str) -> tuple[str, float, str]:
    if market == "us":
        return "美股", float(os.getenv("PAPER_TRADING_US_CAPITAL", "10000")), "美元"
    if market == "kr":
        return "韩股", float(os.getenv("PAPER_TRADING_KR_CAPITAL", "10000000")), "韩元"
    return "A股", float(os.getenv("PAPER_TRADING_CN_CAPITAL", "10000")), "人民币"


def _portfolio(state: dict[str, Any], market: str) -> dict[str, Any]:
    label, capital, currency = _market_config(market)
    portfolios = state.setdefault("portfolios", {})
    portfolio = portfolios.setdefault(
        market,
        {
            "market_label": label,
            "currency": currency,
            "initial_capital": capital,
            "cash": capital,
            "positions": {},
            "trades": [],
            "last_total_value": capital,
        },
    )
    portfolio.setdefault("positions", {})
    portfolio.setdefault("trades", [])
    portfolio.setdefault("cash", float(portfolio.get("initial_capital") or capital))
    portfolio.setdefault("initial_capital", capital)
    portfolio.setdefault("currency", currency)
    portfolio.setdefault("market_label", label)
    portfolio.setdefault("last_total_value", float(portfolio.get("initial_capital") or capital))
    return portfolio


def _total_value(portfolio: dict[str, Any], prices: dict[str, float] | None = None) -> float:
    prices = prices or {}
    total = float(portfolio.get("cash") or 0)
    for code, position in (portfolio.get("positions") or {}).items():
        price = float(prices.get(code) or position.get("last_price") or position.get("avg_price") or 0)
        total += float(position.get("shares") or 0) * price
    return total


def _trade(
    portfolio: dict[str, Any],
    *,
    action: str,
    code: str,
    name: str,
    price: float,
    shares: float,
    at: datetime,
    reason: str,
) -> dict[str, Any] | None:
    if price <= 0 or abs(shares) < 1e-8:
        return None
    positions = portfolio.setdefault("positions", {})
    current = positions.setdefault(code, {"code": code, "name": name, "shares": 0.0, "avg_price": price})
    current_shares = float(current.get("shares") or 0)
    amount = shares * price
    if action == "buy":
        new_shares = current_shares + shares
        current["avg_price"] = (
            (current_shares * float(current.get("avg_price") or price) + amount) / new_shares
            if new_shares > 0
            else price
        )
        current["shares"] = new_shares
        portfolio["cash"] = float(portfolio.get("cash") or 0) - amount
    else:
        sell_shares = min(abs(shares), current_shares)
        if sell_shares <= 0:
            return None
        amount = sell_shares * price
        current["shares"] = current_shares - sell_shares
        portfolio["cash"] = float(portfolio.get("cash") or 0) + amount
        shares = sell_shares
        if float(current.get("shares") or 0) <= 1e-8:
            positions.pop(code, None)
    if code in positions:
        positions[code]["name"] = name
        positions[code]["last_price"] = price
    record = {
        "at": at.isoformat(timespec="seconds"),
        "action": action,
        "code": code,
        "name": name,
        "price": round(price, 4),
        "shares": round(shares, 6),
        "amount": round(amount, 2),
        "reason": reason,
    }
    portfolio.setdefault("trades", []).append(record)
    portfolio["trades"] = portfolio["trades"][-120:]
    return record


def rebalance_to_picks(market: str, picks: list[Any], *, dry_run: bool = False) -> dict[str, Any] | None:
    if not paper_trading_enabled() or not picks:
        return None
    state = load_paper_state()
    working_state = copy.deepcopy(state) if dry_run else state
    portfolio = _portfolio(working_state, market)
    data_date = str(getattr(picks[0], "data_date", "")) if picks else "none"
    codes = [str(getattr(pick, "code")) for pick in picks]
    signature = "|".join([data_date, *codes])
    prices = {str(getattr(pick, "code")): float(getattr(pick, "price")) for pick in picks}
    names = {str(getattr(pick, "code")): str(getattr(pick, "name")) for pick in picks}
    before_value = _total_value(portfolio, prices)
    trades: list[dict[str, Any]] = []
    at = datetime.now()

    if portfolio.get("last_rebalance_signature") != signature:
        target_codes = set(codes)
        for code, position in list((portfolio.get("positions") or {}).items()):
            if code not in target_codes:
                trade = _trade(
                    portfolio,
                    action="sell",
                    code=code,
                    name=str(position.get("name") or code),
                    price=float(position.get("last_price") or position.get("avg_price") or 0),
                    shares=float(position.get("shares") or 0),
                    at=at,
                    reason="调出精选名单",
                )
                if trade:
                    trades.append(trade)
        target_value = _total_value(portfolio, prices) / max(1, len(codes))
        for code in codes:
            price = prices[code]
            target_shares = target_value / price if price > 0 else 0
            current = (portfolio.get("positions") or {}).get(code, {})
            current_shares = float(current.get("shares") or 0)
            delta = target_shares - current_shares
            action = "buy" if delta > 0 else "sell"
            trade = _trade(
                portfolio,
                action=action,
                code=code,
                name=names.get(code, code),
                price=price,
                shares=abs(delta),
                at=at,
                reason="盘前等权模拟调仓",
            )
            if trade:
                trades.append(trade)
        portfolio["last_rebalance_signature"] = signature
        portfolio["last_rebalanced_at"] = at.isoformat(timespec="seconds")
        portfolio["last_rebalance_codes"] = codes

    after_value = _total_value(portfolio, prices)
    portfolio["last_total_value"] = after_value
    working_state["updated_at"] = at.isoformat(timespec="seconds")
    if not dry_run:
        save_paper_state(working_state)
    initial_capital = float(portfolio.get("initial_capital") or after_value or 0)
    return {
        "market": market,
        "market_label": portfolio.get("market_label"),
        "currency": portfolio.get("currency"),
        "initial_capital": round(initial_capital, 2),
        "total_value": round(after_value, 2),
        "cash": round(float(portfolio.get("cash") or 0), 2),
        "pnl": round(after_value - initial_capital, 2),
        "pnl_pct": round((after_value / initial_capital - 1) * 100, 2) if initial_capital else 0.0,
        "positions_count": len(portfolio.get("positions") or {}),
        "trades": trades,
        "changed": bool(trades),
    }


def mark_to_market(market: str, quotes: dict[str, dict[str, Any]], *, dry_run: bool = False) -> dict[str, Any] | None:
    if not paper_trading_enabled():
        return None
    state = load_paper_state()
    working_state = copy.deepcopy(state) if dry_run else state
    portfolio = _portfolio(working_state, market)
    positions = portfolio.get("positions") or {}
    if not positions:
        return None
    prices: dict[str, float] = {}
    for code, position in positions.items():
        quote = quotes.get(code) or {}
        price = float(quote.get("price") or position.get("last_price") or position.get("avg_price") or 0)
        prices[code] = price
        position["last_price"] = price
        if quote.get("name"):
            position["name"] = str(quote["name"])
    before = float(portfolio.get("last_total_value") or portfolio.get("initial_capital") or 0)
    total = _total_value(portfolio, prices)
    initial_capital = float(portfolio.get("initial_capital") or total or 0)
    portfolio["last_total_value"] = total
    portfolio["last_marked_at"] = datetime.now().isoformat(timespec="seconds")
    working_state["updated_at"] = portfolio["last_marked_at"]
    if not dry_run:
        save_paper_state(working_state)
    holdings = []
    for code, position in positions.items():
        price = float(position.get("last_price") or position.get("avg_price") or 0)
        avg_price = float(position.get("avg_price") or 0)
        shares = float(position.get("shares") or 0)
        holdings.append(
            {
                "code": code,
                "name": position.get("name") or code,
                "shares": round(shares, 6),
                "avg_price": round(avg_price, 4),
                "price": round(price, 4),
                "value": round(shares * price, 2),
                "pnl_pct": round((price / avg_price - 1) * 100, 2) if avg_price > 0 else 0.0,
            }
        )
    holdings.sort(key=lambda item: item["value"], reverse=True)
    return {
        "market": market,
        "market_label": portfolio.get("market_label"),
        "currency": portfolio.get("currency"),
        "initial_capital": round(initial_capital, 2),
        "total_value": round(total, 2),
        "cash": round(float(portfolio.get("cash") or 0), 2),
        "pnl": round(total - initial_capital, 2),
        "pnl_pct": round((total / initial_capital - 1) * 100, 2) if initial_capital else 0.0,
        "period_pnl": round(total - before, 2),
        "period_pnl_pct": round((total / before - 1) * 100, 2) if before else 0.0,
        "positions_count": len(holdings),
        "holdings": holdings,
    }


def apply_risk_controls(
    market: str,
    quotes: dict[str, dict[str, Any]],
    *,
    dry_run: bool = False,
) -> dict[str, Any] | None:
    if not paper_trading_enabled() or not paper_risk_control_enabled():
        return None
    state = load_paper_state()
    working_state = copy.deepcopy(state) if dry_run else state
    portfolio = _portfolio(working_state, market)
    positions = portfolio.get("positions") or {}
    if not positions:
        return None

    stop_loss_pct = abs(_env_float("PAPER_TRADING_STOP_LOSS_PCT", "5"))
    take_profit_pct = abs(_env_float("PAPER_TRADING_TAKE_PROFIT_PCT", "8"))
    trailing_drawdown_pct = abs(_env_float("PAPER_TRADING_TRAILING_TAKE_PROFIT_DRAWDOWN_PCT", "4"))
    trailing_arm_pct = abs(_env_float("PAPER_TRADING_TRAILING_TAKE_PROFIT_ARM_PCT", str(take_profit_pct)))
    at = datetime.now()
    triggered: list[dict[str, Any]] = []
    prices: dict[str, float] = {}

    for code, position in list(positions.items()):
        quote = quotes.get(code) or {}
        price = float(quote.get("price") or position.get("last_price") or position.get("avg_price") or 0)
        avg_price = float(position.get("avg_price") or 0)
        shares = float(position.get("shares") or 0)
        if price <= 0 or avg_price <= 0 or shares <= 0:
            continue
        prices[code] = price
        name = str(quote.get("name") or position.get("name") or code)
        pnl_pct = (price / avg_price - 1) * 100
        highest_return_pct = max(float(position.get("highest_return_pct") or pnl_pct), pnl_pct)
        position["highest_return_pct"] = round(highest_return_pct, 4)
        position["last_price"] = price
        position["name"] = name

        reason = ""
        rule = ""
        threshold = 0.0
        if pnl_pct <= -stop_loss_pct:
            reason = "跌到止损线，模拟盘立即卖出"
            rule = "止损"
            threshold = -stop_loss_pct
        elif take_profit_pct > 0 and pnl_pct >= take_profit_pct:
            reason = "达到止盈线，模拟盘先落袋"
            rule = "止盈"
            threshold = take_profit_pct
        elif (
            trailing_drawdown_pct > 0
            and highest_return_pct >= trailing_arm_pct
            and highest_return_pct - pnl_pct >= trailing_drawdown_pct
        ):
            reason = "浮盈回撤达到移动止盈线，模拟盘先锁定利润"
            rule = "移动止盈"
            threshold = trailing_drawdown_pct

        if not reason:
            continue

        trade = _trade(
            portfolio,
            action="sell",
            code=code,
            name=name,
            price=price,
            shares=shares,
            at=at,
            reason=reason,
        )
        if trade:
            triggered.append(
                {
                    "rule": rule,
                    "code": code,
                    "name": name,
                    "price": round(price, 4),
                    "avg_price": round(avg_price, 4),
                    "shares": round(shares, 6),
                    "pnl_pct": round(pnl_pct, 2),
                    "highest_return_pct": round(highest_return_pct, 2),
                    "threshold": round(threshold, 2),
                    "reason": reason,
                    "trade": trade,
                }
            )

    total = _total_value(portfolio, prices)
    initial_capital = float(portfolio.get("initial_capital") or total or 0)
    portfolio["last_total_value"] = total
    portfolio["last_risk_checked_at"] = at.isoformat(timespec="seconds")
    if triggered:
        portfolio["last_risk_triggered_at"] = at.isoformat(timespec="seconds")
    working_state["updated_at"] = at.isoformat(timespec="seconds")
    if not dry_run:
        save_paper_state(working_state)
    return {
        "market": market,
        "market_label": portfolio.get("market_label"),
        "currency": portfolio.get("currency"),
        "initial_capital": round(initial_capital, 2),
        "total_value": round(total, 2),
        "cash": round(float(portfolio.get("cash") or 0), 2),
        "pnl": round(total - initial_capital, 2),
        "pnl_pct": round((total / initial_capital - 1) * 100, 2) if initial_capital else 0.0,
        "positions_count": len(portfolio.get("positions") or {}),
        "triggered": triggered,
        "triggered_count": len(triggered),
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
        "trailing_drawdown_pct": trailing_drawdown_pct,
        "trailing_arm_pct": trailing_arm_pct,
    }


def build_paper_element(summary: dict[str, Any] | None, *, mode: str) -> dict[str, Any] | None:
    if not summary:
        return None
    currency = summary.get("currency") or ""
    if mode == "rebalance":
        action = "已按今日精选名单完成模拟调仓" if summary.get("changed") else "今日精选名单未变化，模拟持仓不重复调仓"
        trades = list(summary.get("trades") or [])
        trade_count = len(trades)
        trade_lines = []
        for trade in trades[:6]:
            side = "买入" if trade.get("action") == "buy" else "卖出"
            trade_lines.append(
                f"{side}{trade.get('name') or trade.get('code')}（{trade.get('code')}）"
                f"｜价格 {float(trade.get('price') or 0):.2f}"
                f"｜数量 {float(trade.get('shares') or 0):.6f}"
                f"｜金额 {float(trade.get('amount') or 0):.2f} {currency}"
            )
        detail_text = "\n".join(f"- {line}" for line in trade_lines) if trade_lines else "- 暂无新增买卖，继续持有原模拟仓位"
        content = (
            f"**模拟跟单：** {action}\n"
            f"账户市值 **{summary['total_value']:.2f} {currency}**｜"
            f"累计盈亏 **{summary['pnl']:+.2f} {currency}（{summary['pnl_pct']:+.2f}%）**｜"
            f"持仓 **{summary['positions_count']} 只**｜本次交易 **{trade_count} 笔**\n"
            f"**买卖明细：**\n{detail_text}"
        )
    else:
        holding_lines = []
        for item in list(summary.get("holdings") or [])[:6]:
            holding_lines.append(
                f"{item.get('name') or item.get('code')}（{item.get('code')}）"
                f"｜买入价 {float(item.get('avg_price') or 0):.2f}"
                f"｜当前价 {float(item.get('price') or 0):.2f}"
                f"｜数量 {float(item.get('shares') or 0):.6f}"
                f"｜盈亏 {float(item.get('pnl_pct') or 0):+.2f}%"
            )
        detail_text = "\n".join(f"- {line}" for line in holding_lines) if holding_lines else "- 暂无持仓，等待下一次盘前策略建仓"
        content = (
            f"**模拟跟单复盘：** 账户市值 **{summary['total_value']:.2f} {currency}**｜"
            f"本次变化 **{summary['period_pnl']:+.2f} {currency}（{summary['period_pnl_pct']:+.2f}%）**｜"
            f"累计盈亏 **{summary['pnl']:+.2f} {currency}（{summary['pnl_pct']:+.2f}%）**｜"
            f"持仓 **{summary['positions_count']} 只**\n"
            f"**持仓明细：**\n{detail_text}"
        )
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}
