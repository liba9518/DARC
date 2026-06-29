"""Post-close review cards and preliminary next-session strategy."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import schedule
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from integrations.a_stock_direct import fetch_tencent_quotes
from integrations.card_language import confidence_text, stock_display_name
from integrations.daily_stock_selector import StockPick, select_daily_picks
from scripts.push_daily_strategy_cards import (
    DEFAULT_A_POOL,
    DEFAULT_US_POOL,
    generate_market_selection,
    load_state,
    save_state,
    send_card,
)
from scripts.push_strategy_digest import configure_console_encoding, parse_tickers


def _latest_prices(market: str, codes: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    if not codes:
        return {}, []
    if market == "cn":
        try:
            quotes = fetch_tencent_quotes(codes)
            return {
                str(item["code"]): {
                    "price": float(item["price"]),
                    "day_change": float(item.get("pct_change") or 0),
                    "name": str(item.get("name") or item["code"]),
                }
                for item in quotes
            }, []
        except Exception as exc:
            return {}, [f"A股收盘行情获取失败：{exc}"]

    picks, errors = select_daily_picks(
        codes,
        market="us",
        count=len(codes),
        include_reserves=0,
        minimum_liquidity=0,
    )
    return {
        pick.code: {
            "price": pick.price,
            "day_change": pick.day_change,
            "name": pick.name,
        }
        for pick in picks
    }, errors


def evaluate_previous(
    previous_picks: list[dict[str, Any]],
    latest: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    results = []
    for item in previous_picks:
        code = str(item.get("code") or "").upper()
        quote = latest.get(code)
        signal_price = float(item.get("signal_price") or 0)
        current_price = float(quote.get("price") or 0) if quote else 0
        performance = (
            round(((current_price / signal_price) - 1) * 100, 4)
            if signal_price > 0 and current_price > 0
            else None
        )
        results.append(
            {
                "code": code,
                "name": str((quote or {}).get("name") or item.get("name") or code),
                "signal_price": signal_price,
                "current_price": current_price,
                "performance": performance,
                "day_change": float((quote or {}).get("day_change") or 0),
            }
        )
    return results


def _summary(results: list[dict[str, Any]]) -> tuple[str, float | None, int, int]:
    measurable = [item for item in results if item["performance"] is not None]
    if not measurable:
        return "首次建立复盘基线", None, 0, 0
    average = sum(float(item["performance"]) for item in measurable) / len(measurable)
    wins = sum(float(item["performance"]) > 0 for item in measurable)
    label = "策略表现明确有效" if average > 0.5 else "策略表现不理想，需要收紧" if average < -0.5 else "策略表现稳定"
    return label, average, wins, len(measurable)


def build_review_card(
    market: str,
    results: list[dict[str, Any]],
    next_picks: list[StockPick],
    previous_codes: list[str],
    *,
    errors: list[str],
) -> dict[str, Any]:
    is_us = market == "us"
    title = "🇺🇸 美股收盘复盘与次日预案" if is_us else "🇨🇳 A股收盘复盘与次日预案"
    template = "indigo" if is_us else "turquoise"
    summary_label, average, wins, total = _summary(results)
    summary_text = (
        f"平均表现 **{average:+.2f}%**｜上涨 **{wins}/{total}**"
        if average is not None
        else "尚无可比入选价格，本次开始建立跟踪基线"
    )
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**复盘结论：** {summary_label}\n"
                    f"**当日统计：** {summary_text}\n"
                    f"**收盘环境：** {next_picks[0].regime if next_picks else '未知'}　"
                    f"**生成：** {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                ),
            },
        },
        {"tag": "hr"},
        {"tag": "div", "text": {"tag": "lark_md", "content": "**今日精选复盘**"}},
    ]
    for item in results:
        display_name = stock_display_name(item["code"], item["name"])
        performance = item["performance"]
        result_text = f"{performance:+.2f}%" if performance is not None else "待建立基线"
        icon = "🟢" if performance is not None and performance > 0 else "🔴" if performance is not None and performance < 0 else "⚪"
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"{icon} **{display_name}（{item['code']}）**　"
                        f"策略结果 **{result_text}**\n"
                        f"收盘 **{item['current_price']:.2f}**　当日 **{item['day_change']:+.2f}%**"
                    ),
                },
            }
        )
    elements.extend(
        [
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": "**明日优先关注名单（盘前再次确认）**"}},
        ]
    )
    previous = set(previous_codes)
    next_codes = {pick.code for pick in next_picks}
    for index, pick in enumerate(next_picks, start=1):
        status = "继续重点关注" if pick.code in previous else "明确加入关注"
        display_name = stock_display_name(pick.code, pick.name)
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**{index}. {display_name}（{pick.code}）**　"
                        f"{status}｜综合得分 **{pick.score:.1f}**｜"
                        f"判断把握 **{confidence_text(pick.confidence)}**\n"
                        f"20日动量 **{pick.return_20d:+.2f}%**｜相对基准 **{pick.relative_strength_20d:+.2f}%**"
                    ),
                },
            }
        )
    removed = [
        f"{stock_display_name(code, code)}（{code}）"
        for code in previous_codes
        if code not in next_codes
    ]
    if removed:
        elements.append(
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**暂时移出：** {', '.join(removed)}"}}
        )
    if errors:
        elements.append(
            {
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": f"部分数据降级：{len(errors)} 项。"}],
            }
        )
    data_date = next_picks[0].data_date if next_picks else "无"
    elements.append(
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": (
                        f"复盘使用完整收盘数据（{data_date}）。次日预备名单不是最终开盘策略，"
                        "盘前确认通过后直接按重点关注名单推送。"
                    ),
                }
            ],
        }
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": template, "title": {"tag": "plain_text", "content": title}},
        "elements": elements,
    }


def review_signature(market: str, results: list[dict[str, Any]], next_picks: list[StockPick]) -> str:
    data_date = next_picks[0].data_date if next_picks else "none"
    return "|".join([market, data_date, *(item["code"] for item in results), *(pick.code for pick in next_picks)])


def run_once(*, market: str, dry_run: bool = False, force: bool = False) -> None:
    load_dotenv(ROOT / ".env")
    state = load_state()
    state_key = "us" if market == "us" else "a"
    previous = state.get(state_key, {})
    previous_codes = list(previous.get("codes") or [])
    previous_picks = list(previous.get("picks") or [])
    if not previous_picks and previous_codes:
        previous_picks = [{"code": code, "name": code, "signal_price": 0} for code in previous_codes]

    latest, quote_errors = _latest_prices(market, previous_codes)
    results = evaluate_previous(previous_picks, latest)
    next_picks, selection_errors = generate_market_selection(market)
    if not next_picks:
        print(f"{state_key.upper()} 未生成次日有效名单，跳过本次复盘推送")
        return
    errors = [*quote_errors, *selection_errors]
    card = build_review_card(market, results, next_picks, previous_codes, errors=errors)
    signature = review_signature(market, results, next_picks)

    if dry_run:
        print(json.dumps(card, ensure_ascii=False, indent=2))
        return
    if not force and previous.get("review_signature") == signature:
        print(f"{state_key.upper()} 收盘数据与复盘结论未变化，跳过重复推送")
        return
    send_card(card)
    previous["review_signature"] = signature
    previous["reviewed_at"] = datetime.now().isoformat(timespec="seconds")
    previous["review_data_date"] = next_picks[0].data_date if next_picks else None
    previous["next_preview_codes"] = [pick.code for pick in next_picks]
    previous["review_results"] = results
    state[state_key] = previous
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)
    print(f"{state_key.upper()} 收盘复盘与次日预案已推送")


def main() -> int:
    configure_console_encoding()
    parser = argparse.ArgumentParser(description="收盘复盘并生成次日预备策略")
    parser.add_argument("--market", choices=("cn", "us"), required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--schedule", action="store_true")
    args = parser.parse_args()
    if not args.schedule:
        run_once(market=args.market, dry_run=args.dry_run, force=args.force)
        return 0

    load_dotenv(ROOT / ".env")
    a_time = os.getenv("A_REVIEW_SCHEDULE_TIME", "15:20").strip()
    us_time = os.getenv("US_REVIEW_SCHEDULE_TIME", "06:30").strip()
    schedule.every().day.at(a_time).do(run_once, market="cn", dry_run=args.dry_run, force=args.force)
    schedule.every().day.at(us_time).do(run_once, market="us", dry_run=args.dry_run, force=args.force)
    print(f"收盘复盘任务已启动：A股 {a_time}，美股 {us_time}")
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
