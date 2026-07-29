"""Push Binance stock perpetual long/short watch signals to Feishu.

This script is intentionally read-only toward Binance: it fetches public
contract market data, filters ``long_watch`` / ``short_watch`` candidates,
and pushes an interactive Feishu card. It is scoped to Binance TradFi/equity
perpetual contracts and never places orders.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SIM_STATE_PATH = ROOT / "data" / "binance_contract_sim_state.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_binance_contract_data import (
    BinanceContractSnapshot,
    DEFAULT_INTERVAL,
    DEFAULT_LIMIT,
    configure_console_encoding,
    contract_symbols,
    fetch_contract_snapshots,
)


FEISHU_WEBHOOK_ATTEMPTS = 3
FEISHU_WEBHOOK_RETRY_DELAYS = (2.0, 5.0)
FEISHU_WEBHOOK_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_SIGNALS_PER_SIDE = 3


def _sign(secret: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    signature = base64.b64encode(
        hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    ).decode("utf-8")
    return {"timestamp": timestamp, "sign": signature}


def _stock_feishu_config() -> tuple[str, str, str]:
    stock_webhook = os.getenv("STOCK_FEISHU_WEBHOOK_URL", "").strip()
    if stock_webhook:
        return (
            stock_webhook,
            os.getenv("STOCK_FEISHU_WEBHOOK_SECRET", "").strip(),
            os.getenv("STOCK_FEISHU_WEBHOOK_KEYWORD", "").strip(),
        )
    return (
        os.getenv("FEISHU_WEBHOOK_URL", "").strip(),
        os.getenv("FEISHU_WEBHOOK_SECRET", "").strip(),
        os.getenv("FEISHU_WEBHOOK_KEYWORD", "").strip(),
    )


def send_card(card: dict[str, Any]) -> None:
    webhook, secret, _keyword = _stock_feishu_config()
    if not webhook:
        raise RuntimeError("未配置 STOCK_FEISHU_WEBHOOK_URL 或 FEISHU_WEBHOOK_URL")
    payload: dict[str, Any] = {"msg_type": "interactive", "card": card}
    if secret:
        payload.update(_sign(secret))
    last_error: Exception | None = None
    for attempt in range(1, FEISHU_WEBHOOK_ATTEMPTS + 1):
        try:
            response = requests.post(webhook, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            if result.get("code", result.get("StatusCode", 0)) not in {0, None}:
                raise RuntimeError(f"飞书卡片推送失败: {result}")
            return
        except requests.HTTPError as exc:
            last_error = exc
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code not in FEISHU_WEBHOOK_RETRY_STATUS_CODES or attempt >= FEISHU_WEBHOOK_ATTEMPTS:
                raise
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= FEISHU_WEBHOOK_ATTEMPTS:
                raise
        delay = FEISHU_WEBHOOK_RETRY_DELAYS[min(attempt - 1, len(FEISHU_WEBHOOK_RETRY_DELAYS) - 1)]
        print(
            f"Feishu webhook push failed on attempt {attempt}; retrying in {delay:g}s: {last_error}",
            file=sys.stderr,
        )
        time.sleep(delay)
    if last_error is not None:
        raise last_error


def _env_flag(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return min(maximum, max(minimum, int(raw_value)))
    except ValueError:
        return default


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return min(maximum, max(minimum, float(raw_value)))
    except ValueError:
        return default


def _pct(value: float) -> str:
    return f"{value:+.2f}%"


def _funding(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:+.4f}%"


def long_candidates(
    snapshots: list[BinanceContractSnapshot],
    *,
    min_score: float,
) -> list[BinanceContractSnapshot]:
    return [
        item
        for item in snapshots
        if item.contract_signal == "long_watch" and item.signal_score >= min_score
    ]


def signal_candidates(
    snapshots: list[BinanceContractSnapshot],
    *,
    side: str,
    min_score: float,
) -> list[BinanceContractSnapshot]:
    selected: list[BinanceContractSnapshot] = []
    for item in snapshots:
        if side in {"long", "both"} and item.contract_signal == "long_watch" and item.signal_score >= min_score:
            selected.append(item)
        if side in {"short", "both"} and item.contract_signal == "short_watch" and item.signal_score <= -min_score:
            selected.append(item)
    return sorted(
        selected,
        key=lambda item: (
            0 if item.contract_signal == "long_watch" else 1,
            -abs(item.signal_score),
            -item.quote_volume_24h,
        ),
    )


def build_contract_signal_card(
    signals: list[BinanceContractSnapshot],
    *,
    all_snapshots: list[BinanceContractSnapshot],
    errors: list[str],
    interval: str,
    limit: int,
    side: str,
) -> dict[str, Any]:
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M")
    long_count = sum(1 for item in signals if item.contract_signal == "long_watch")
    short_count = sum(1 for item in signals if item.contract_signal == "short_watch")
    header_title = (
        f"🟢 Binance 股票合约多空信号｜多 {long_count} / 空 {short_count}"
        if signals
        else "⚪ Binance 股票合约多空信号｜当前无触发"
    )
    conclusion = (
        f"当前触发 {len(signals)} 个合约信号：多头 {long_count} 个，空头 {short_count} 个。"
        if signals
        else "当前候选池没有满足做多或做空条件的合约，不建议为了推送而硬开仓。"
    )
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**结论：** {conclusion}\n"
                    f"**筛选：** Binance EQUITY / TRADIFI_PERPETUAL，side=`{side}`，`long_watch`/`short_watch` + 分数阈值 + 主动买卖结构\n"
                    f"**周期：** {interval} × {limit} 根K线　**生成：** {now_text}"
                ),
            },
        },
        {"tag": "hr"},
    ]

    rows = signals if signals else all_snapshots[:5]
    if not rows:
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": "未抓取到有效合约行情。"},
            }
        )
    for index, item in enumerate(rows, start=1):
        if item.contract_signal == "long_watch":
            label = "做多观察"
        elif item.contract_signal == "short_watch":
            label = "做空观察"
        else:
            label = "未触发"
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**{index}. {item.symbol}｜{label}**　评分 **{item.signal_score:+.2f}**\n"
                        f"最新 **{item.last_price:g}**　标记 **{item.mark_price:g}**　指数 **{item.index_price:g}**\n"
                        f"24h **{_pct(item.price_change_pct_24h)}**　短周期 **{_pct(item.kline_return_pct)}**　"
                        f"主动买入占比 **{item.taker_buy_quote_ratio:.2f}**\n"
                        f"资金费率 **{_funding(item.last_funding_rate)}**　24h成交额 **{item.quote_volume_24h:,.0f}**"
                    ),
                },
            }
        )
        elements.append({"tag": "hr"})

    if errors:
        elements.append(
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"部分合约抓取失败：{len(errors)} 项；已跳过失败项。",
                    }
                ],
            }
        )
    elements.append(
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": "仅为 Binance 股票合约行情信号，不代表自动下单；请按杠杆、止损和仓位纪律执行。",
                }
            ],
        }
    )
    if long_count and short_count:
        template = "purple"
    elif short_count:
        template = "red"
    elif long_count:
        template = "green"
    else:
        template = "grey"
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": header_title},
        },
        "elements": elements,
    }


def build_long_signal_card(
    longs: list[BinanceContractSnapshot],
    *,
    all_snapshots: list[BinanceContractSnapshot],
    errors: list[str],
    interval: str,
    limit: int,
) -> dict[str, Any]:
    """Compatibility wrapper for older tests/imports that only cared about longs."""
    return build_contract_signal_card(
        longs,
        all_snapshots=all_snapshots,
        errors=errors,
        interval=interval,
        limit=limit,
        side="long",
    )


def _signal_label(signal: str) -> str:
    if signal == "long_watch":
        return "做多观察"
    if signal == "short_watch":
        return "做空观察"
    return "未触发"


def _side_label(side: str) -> str:
    return {"long": "只看做多", "short": "只看做空", "both": "多空都看"}.get(side, side)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _format_price(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _plan_base_price(item: BinanceContractSnapshot) -> float:
    return item.mark_price or item.last_price or item.index_price


def _risk_pct(item: BinanceContractSnapshot) -> float:
    # Use recent K-line range as a volatility proxy, but keep the plan tight
    # enough for contract trading and wide enough to avoid pure noise stops.
    return _clamp(item.kline_range_pct * 0.35, 0.8, 3.0)


def _trade_plan_values(item: BinanceContractSnapshot) -> dict[str, Any] | None:
    base = _plan_base_price(item)
    if base <= 0 or item.contract_signal not in {"long_watch", "short_watch"}:
        return None

    risk_pct = _risk_pct(item)
    entry_band = _clamp(risk_pct * 0.18, 0.15, 0.50)
    entry_low = base * (1 - entry_band / 100)
    entry_high = base * (1 + entry_band / 100)
    if item.contract_signal == "long_watch":
        stop = base * (1 - risk_pct / 100)
        risk = base - stop
        tp1 = base + risk
        tp2 = base + risk * 2
        invalidation = "15m 收盘跌破止损，或主动买入占比跌回 0.50 以下。"
        direction = "long"
    else:
        stop = base * (1 + risk_pct / 100)
        risk = stop - base
        tp1 = max(0.0, base - risk)
        tp2 = max(0.0, base - risk * 2)
        invalidation = "15m 收盘突破止损，或主动买入占比回到 0.50 以上。"
        direction = "short"
    return {
        "direction": direction,
        "base": base,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "risk_pct": risk_pct,
        "risk": abs(base - stop),
        "invalidation": invalidation,
    }


def _trade_plan_lines(item: BinanceContractSnapshot) -> tuple[str, str]:
    plan = _trade_plan_values(item)
    if not plan:
        return (
            "计划：无触发，不提供参考入场、止损、止盈。",
            "失效：等待下一轮扫描重新确认。",
        )

    return (
        "计划："
        f"参考入场 {_format_price(plan['entry_low'])}-{_format_price(plan['entry_high'])}；"
        f"止损 {_format_price(plan['stop'])}；"
        f"止盈1 {_format_price(plan['tp1'])}；"
        f"止盈2 {_format_price(plan['tp2'])}；"
        "单笔风险≤账户 0.5%-1%。",
        f"失效：{plan['invalidation']}",
    )


def _sim_order_enabled() -> bool:
    return _env_flag("BINANCE_SIM_ORDER_ENABLED", "true")


def _sim_order_values(item: BinanceContractSnapshot) -> dict[str, Any] | None:
    plan = _trade_plan_values(item)
    if not plan:
        return None

    base = float(plan["base"])
    risk_per_contract = float(plan["risk"])
    if risk_per_contract <= 0:
        return None

    equity = _env_float("BINANCE_SIM_ACCOUNT_EQUITY_USDT", 10_000.0, minimum=100.0, maximum=10_000_000.0)
    order_risk_pct = _env_float("BINANCE_SIM_ORDER_RISK_PCT", 1.0, minimum=0.1, maximum=5.0)
    leverage = _env_float("BINANCE_SIM_LEVERAGE", 3.0, minimum=1.0, maximum=20.0)
    max_margin_pct = _env_float("BINANCE_SIM_MAX_MARGIN_PCT", 30.0, minimum=1.0, maximum=100.0)

    risk_budget = equity * order_risk_pct / 100
    qty_by_risk = risk_budget / risk_per_contract
    max_notional = equity * max_margin_pct / 100 * leverage
    qty_by_margin = max_notional / base
    quantity = max(0.0, min(qty_by_risk, qty_by_margin))
    notional = quantity * base
    margin = notional / leverage if leverage > 0 else notional
    return {
        **plan,
        "entry": base,
        "quantity": quantity,
        "notional": notional,
        "margin": margin,
        "risk_budget": risk_budget,
        "leverage": leverage,
        "direction_label": "做多" if plan["direction"] == "long" else "做空",
        "capped": qty_by_margin < qty_by_risk,
    }


def _sim_order_line(item: BinanceContractSnapshot) -> str:
    if not _sim_order_enabled():
        return "模拟开单：已关闭。"
    if item.contract_signal not in {"long_watch", "short_watch"}:
        return "模拟开单：无触发，不模拟开仓。"
    values = _sim_order_values(item)
    if not values:
        return "模拟开单：风险距离无效，跳过。"

    capped = "；已按最大保证金限制缩小仓位" if values["capped"] else ""

    return (
        f"模拟开单：方向 {values['direction_label']}；开单价 {_format_price(float(values['entry']))}；"
        f"数量 {_format_price(float(values['quantity']))} 张；名义仓位 {_format_price(float(values['notional']))} USDT；"
        f"预估保证金 {_format_price(float(values['margin']))} USDT；"
        f"风险预算 {_format_price(float(values['risk_budget']))} USDT；"
        f"杠杆 {float(values['leverage']):g}x{capped}。"
    )


def _load_sim_state() -> dict[str, Any]:
    try:
        state = json.loads(SIM_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    state.setdefault("orders", [])
    return state


def _save_sim_state(state: dict[str, Any]) -> None:
    SIM_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = SIM_STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(SIM_STATE_PATH)


def _current_price(item: BinanceContractSnapshot) -> float:
    return item.mark_price or item.last_price or item.index_price


def _close_sim_order(order: dict[str, Any], *, price: float, reason: str, result: str, at: str) -> dict[str, Any]:
    entry = float(order.get("entry") or 0)
    quantity = float(order.get("quantity") or 0)
    direction = str(order.get("direction") or "")
    pnl = (entry - price) * quantity if direction == "short" else (price - entry) * quantity
    order.update(
        {
            "status": "closed",
            "closed_at": at,
            "close_price": round(price, 6),
            "close_reason": reason,
            "result": result,
            "pnl": round(pnl, 4),
            "pnl_pct": round((pnl / float(order.get("notional") or 1)) * 100, 4),
        }
    )
    return order


def _maybe_close_order(order: dict[str, Any], snapshot: BinanceContractSnapshot, *, at: str) -> dict[str, Any] | None:
    if order.get("status") != "open":
        return None
    price = _current_price(snapshot)
    if price <= 0:
        return None
    direction = str(order.get("direction") or "")
    stop = float(order.get("stop") or 0)
    tp1 = float(order.get("tp1") or 0)
    tp2 = float(order.get("tp2") or 0)
    if direction == "long":
        if tp2 > 0 and price >= tp2:
            return _close_sim_order(order, price=price, reason="止盈2", result="win", at=at)
        if tp1 > 0 and price >= tp1:
            return _close_sim_order(order, price=price, reason="止盈1", result="win", at=at)
        if stop > 0 and price <= stop:
            return _close_sim_order(order, price=price, reason="止损", result="loss", at=at)
    if direction == "short":
        if tp2 > 0 and price <= tp2:
            return _close_sim_order(order, price=price, reason="止盈2", result="win", at=at)
        if tp1 > 0 and price <= tp1:
            return _close_sim_order(order, price=price, reason="止盈1", result="win", at=at)
        if stop > 0 and price >= stop:
            return _close_sim_order(order, price=price, reason="止损", result="loss", at=at)
    return None


def _sim_stats(state: dict[str, Any]) -> dict[str, Any]:
    orders = list(state.get("orders") or [])
    closed = [order for order in orders if order.get("status") == "closed"]
    wins = [order for order in closed if order.get("result") == "win"]
    losses = [order for order in closed if order.get("result") == "loss"]
    open_orders = [order for order in orders if order.get("status") == "open"]
    total_pnl = sum(float(order.get("pnl") or 0) for order in closed)
    closed_count = len(closed)
    return {
        "total_orders": len(orders),
        "open_count": len(open_orders),
        "closed_count": closed_count,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / closed_count * 100, 2) if closed_count else 0.0,
        "total_pnl": round(total_pnl, 4),
    }


def _sim_order_record(item: BinanceContractSnapshot, *, at: str) -> dict[str, Any] | None:
    values = _sim_order_values(item)
    if not values:
        return None
    return {
        "id": f"{at}-{item.symbol}-{values['direction']}",
        "status": "open",
        "opened_at": at,
        "symbol": item.symbol,
        "direction": values["direction"],
        "direction_label": values["direction_label"],
        "entry": round(float(values["entry"]), 6),
        "entry_low": round(float(values["entry_low"]), 6),
        "entry_high": round(float(values["entry_high"]), 6),
        "stop": round(float(values["stop"]), 6),
        "tp1": round(float(values["tp1"]), 6),
        "tp2": round(float(values["tp2"]), 6),
        "quantity": round(float(values["quantity"]), 6),
        "notional": round(float(values["notional"]), 4),
        "margin": round(float(values["margin"]), 4),
        "risk_budget": round(float(values["risk_budget"]), 4),
        "leverage": float(values["leverage"]),
        "signal_score": item.signal_score,
    }


def _update_sim_orders(
    *,
    snapshots: list[BinanceContractSnapshot],
    signals: list[BinanceContractSnapshot],
    dry_run: bool,
) -> dict[str, Any]:
    if not _sim_order_enabled():
        return {"enabled": False, "events": [], "stats": _sim_stats({"orders": []})}
    state = _load_sim_state()
    events: list[dict[str, Any]] = []
    at = datetime.now().isoformat(timespec="seconds")
    by_symbol = {snapshot.symbol: snapshot for snapshot in snapshots}

    for order in state.get("orders", []):
        snapshot = by_symbol.get(str(order.get("symbol") or ""))
        if not snapshot:
            continue
        before_status = order.get("status")
        closed = _maybe_close_order(order, snapshot, at=at)
        if closed and before_status != "closed":
            events.append({"type": "close", "order": dict(closed)})

    open_keys = {
        (str(order.get("symbol")), str(order.get("direction")))
        for order in state.get("orders", [])
        if order.get("status") == "open"
    }
    for item in signals:
        order = _sim_order_record(item, at=at)
        if not order:
            continue
        key = (str(order["symbol"]), str(order["direction"]))
        if key in open_keys:
            continue
        state.setdefault("orders", []).append(order)
        open_keys.add(key)
        events.append({"type": "open", "order": dict(order)})

    state["orders"] = list(state.get("orders") or [])[-300:]
    state["updated_at"] = at
    if not dry_run:
        _save_sim_state(state)
    return {"enabled": True, "events": events, "stats": _sim_stats(state)}


def _sim_stats_line(simulation: dict[str, Any] | None) -> str:
    if not simulation or not simulation.get("enabled"):
        return "模拟胜率：模拟开单已关闭。"
    stats = simulation.get("stats") or {}
    closed_count = int(stats.get("closed_count") or 0)
    if closed_count <= 0:
        return f"模拟胜率：暂无已平仓样本；当前持仓 {int(stats.get('open_count') or 0)} 笔。"
    return (
        f"模拟胜率：已平 {closed_count} 笔；胜 {int(stats.get('wins') or 0)} / "
        f"负 {int(stats.get('losses') or 0)}；胜率 {float(stats.get('win_rate') or 0):.2f}%；"
        f"累计盈亏 {_format_price(float(stats.get('total_pnl') or 0))} USDT；"
        f"当前持仓 {int(stats.get('open_count') or 0)} 笔。"
    )


def _sim_events_line(simulation: dict[str, Any] | None) -> str:
    events = list((simulation or {}).get("events") or [])
    if not events:
        return "模拟变动：本轮无新开仓/平仓。"
    parts: list[str] = []
    for event in events[-5:]:
        order = event.get("order") or {}
        symbol = order.get("symbol")
        if event.get("type") == "open":
            parts.append(f"开仓 {symbol} {order.get('direction_label')} @ {_format_price(float(order.get('entry') or 0))}")
        if event.get("type") == "close":
            parts.append(
                f"平仓 {symbol} {order.get('close_reason')} @ {_format_price(float(order.get('close_price') or 0))} "
                f"({order.get('result')}, PnL {_format_price(float(order.get('pnl') or 0))})"
            )
    return "模拟变动：" + "；".join(parts) + "。"


def _score_explanation() -> str:
    return (
        "分数怎么看：正分越高，说明做多条件越集中；负分越低，说明做空条件越集中；"
        "接近 0 代表方向不明显。分数不是胜率，也不是下单命令，只用于排序优先级。"
    )


def _direction_logic_text(direction: str) -> str:
    if direction == "long":
        return (
            "做多逻辑：短周期价格动量转强，主动买入占比偏高，标记价/指数价没有明显失真，"
            "资金费率风险可控，优先找顺势突破或回踩承接。"
        )
    return (
        "做空逻辑：短周期价格动量转弱，主动买入不足或卖压占优，反弹承压，"
        "标记价/指数价没有明显失真，资金费率风险可控。"
    )


def _score_meaning(item: BinanceContractSnapshot) -> str:
    strength = abs(item.signal_score)
    if strength >= 5:
        level = "强"
    elif strength >= 2:
        level = "中等"
    else:
        level = "轻微"
    if item.contract_signal == "short_watch":
        return f"分数含义：偏空{level}信号；负分绝对值越大，空头条件越集中。"
    if item.contract_signal == "long_watch":
        return f"分数含义：偏多{level}信号；正分越高，多头条件越集中。"
    return "分数含义：方向不明显，仅作候选池参考。"


def _rank_long_signal(item: BinanceContractSnapshot) -> tuple[float, float, str]:
    return (-item.signal_score, -item.quote_volume_24h, item.symbol)


def _rank_short_signal(item: BinanceContractSnapshot) -> tuple[float, float, str]:
    return (item.signal_score, -item.quote_volume_24h, item.symbol)


def signal_sections(
    signals: list[BinanceContractSnapshot],
    *,
    per_side_limit: int = MAX_SIGNALS_PER_SIDE,
) -> tuple[list[BinanceContractSnapshot], list[BinanceContractSnapshot]]:
    longs = sorted(
        [item for item in signals if item.contract_signal == "long_watch"],
        key=_rank_long_signal,
    )[:per_side_limit]
    shorts = sorted(
        [item for item in signals if item.contract_signal == "short_watch"],
        key=_rank_short_signal,
    )[:per_side_limit]
    return longs, shorts


def selected_signals(
    signals: list[BinanceContractSnapshot],
    *,
    per_side_limit: int = MAX_SIGNALS_PER_SIDE,
) -> list[BinanceContractSnapshot]:
    longs, shorts = signal_sections(signals, per_side_limit=per_side_limit)
    return longs + shorts


def _candidate_preview(all_snapshots: list[BinanceContractSnapshot]) -> list[BinanceContractSnapshot]:
    return sorted(all_snapshots, key=lambda item: (-abs(item.signal_score), -item.quote_volume_24h))[:3]


def _append_signal_section(
    elements: list[dict[str, Any]],
    *,
    title: str,
    logic: str,
    items: list[BinanceContractSnapshot],
    empty_text: str,
) -> None:
    elements.append(
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{title}**\n{logic}",
            },
        }
    )
    if not items:
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": empty_text},
            }
        )
        elements.append({"tag": "hr"})
        return

    for index, item in enumerate(items, start=1):
        label = _signal_label(item.contract_signal)
        plan_line, invalidation_line = _trade_plan_lines(item)
        sim_order_line = _sim_order_line(item)
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**{index}. 合约：{item.symbol}**\n"
                        f"方向：**{label}**　评分：**{item.signal_score:+.2f}**\n"
                        f"{_score_meaning(item)}\n"
                        f"{plan_line}\n"
                        f"{sim_order_line}\n"
                        f"{invalidation_line}\n"
                        f"最新：**{item.last_price:g}**　标记：**{item.mark_price:g}**　指数：**{item.index_price:g}**\n"
                        f"24h：**{_pct(item.price_change_pct_24h)}**　短周期：**{_pct(item.kline_return_pct)}**　"
                        f"主动买入占比：**{item.taker_buy_quote_ratio:.2f}**\n"
                        f"资金费率：**{_funding(item.last_funding_rate)}**　24h成交额：**{item.quote_volume_24h:,.0f}**"
                    ),
                },
            }
        )
        elements.append({"tag": "hr"})


def build_contract_signal_card(
    signals: list[BinanceContractSnapshot],
    *,
    all_snapshots: list[BinanceContractSnapshot],
    errors: list[str],
    interval: str,
    limit: int,
    side: str,
    simulation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a Feishu card with conservative lark_md formatting.

    Feishu's markdown renderer can be picky around backticks and full-width
    separators. Keep the symbol on a dedicated ``合约：`` line so stock token
    names such as MUUSDT/SNDKUSDT are never swallowed by rendering.
    """

    now_text = datetime.now().strftime("%Y-%m-%d %H:%M")
    long_signals, short_signals = signal_sections(signals)
    long_count = len(long_signals)
    short_count = len(short_signals)
    header_title = (
        f"Binance 股票合约多空信号 - 开多 {long_count} / 开空 {short_count}"
        if signals
        else "Binance 股票合约多空信号 - 当前无触发"
    )
    conclusion = (
        f"当前精选 {len(long_signals) + len(short_signals)} 个合约信号：开多 {long_count} 个，开空 {short_count} 个；每边最多展示 {MAX_SIGNALS_PER_SIDE} 支。"
        if signals
        else "当前候选池没有满足做多或做空条件的合约，不建议为了推送而硬开仓。"
    )
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**结论：** {conclusion}\n"
                    f"**筛选：** 只扫描 Binance 股票代币合约；{_side_label(side)}；按价格动量、分数阈值、主动买卖结构判断。\n"
                    f"**{_score_explanation()}**\n"
                    f"**周期：** {interval} × {limit} 根K线　**生成：** {now_text}\n"
                    f"**{_sim_stats_line(simulation)}**\n"
                    f"{_sim_events_line(simulation)}"
                ),
            },
        },
        {"tag": "hr"},
    ]

    _append_signal_section(
        elements,
        title=f"开多精选（最多 {MAX_SIGNALS_PER_SIDE} 支）",
        logic=_direction_logic_text("long"),
        items=long_signals,
        empty_text="本轮没有满足开多条件的股票合约；不为了凑数量硬开多。",
    )
    _append_signal_section(
        elements,
        title=f"开空精选（最多 {MAX_SIGNALS_PER_SIDE} 支）",
        logic=_direction_logic_text("short"),
        items=short_signals,
        empty_text="本轮没有满足开空条件的股票合约；不为了凑数量硬开空。",
    )

    preview_rows = [] if signals else _candidate_preview(all_snapshots)
    if not signals and preview_rows:
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**未触发候选参考**\n下面只用于解释为什么没有开仓信号，不建议据此交易。",
                },
            }
        )
    if not signals and not preview_rows:
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": "未抓取到有效股票合约行情。"},
            }
        )

    for index, item in enumerate(preview_rows, start=1):
        label = _signal_label(item.contract_signal)
        plan_line, invalidation_line = _trade_plan_lines(item)
        sim_order_line = _sim_order_line(item)
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**{index}. 合约：{item.symbol}**\n"
                        f"状态：**{label}**　评分：**{item.signal_score:+.2f}**\n"
                        f"{_score_meaning(item)}\n"
                        f"{plan_line}\n"
                        f"{sim_order_line}\n"
                        f"{invalidation_line}\n"
                        f"最新：**{item.last_price:g}**　标记：**{item.mark_price:g}**　指数：**{item.index_price:g}**\n"
                        f"24h：**{_pct(item.price_change_pct_24h)}**　短周期：**{_pct(item.kline_return_pct)}**　"
                        f"主动买入占比：**{item.taker_buy_quote_ratio:.2f}**\n"
                        f"资金费率：**{_funding(item.last_funding_rate)}**　24h成交额：**{item.quote_volume_24h:,.0f}**"
                    ),
                },
            }
        )
        elements.append({"tag": "hr"})

    if errors:
        elements.append(
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"部分合约抓取失败：{len(errors)} 项；已跳过失败项。",
                    }
                ],
            }
        )
    elements.append(
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": "仅为 Binance 股票合约行情信号，不代表自动下单；请按杠杆、止损和仓位纪律执行。",
                }
            ],
        }
    )

    if long_count and short_count:
        template = "purple"
    elif short_count:
        template = "red"
    elif long_count:
        template = "green"
    else:
        template = "grey"
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": header_title},
        },
        "elements": elements,
    }


def run(
    *,
    market: str,
    symbols: str | None,
    interval: str,
    limit: int,
    timeout: float,
    side: str,
    min_score: float,
    dry_run: bool,
    push_empty: bool,
) -> dict[str, Any]:
    snapshots, errors = fetch_contract_snapshots(
        contract_symbols(market, symbols),
        market=market,
        interval=interval,
        limit=limit,
        timeout=timeout,
    )
    raw_signals = signal_candidates(snapshots, side=side, min_score=min_score)
    signals = selected_signals(raw_signals)
    longs = [item for item in signals if item.contract_signal == "long_watch"]
    shorts = [item for item in signals if item.contract_signal == "short_watch"]
    simulation = _update_sim_orders(snapshots=snapshots, signals=signals, dry_run=dry_run)
    card = build_contract_signal_card(
        signals,
        all_snapshots=snapshots,
        errors=errors,
        interval=interval,
        limit=limit,
        side=side,
        simulation=simulation,
    )
    result = {
        "long_count": len(longs),
        "short_count": len(shorts),
        "signal_count": len(signals),
        "raw_signal_count": len(raw_signals),
        "snapshot_count": len(snapshots),
        "errors": errors,
        "longs": [item.symbol for item in longs],
        "shorts": [item.symbol for item in shorts],
        "signals": [item.symbol for item in signals],
        "simulation": simulation,
        "card": card,
    }
    if dry_run:
        return result
    sim_events = list(simulation.get("events") or [])
    if signals or push_empty or sim_events:
        send_card(card)
        result["pushed"] = True
    else:
        result["pushed"] = False
    return result


def main() -> int:
    configure_console_encoding()
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Push Binance stock perpetual long/short watch signals to Feishu.")
    parser.add_argument("--market", choices=("usdm",), default=os.getenv("BINANCE_CONTRACT_MARKET", "usdm"))
    parser.add_argument("--symbols", help="Comma separated futures symbols.")
    parser.add_argument("--interval", default=os.getenv("BINANCE_CONTRACT_INTERVAL", DEFAULT_INTERVAL))
    parser.add_argument(
        "--limit",
        type=int,
        default=_env_int("BINANCE_CONTRACT_KLINE_LIMIT", DEFAULT_LIMIT, minimum=2, maximum=1000),
    )
    parser.add_argument("--timeout", type=float, default=float(os.getenv("BINANCE_CONTRACT_TIMEOUT_SEC", "10")))
    parser.add_argument(
        "--side",
        choices=("long", "short", "both"),
        default=os.getenv("BINANCE_CONTRACT_SIGNAL_SIDE", "both"),
        help="Signal side to push. Default: both.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=float(os.getenv("BINANCE_SIGNAL_MIN_SCORE", os.getenv("BINANCE_LONG_SIGNAL_MIN_SCORE", "2"))),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-push-empty",
        action="store_true",
        help="Do not push a status card when there are no long/short watch signals.",
    )
    parser.add_argument(
        "--push-empty",
        action="store_true",
        help="Push a status card even when there are no long/short watch signals.",
    )
    args = parser.parse_args()
    result = run(
        market=args.market,
        symbols=args.symbols,
        interval=args.interval,
        limit=max(2, min(1000, args.limit)),
        timeout=max(1.0, args.timeout),
        side=args.side,
        min_score=args.min_score,
        dry_run=args.dry_run,
        push_empty=args.push_empty
        or ((not args.no_push_empty) and _env_flag("BINANCE_PUSH_EMPTY_LONG_STATUS", "false")),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
