"""Generate and push separate US/A-share daily top-three Feishu cards."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from dataclasses import replace
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
import schedule
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from integrations.a_stock_direct import fetch_tencent_quotes
from integrations.card_language import confidence_text, sanitize_card, stock_display_name
from integrations.daily_stock_selector import StockPick, select_daily_picks
from scripts.push_strategy_digest import configure_console_encoding, parse_tickers


DEFAULT_US_POOL = "NVDA,MSFT,GOOGL,AMZN,META,AVGO,AMD,ANET,VRT,MU,TSM,PLTR"
DEFAULT_A_POOL = "600519,300750,002594,601138,000063,002475,300308,688041,600276,601318,600036,000333"
STATE_PATH = ROOT / "data" / "daily_card_state.json"


def _sign(secret: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    signature = base64.b64encode(
        hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    ).decode("utf-8")
    return {"timestamp": timestamp, "sign": signature}


def build_strategy_card(
    title: str,
    market_label: str,
    picks: list[StockPick],
    *,
    template: str,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**今日结论：** 以下三只已经通过趋势、强弱和成交活跃度筛选，优先关注。\n"
                    f"**判断方法：** 市场环境 + 多周期趋势 + 相对强度 + 流动性 + 风险一致性\n"
                    f"**市场：** {market_label}　**环境：** {picks[0].regime if picks else '未知'}　"
                    f"**生成：** {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                ),
            },
        },
        {"tag": "hr"},
    ]
    for index, pick in enumerate(picks, start=1):
        display_name = stock_display_name(pick.code, pick.name)
        code_suffix = f"（{pick.code}）"
        reason_text = "；".join(pick.reasons)
        risk_text = "；".join(pick.risks)
        elements.extend(
            [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**{index}. {display_name}{code_suffix}**　"
                            f"综合得分 **{pick.score:.1f}**　"
                            f"判断把握 **{confidence_text(pick.confidence)}（{pick.confidence_points}/10）**　"
                            f"结论 **{'重点关注' if pick.eligible else '继续观察'}**\n"
                            f"价格 **{pick.price:.2f}**　当日 **{pick.day_change:+.2f}%**　"
                            f"5日 **{pick.return_5d:+.2f}%**　20日 **{pick.return_20d:+.2f}%**\n"
                            f"相对基准 **{pick.relative_strength_20d:+.2f}%**　"
                            f"成交活跃度 **{pick.volume_ratio:.2f}**　强弱指标 **{pick.rsi14:.1f}**\n"
                            f"✅ 判断：{reason_text}\n⚠️ 执行要点：{risk_text}"
                        ),
                    },
                },
                {"tag": "hr"},
            ]
        )
    if not picks:
        elements.append(
            {"tag": "div", "text": {"tag": "lark_md", "content": "今日数据不足，未生成精选名单。"}}
        )
    if errors:
        elements.append(
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"部分候选数据降级：{len(errors)} 项；不影响已展示名单。",
                    }
                ],
            }
        )
    data_date = picks[0].data_date if picks else "无"
    elements.append(
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": f"盘前判断基于上一完整交易日（{data_date}），结论明确，但仍需按执行要点控制风险。",
                }
            ],
        }
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": elements,
    }


def send_card(card: dict[str, Any]) -> None:
    webhook = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    if not webhook:
        raise RuntimeError("未配置 FEISHU_WEBHOOK_URL")
    payload: dict[str, Any] = {"msg_type": "interactive", "card": sanitize_card(card)}
    secret = os.getenv("FEISHU_WEBHOOK_SECRET", "").strip()
    if secret:
        payload.update(_sign(secret))
    response = requests.post(webhook, json=payload, timeout=30)
    response.raise_for_status()
    result = response.json()
    if result.get("code", result.get("StatusCode", 0)) not in {0, None}:
        raise RuntimeError(f"飞书卡片推送失败: {result}")


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_PATH)


def stabilize_picks(
    ranked: list[StockPick],
    previous_codes: list[str],
    *,
    count: int,
    retention_bonus: float,
) -> list[StockPick]:
    previous = set(previous_codes)
    eligible = [pick for pick in ranked if pick.eligible]
    pool = eligible if len(eligible) >= count else ranked
    stable = sorted(
        pool,
        key=lambda pick: (-(pick.score + (retention_bonus if pick.code in previous else 0)), pick.code),
    )
    return stable[:count]


def apply_a_share_realtime_quotes(
    picks: list[StockPick],
    quotes: list[dict[str, Any]],
) -> list[StockPick]:
    quote_map = {str(item["code"]): item for item in quotes}
    result = []
    for pick in picks:
        quote = quote_map.get(pick.code)
        if quote and float(quote.get("price") or 0) > 0:
            result.append(
                replace(
                    pick,
                    price=round(float(quote["price"]), 2),
                    day_change=round(float(quote.get("pct_change") or pick.day_change), 2),
                )
            )
        else:
            result.append(pick)
    return result


def is_a_share_preopen() -> bool:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return now.time() < dt_time(9, 30)


def selection_signature(picks: list[StockPick]) -> str:
    return "|".join([picks[0].data_date if picks else "none", *(pick.code for pick in picks)])


def pick_snapshot(pick: StockPick) -> dict[str, Any]:
    return {
        "code": pick.code,
        "name": pick.name,
        "signal_price": pick.price,
        "score": pick.score,
        "confidence": pick.confidence,
        "confidence_points": pick.confidence_points,
        "regime": pick.regime,
        "data_date": pick.data_date,
    }


def generate_market_selection(market: str) -> tuple[list[StockPick], list[str]]:
    count = max(1, int(os.getenv("DAILY_CARD_PICK_COUNT", "3")))
    retention_bonus = max(0.0, float(os.getenv("DAILY_CARD_RETENTION_BONUS", "4")))
    state = load_state()

    if market == "us":
        pool = parse_tickers(os.getenv("US_STRATEGY_POOL", DEFAULT_US_POOL))
        ranked, errors = select_daily_picks(
            pool,
            market="us",
            count=count,
            minimum_liquidity=float(os.getenv("US_MIN_DOLLAR_VOLUME", "20000000")),
        )
        picks = stabilize_picks(
            ranked,
            list(state.get("us", {}).get("codes", [])),
            count=count,
            retention_bonus=retention_bonus,
        )
        return picks, errors

    pool = parse_tickers(os.getenv("A_STRATEGY_POOL", DEFAULT_A_POOL))
    quotes = fetch_tencent_quotes(pool)
    names = {str(item["code"]): str(item["name"]) for item in quotes}
    ranked, errors = select_daily_picks(
        pool,
        market="cn",
        names=names,
        count=count,
        minimum_liquidity=float(os.getenv("A_MIN_TURNOVER_CNY", "100000000")),
    )
    picks = stabilize_picks(
        ranked,
        list(state.get("a", {}).get("codes", [])),
        count=count,
        retention_bonus=retention_bonus,
    )
    return apply_a_share_realtime_quotes(picks, quotes) if is_a_share_preopen() else picks, errors


def generate_selections() -> tuple[list[StockPick], list[StockPick], list[str], list[str]]:
    us_picks, us_errors = generate_market_selection("us")
    a_picks, a_errors = generate_market_selection("cn")
    return us_picks, a_picks, us_errors, a_errors


def generate_cards() -> tuple[dict[str, Any], dict[str, Any]]:
    count = max(1, int(os.getenv("DAILY_CARD_PICK_COUNT", "3")))
    us_picks, a_picks, us_errors, a_errors = generate_selections()

    us_card = build_strategy_card(
        f"🇺🇸 美股盘前策略｜精选{count}只",
        "美国股票",
        us_picks,
        template="blue",
        errors=us_errors,
    )
    a_card = build_strategy_card(
        f"🇨🇳 A股盘前策略｜精选{count}只",
        "沪深A股",
        a_picks,
        template="green",
        errors=a_errors,
    )
    return us_card, a_card


def run_once(*, market: str = "both", dry_run: bool = False, force: bool = False) -> None:
    load_dotenv(ROOT / ".env")
    count = max(1, int(os.getenv("DAILY_CARD_PICK_COUNT", "3")))
    markets = ("cn", "us") if market == "both" else (market,)
    cards: dict[str, dict[str, Any]] = {}
    picks_by_market: dict[str, list[StockPick]] = {}
    for selected_market in markets:
        picks, errors = generate_market_selection(selected_market)
        picks_by_market[selected_market] = picks
        if selected_market == "us":
            cards[selected_market] = build_strategy_card(
                f"🇺🇸 美股盘前策略｜精选{count}只",
                "美国股票",
                picks,
                template="blue",
                errors=errors,
            )
        else:
            cards[selected_market] = build_strategy_card(
                f"🇨🇳 A股盘前策略｜精选{count}只",
                "沪深A股",
                picks,
                template="green",
                errors=errors,
            )
    if dry_run:
        print(json.dumps(cards, ensure_ascii=False, indent=2))
        return
    state = load_state()
    sent = []
    for selected_market in markets:
        state_key = "us" if selected_market == "us" else "a"
        picks = picks_by_market[selected_market]
        if not picks:
            print(f"{state_key.upper()} 未选出有效标的，跳过本次推送")
            continue
        signature = selection_signature(picks)
        if not force and state.get(state_key, {}).get("signature") == signature:
            print(f"{state_key.upper()} 行情日期与名单未变化，跳过重复推送")
            continue
        send_card(cards[selected_market])
        state[state_key] = {
            "signature": signature,
            "codes": [pick.code for pick in picks],
            "data_date": picks[0].data_date if picks else None,
            "picks": [pick_snapshot(pick) for pick in picks],
            "pushed_at": datetime.now().isoformat(timespec="seconds"),
        }
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        save_state(state)
        sent.append(state_key)
        if len(markets) > 1:
            time.sleep(1)
    print(f"盘前策略卡片处理完成：{', '.join(sent) if sent else '无新增推送'}")


def main() -> int:
    configure_console_encoding()
    parser = argparse.ArgumentParser(description="生成美股/A股每日三只精选飞书卡片")
    parser.add_argument("--dry-run", action="store_true", help="只生成JSON，不推送")
    parser.add_argument("--schedule", action="store_true", help="按A/美股盘前时间常驻执行")
    parser.add_argument("--force", action="store_true", help="即使行情与名单未变化也强制推送")
    parser.add_argument("--market", choices=("cn", "us", "both"), default="both", help="只处理指定市场")
    args = parser.parse_args()
    if not args.schedule:
        run_once(market=args.market, dry_run=args.dry_run, force=args.force)
        return 0

    load_dotenv(ROOT / ".env")
    a_time = os.getenv("A_CARD_SCHEDULE_TIME", "09:10").strip()
    us_time = os.getenv("US_CARD_SCHEDULE_TIME", "21:10").strip()
    schedule.every().day.at(a_time).do(run_once, market="cn", dry_run=args.dry_run, force=args.force)
    schedule.every().day.at(us_time).do(run_once, market="us", dry_run=args.dry_run, force=args.force)
    if os.getenv("DAILY_CARD_RUN_IMMEDIATELY", "true").lower() == "true":
        run_once(market=args.market, dry_run=args.dry_run, force=args.force)
    print(f"盘前卡片任务已启动：A股 {a_time}，美股 {us_time}")
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
