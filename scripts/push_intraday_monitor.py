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
from scripts.paper_trading import apply_risk_controls
from scripts.push_daily_strategy_cards import load_state, send_card
from scripts.push_strategy_digest import configure_console_encoding


ALERT_STATE_PATH = ROOT / "data" / "intraday_alert_state.json"


def intraday_status_on_idle_enabled() -> bool:
    return os.getenv("FEISHU_INTRADAY_STATUS_ON_IDLE", "false").strip().lower() in {"1", "true", "yes", "on"}


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


def build_risk_control_card(market: str, summary: dict[str, Any]) -> dict[str, Any]:
    triggered = list(summary.get("triggered") or [])
    is_us = market == "us"
    has_stop_loss = any(str(item.get("rule")) == "止损" for item in triggered)
    title = "🇺🇸 美股模拟跟单止盈止损处理" if is_us else "🇨🇳 A股模拟跟单止盈止损处理"
    currency = summary.get("currency") or ""
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**明确结论：** 模拟盘已自动处理达到纪律线的持仓，共 {len(triggered)} 只。\n"
                    f"**账户状态：** 当前市值 **{summary['total_value']:.2f} {currency}**｜"
                    f"累计盈亏 **{summary['pnl']:+.2f} {currency}（{summary['pnl_pct']:+.2f}%）**｜"
                    f"剩余持仓 **{summary['positions_count']} 只**"
                ),
            },
        },
        {"tag": "hr"},
    ]
    for item in triggered:
        display_name = stock_display_name(str(item["code"]), str(item["name"]))
        trade = item.get("trade") or {}
        shares = float(trade.get("shares") or item.get("shares") or 0)
        amount = float(trade.get("amount") or (shares * float(item.get("price") or 0)))
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**{item['rule']}：{display_name}（{item['code']}）**\n"
                        f"买入价 **{item['avg_price']:.2f}**｜卖出价 **{item['price']:.2f}**｜"
                        f"卖出数量 **{shares:.6f}**｜卖出金额 **{amount:.2f} {currency}**\n"
                        f"本笔变化 **{item['pnl_pct']:+.2f}%**｜最高浮盈 **{item['highest_return_pct']:+.2f}%**\n"
                        f"**处理意见：** {item['reason']}"
                    ),
                },
            }
        )
    elements.append(
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": (
                        f"模拟纪律线：止损 {summary['stop_loss_pct']:.1f}%；止盈 {summary['take_profit_pct']:.1f}%；"
                        f"移动止盈回撤 {summary['trailing_drawdown_pct']:.1f}%。仅为模拟盘记录，不会真实下单。"
                    ),
                }
            ],
        }
    )
    return sanitize_card(
        {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "red" if has_stop_loss else "green",
                "title": {"tag": "plain_text", "content": title},
            },
            "elements": elements,
        }
    )


def build_idle_status_card(market: str, entries_count: int, now: datetime) -> dict[str, Any]:
    is_us = market == "us"
    return sanitize_card(
        {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue" if is_us else "green",
                "title": {
                    "tag": "plain_text",
                    "content": "🇺🇸 美股盘中监控｜运行状态" if is_us else "🇨🇳 A股盘中监控｜运行状态",
                },
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            "**明确结论：** 云端盘中监控已经正常运行，目前没有达到异动提醒门槛。\n"
                            "**处理意见：** 继续盯住精选名单，出现明显放量或价格异动时再推送提醒。\n"
                            f"**检查范围：** 已检查 {entries_count} 只精选标的　"
                            f"**检查时间：** {now.strftime('%Y-%m-%d %H:%M')}"
                        ),
                    },
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "这张状态卡用于确认云端盘中监控仍在运行；同一市场每天最多发送一次。",
                        }
                    ],
                },
            ],
        }
    )


def send_idle_status_once(state: dict[str, Any], market: str, entries_count: int, now: datetime) -> bool:
    state_key = f"{market}_intraday_idle"
    signature = f"{now.strftime('%Y-%m-%d')}|{market}|no_intraday_alert"
    status_state = state.setdefault("idle_status", {})
    if status_state.get(state_key) == signature:
        print("盘中运行状态卡今日已发送，跳过重复提醒")
        return False
    send_card(build_idle_status_card(market, entries_count, now))
    status_state[state_key] = signature
    status_state[f"{state_key}_at"] = now.isoformat(timespec="seconds")
    state["updated_at"] = now.isoformat(timespec="seconds")
    save_alert_state(state)
    return True


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
    risk_summary = apply_risk_controls(market, quotes, dry_run=dry_run)
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
        if risk_summary and risk_summary.get("triggered_count"):
            print(json.dumps(build_risk_control_card(market, risk_summary), ensure_ascii=False, indent=2))
            return
        print(json.dumps(build_alert_card(market, alerts), ensure_ascii=False, indent=2) if alerts else "没有达到推送门槛")
        return
    save_alert_state(state)
    if risk_summary and risk_summary.get("triggered_count"):
        send_card(build_risk_control_card(market, risk_summary))
        print(f"模拟跟单止盈止损处理已推送：{risk_summary['triggered_count']}只")
        return
    if not alerts:
        if intraday_status_on_idle_enabled():
            sent_status = send_idle_status_once(state, market, len(entries), now)
            if sent_status:
                print("盘中运行状态卡已推送")
                return
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
