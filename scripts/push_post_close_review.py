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

from integrations.card_language import confidence_text, stock_display_name
from integrations.daily_stock_selector import StockPick, select_daily_picks
from scripts.push_daily_strategy_cards import (
    build_status_card,
    fetch_market_indices,
    fetch_important_news,
    format_market_indices,
    format_important_news,
    generate_market_selection,
    load_state,
    market_label,
    market_state_key,
    save_state,
    send_card,
    send_status_card_once,
    status_on_skip_enabled,
    stock_strategy_cards_enabled,
)
from scripts.paper_trading import build_paper_element, mark_to_market
from scripts.push_strategy_digest import configure_console_encoding


def _latest_prices(market: str, codes: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    if not codes:
        return {}, []
    selection_profile = "us_contract" if market == "us" else "standard"
    picks, errors = select_daily_picks(
        codes,
        market=market,
        count=len(codes),
        include_reserves=0,
        minimum_liquidity=0,
        selection_profile=selection_profile,
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
    market_indices: list[dict[str, Any]] | None = None,
    important_news: list[dict[str, Any]] | None = None,
    errors: list[str],
    session: str = "close",
) -> dict[str, Any]:
    is_us = market == "us"
    title = "🇺🇸 美股收盘复盘与次日预案" if is_us else "🇰🇷 韩股收盘复盘与次日预案"
    template = "indigo" if is_us else "turquoise"
    summary_label, average, wins, total = _summary(results)
    summary_text = (
        f"平均表现 **{average:+.2f}%**｜上涨 **{wins}/{total}**"
        if average is not None
        else "尚无可比入选价格，本次开始建立跟踪基线"
    )
    index_text = format_market_indices(market_indices or [])
    news_text = format_important_news(important_news or [])
    conclusion_label = "复盘结论"
    stats_label = "当日统计"
    environment_label = "收盘环境"
    previous_section = "**今日精选复盘**"
    next_section = "**明日优先关注名单（盘前再次确认）**"
    current_price_label = "收盘"
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**{conclusion_label}：** {summary_label}\n"
                    f"**{stats_label}：** {summary_text}\n"
                    f"**大盘指数：** {index_text}\n"
                    f"**重要快讯：** {news_text}\n"
                    f"**{environment_label}：** {next_picks[0].regime if next_picks else '未知'}　"
                    f"**生成：** {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                ),
            },
        },
        {"tag": "hr"},
        {"tag": "div", "text": {"tag": "lark_md", "content": previous_section}},
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
                        f"{current_price_label} **{item['current_price']:.2f}**　当日 **{item['day_change']:+.2f}%**"
                    ),
                },
            }
        )
    elements.extend(
        [
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": next_section}},
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
                        f"20日动量 **{pick.return_20d:+.2f}%**｜相对基准 **{pick.relative_strength_20d:+.2f}%**｜"
                        f"资金链路 **{pick.capital_trace_score:.0f}/100**"
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
    note_text = (
        f"复盘使用完整收盘数据（{data_date}）。次日预备名单不是最终开盘策略，"
        "盘前确认通过后直接按重点关注名单推送。"
    )
    elements.append(
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": note_text,
                }
            ],
        }
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": template, "title": {"tag": "plain_text", "content": title}},
        "elements": elements,
    }


def append_paper_review_element(
    card: dict[str, Any],
    market: str,
    latest: dict[str, dict[str, Any]],
    *,
    dry_run: bool,
) -> None:
    paper_summary = mark_to_market(market, latest, dry_run=dry_run)
    paper_element = build_paper_element(paper_summary, mode="review")
    if not paper_element:
        return
    elements = card.setdefault("elements", [])
    insert_at = max(0, len(elements) - 1)
    elements.insert(insert_at, {"tag": "hr"})
    elements.insert(insert_at + 1, paper_element)


def review_signature(
    market: str,
    results: list[dict[str, Any]],
    next_picks: list[StockPick],
    *,
    session: str = "close",
) -> str:
    data_date = next_picks[0].data_date if next_picks else "none"
    return "|".join([market, session, data_date, *(item["code"] for item in results), *(pick.code for pick in next_picks)])


def run_once(*, market: str, dry_run: bool = False, force: bool = False, session: str = "close") -> None:
    load_dotenv(ROOT / ".env")
    if not stock_strategy_cards_enabled():
        print(
            "Stock post-close reviews are disabled by FEISHU_STOCK_CARDS_ENABLED=false; "
            "use scripts/push_binance_long_signals.py for Binance stock contract signals."
        )
        return
    state = load_state()
    state_key = market_state_key(market)
    review_name = "收盘复盘"
    signature_key = "review_signature"
    reviewed_at_key = "reviewed_at"
    review_data_date_key = "review_data_date"
    preview_codes_key = "next_preview_codes"
    results_key = "review_results"
    previous = state.get(state_key, {})
    previous_codes = list(previous.get("codes") or [])
    previous_picks = list(previous.get("picks") or [])
    if not previous_picks and previous_codes:
        previous_picks = [{"code": code, "name": code, "signal_price": 0} for code in previous_codes]

    latest, quote_errors = _latest_prices(market, previous_codes)
    results = evaluate_previous(previous_picks, latest)
    next_picks, selection_errors = generate_market_selection(market)
    if not next_picks:
        print(f"{state_key.upper()} 未生成有效名单，跳过本次{review_name}推送")
        if not dry_run and status_on_skip_enabled():
            sent_status = send_status_card_once(
                state,
                state_key=state_key,
                task_key="review_empty",
                reason="no_next_picks",
                card=build_status_card(
                    title="🇺🇸 美股收盘复盘｜运行状态" if market == "us" else "🇰🇷 韩股收盘复盘｜运行状态",
                    market_label=market_label(market),
                    conclusion=f"云端{review_name}任务已经正常执行，本次没有生成有效名单。",
                    action="不推送空复盘卡，继续保留上一版跟踪名单，等待下一次有效信号。",
                    details=[*quote_errors, *selection_errors] or ["数据源或筛选条件未达到策略门槛"],
                    template="turquoise",
                ),
            )
            if sent_status:
                print(f"{state_key.upper()} {review_name}状态卡已推送")
        return
    errors = [*quote_errors, *selection_errors]
    card = build_review_card(
        market,
        results,
        next_picks,
        previous_codes,
        market_indices=fetch_market_indices(market),
        important_news=fetch_important_news(market),
        errors=errors,
        session=session,
    )
    signature = review_signature(market, results, next_picks, session=session)

    if dry_run:
        append_paper_review_element(card, market, latest, dry_run=True)
        print(json.dumps(card, ensure_ascii=False, indent=2))
        return
    if not force and previous.get(signature_key) == signature:
        print(f"{state_key.upper()} {review_name}数据与结论未变化，跳过重复推送")
        return
    append_paper_review_element(card, market, latest, dry_run=False)
    send_card(card)
    previous[signature_key] = signature
    previous[reviewed_at_key] = datetime.now().isoformat(timespec="seconds")
    previous[review_data_date_key] = next_picks[0].data_date if next_picks else None
    previous[preview_codes_key] = [pick.code for pick in next_picks]
    previous[results_key] = results
    state[state_key] = previous
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)
    print(f"{state_key.upper()} {review_name}与预案已推送")


def main() -> int:
    configure_console_encoding()
    parser = argparse.ArgumentParser(description="收盘复盘并生成次日预备策略")
    parser.add_argument("--market", choices=("kr", "us"), required=True)
    parser.add_argument("--session", choices=("close",), default="close")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--schedule", action="store_true")
    args = parser.parse_args()
    if not args.schedule:
        run_once(market=args.market, dry_run=args.dry_run, force=args.force, session=args.session)
        return 0

    load_dotenv(ROOT / ".env")
    kr_time = os.getenv("KR_REVIEW_SCHEDULE_TIME", "14:50").strip()
    us_time = os.getenv("US_REVIEW_SCHEDULE_TIME", "06:30").strip()
    schedule.every().day.at(kr_time).do(run_once, market="kr", dry_run=args.dry_run, force=args.force, session="close")
    schedule.every().day.at(us_time).do(run_once, market="us", dry_run=args.dry_run, force=args.force, session="close")
    print(f"收盘复盘任务已启动：韩股 {kr_time}，美股 {us_time}")
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
