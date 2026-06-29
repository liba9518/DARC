"""Intraday event-driven alerts for the currently selected stocks."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yfinance as yf
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from integrations.a_stock_direct import fetch_tencent_quotes
from integrations.card_language import sanitize_card, stock_display_name
from scripts.push_daily_strategy_cards import load_state, send_card
from scripts.push_strategy_digest import configure_console_encoding


ALERT_STATE_PATH = ROOT / "data" / "intraday_alert_state.json"


def market_is_open(market: str, now: datetime | None = None) -> bool:
    timezone = ZoneInfo("America/New_York") if market == "us" else ZoneInfo("Asia/Shanghai")
    current = now or datetime.now(timezone)
    if current.weekday() >= 5:
        return False
    current_time = current.time()
    if market == "us":
        return time(9, 30) <= current_time <= time(16, 0)
    return time(9, 30) <= current_time <= time(11, 30) or time(13, 0) <= current_time <= time(15, 0)


def load_alert_state() -> dict[str, Any]:
    try:
        return json.loads(ALERT_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_alert_state(state: dict[str, Any]) -> None:
    ALERT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = ALERT_STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(ALERT_STATE_PATH)


def _selected_entries(market: str) -> list[dict[str, Any]]:
    state = load_state()
    key = "us" if market == "us" else "a"
    section = state.get(key, {})
    picks = section.get("picks") or []
    if picks:
        return [item for item in picks if isinstance(item, dict)]
    codes = section.get("next_preview_codes") or section.get("codes") or []
    return [{"code": code, "name": code, "signal_price": 0} for code in codes]


def _a_quotes(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows = fetch_tencent_quotes([str(item["code"]) for item in entries])
    return {
        str(row["code"]): {
            "price": float(row["price"]),
            "day_change": float(row.get("pct_change") or 0),
            "name": str(row.get("name") or row["code"]),
        }
        for row in rows
    }


def _us_quotes(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for item in entries:
        code = str(item["code"]).upper()
        frame = yf.Ticker(code).history(period="1d", interval="5m", auto_adjust=True, prepost=False)
        if frame is None or frame.empty:
            continue
        close = frame["Close"].dropna().astype(float)
        if close.empty:
            continue
        current = float(close.iloc[-1])
        opening = float(close.iloc[0])
        result[code] = {
            "price": current,
            "day_change": (current / opening - 1) * 100 if opening > 0 else 0,
            "name": stock_display_name(code, str(item.get("name") or code)),
        }
    return result


def evaluate_alert(
    *,
    code: str,
    name: str,
    current_price: float,
    day_change: float,
    signal_price: float,
    previous_alert_price: float,
    last_alert_at: str | None,
    now: datetime,
    move_threshold: float = 2.0,
    extreme_threshold: float = 3.5,
    step_threshold: float = 1.2,
    cooldown_minutes: int = 60,
) -> dict[str, Any] | None:
    since_signal = (current_price / signal_price - 1) * 100 if signal_price > 0 else day_change
    since_alert = (
        (current_price / previous_alert_price - 1) * 100 if previous_alert_price > 0 else since_signal
    )
    if last_alert_at:
        try:
            last_time = datetime.fromisoformat(last_alert_at)
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=now.tzinfo)
            if now - last_time < timedelta(minutes=cooldown_minutes) and abs(since_alert) < extreme_threshold:
                return None
        except ValueError:
            pass

    strong_move = abs(since_signal) >= move_threshold
    fresh_step = abs(since_alert) >= step_threshold
    extreme_move = abs(since_signal) >= extreme_threshold
    if not extreme_move and not (strong_move and fresh_step):
        return None

    if since_signal >= extreme_threshold:
        conclusion = "上涨趋势进一步确认，继续重点关注"
    elif since_signal >= move_threshold:
        conclusion = "走势保持强势，继续按计划关注"
    elif since_signal <= -extreme_threshold:
        conclusion = "短线明显转弱，立即降低关注"
    else:
        conclusion = "走势转弱，严格执行风险控制"
    return {
        "code": code,
        "name": name,
        "price": current_price,
        "day_change": day_change,
        "since_signal": since_signal,
        "conclusion": conclusion,
    }


def build_alert_card(market: str, alerts: list[dict[str, Any]]) -> dict[str, Any]:
    title = "🇺🇸 美股盘中异动提醒" if market == "us" else "🇨🇳 沪深股票盘中异动提醒"
    template = "orange" if any(item["since_signal"] < 0 for item in alerts) else "green"
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**明确结论：** 精选股票出现值得处理的盘中变化，共 {len(alerts)} 只。",
            },
        },
        {"tag": "hr"},
    ]
    for item in alerts:
        display_name = stock_display_name(item["code"], item["name"])
        code_suffix = f"（{item['code']}）"
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**{display_name}{code_suffix}**\n"
                        f"当前价格 **{item['price']:.2f}**｜当日变化 **{item['day_change']:+.2f}%**｜"
                        f"策略后变化 **{item['since_signal']:+.2f}%**\n"
                        f"**处理意见：{item['conclusion']}**"
                    ),
                },
            }
        )
    elements.append(
        {
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": "只有达到异动门槛才推送，相同方向一小时内不重复提醒。"}],
        }
    )
    return sanitize_card(
        {
            "config": {"wide_screen_mode": True},
            "header": {"template": template, "title": {"tag": "plain_text", "content": title}},
            "elements": elements,
        }
    )


def run_once(*, market: str, dry_run: bool = False) -> None:
    load_dotenv(ROOT / ".env")
    if not market_is_open(market):
        print("当前不在交易时段，跳过检查")
        return
    entries = _selected_entries(market)
    if not entries:
        print("尚无精选名单，跳过检查")
        return
    quotes = _us_quotes(entries) if market == "us" else _a_quotes(entries)
    state = load_alert_state()
    market_state = state.setdefault(market, {})
    now = datetime.now(ZoneInfo("America/New_York") if market == "us" else ZoneInfo("Asia/Shanghai"))
    alerts = []
    for entry in entries:
        code = str(entry.get("code") or "").upper()
        quote = quotes.get(code)
        if not quote:
            continue
        prior = market_state.get(code, {})
        alert = evaluate_alert(
            code=code,
            name=str(quote.get("name") or entry.get("name") or code),
            current_price=float(quote["price"]),
            day_change=float(quote.get("day_change") or 0),
            signal_price=float(entry.get("signal_price") or 0),
            previous_alert_price=float(prior.get("last_alert_price") or 0),
            last_alert_at=prior.get("last_alert_at"),
            now=now,
            move_threshold=float(os.getenv("INTRADAY_MOVE_THRESHOLD", "2.0")),
            extreme_threshold=float(os.getenv("INTRADAY_EXTREME_THRESHOLD", "3.5")),
            step_threshold=float(os.getenv("INTRADAY_STEP_THRESHOLD", "1.2")),
            cooldown_minutes=int(os.getenv("INTRADAY_COOLDOWN_MINUTES", "60")),
        )
        market_state.setdefault(code, {})["last_price"] = float(quote["price"])
        if alert:
            alerts.append(alert)
            market_state[code]["last_alert_price"] = float(quote["price"])
            market_state[code]["last_alert_at"] = now.isoformat(timespec="seconds")
    state["updated_at"] = now.isoformat(timespec="seconds")
    if dry_run:
        print(json.dumps(build_alert_card(market, alerts), ensure_ascii=False, indent=2) if alerts else "没有达到推送门槛")
        return
    save_alert_state(state)
    if not alerts:
        print("没有达到推送门槛")
        return
    send_card(build_alert_card(market, alerts))
    print(f"盘中异动提醒已推送：{len(alerts)}只")


def main() -> int:
    configure_console_encoding()
    parser = argparse.ArgumentParser(description="精选股票盘中异动监控")
    parser.add_argument("--market", choices=("cn", "us"), required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_once(market=args.market, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
