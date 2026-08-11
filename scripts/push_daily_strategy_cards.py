"""Generate and push separate US/Korea daily Feishu strategy cards."""

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
import yfinance as yf
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from integrations.card_language import confidence_text, sanitize_card, stock_display_name
from integrations.daily_stock_selector import StockPick, select_daily_picks
from src.services.intelligence_service import IntelligenceService
from scripts.paper_trading import build_paper_element, rebalance_to_picks
from scripts.push_strategy_digest import configure_console_encoding, parse_tickers


DEFAULT_US_POOL = "NVDA,TSLA,AAPL,MSFT,AMZN,GOOGL,META,COIN,MSTR,SPY,QQQ,AMD,AVGO"
DEFAULT_KR_POOL = (
    "005930.KS,000660.KS,373220.KS,005380.KS,035420.KS,"
    "051910.KS,006400.KS,035720.KQ,247540.KQ,091990.KQ"
)
DEFAULT_US_PICK_COUNT = 0
DEFAULT_KR_PICK_COUNT = 0
STATE_PATH = ROOT / "data" / "daily_card_state.json"
FEISHU_WEBHOOK_ATTEMPTS = 3
FEISHU_WEBHOOK_RETRY_DELAYS = (2.0, 5.0)
FEISHU_WEBHOOK_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


US_INDEX_SYMBOLS = (
    ("^GSPC", "标普五百"),
    ("^IXIC", "纳斯达克"),
    ("^DJI", "道琼斯"),
)
KR_INDEX_SYMBOLS = (
    ("^KS11", "KOSPI"),
    ("^KQ11", "KOSDAQ"),
)
KR_STOCK_NAMES = {
    "005930.KS": "Samsung Electronics",
    "000660.KS": "SK hynix",
    "373220.KS": "LG Energy Solution",
    "005380.KS": "Hyundai Motor",
    "035420.KS": "NAVER",
    "051910.KS": "LG Chem",
    "006400.KS": "Samsung SDI",
    "035720.KQ": "Kakao",
    "247540.KQ": "Ecopro BM",
    "091990.KQ": "Celltrion Healthcare",
}


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
    market_indices: list[dict[str, Any]] | None = None,
    important_news: list[dict[str, Any]] | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    index_text = format_market_indices(market_indices or [])
    news_text = format_important_news(important_news or [])
    if picks:
        pick_label = "该标的" if len(picks) == 1 else f"以下{len(picks)}只"
        conclusion = f"{pick_label}已经通过趋势、强弱和成交活跃度筛选，优先关注。"
    else:
        conclusion = "候选池暂未触发有效信号，本次不固定凑数。"
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**今日结论：** {conclusion}\n"
                    f"**判断方法：** 市场环境 + 多周期趋势 + 相对强度 + 资金链路 + 风险一致性\n"
                    f"**大盘指数：** {index_text}\n"
                    f"**重要快讯：** {news_text}\n"
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
                            f"资金链路 **{pick.capital_trace_score:.0f}/100**　"
                            f"承接判断 **{pick.capital_trace_label}**　"
                            f"上涨成交占优 **{pick.accumulation_20d:+.1f}%**\n"
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
    payload: dict[str, Any] = {"msg_type": "interactive", "card": sanitize_card(card)}
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


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def stock_strategy_cards_enabled() -> bool:
    if _env_flag("BINANCE_ONLY_FEISHU", "true"):
        return False
    return _env_flag("FEISHU_STOCK_CARDS_ENABLED", "false")


def market_pick_count(market: str) -> int:
    market_key = {
        "us": "US_DAILY_CARD_PICK_COUNT",
        "kr": "KR_DAILY_CARD_PICK_COUNT",
    }.get(market, "DAILY_CARD_PICK_COUNT")
    default = {
        "us": DEFAULT_US_PICK_COUNT,
        "kr": DEFAULT_KR_PICK_COUNT,
    }.get(market, 0)
    raw_value = os.getenv(market_key) or str(default)
    try:
        return max(0, int(raw_value))
    except ValueError:
        return default


def market_state_key(market: str) -> str:
    return {"us": "us", "kr": "kr"}.get(market, market)


def market_label(market: str) -> str:
    return {"us": "美国股票", "kr": "韩国股票"}.get(market, market.upper())


def strategy_card_title(market: str, picks: list[StockPick], count: int) -> str:
    label = {
        "us": "🇺🇸 美股盘前策略",
        "kr": "🇰🇷 韩股盘前策略",
    }.get(market, f"{market.upper()} 盘前策略")
    suffix = f"精选{count}只" if count > 0 else f"信号触发{len(picks)}只"
    return f"{label}｜{suffix}"


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def fetch_yfinance_market_indices(symbols: tuple[tuple[str, str], ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, name in symbols:
        try:
            history = yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=True)
        except Exception:
            continue
        if history is None or history.empty or "Close" not in history:
            continue
        close = history["Close"].dropna().astype(float)
        if close.empty:
            continue
        price = float(close.iloc[-1])
        previous = float(close.iloc[-2]) if len(close) >= 2 else 0.0
        pct_change = (price / previous - 1) * 100 if previous > 0 else 0.0
        rows.append({"name": name, "price": price, "pct_change": pct_change})
    return rows


def fetch_us_market_indices() -> list[dict[str, Any]]:
    return fetch_yfinance_market_indices(US_INDEX_SYMBOLS)


def fetch_kr_market_indices() -> list[dict[str, Any]]:
    return fetch_yfinance_market_indices(KR_INDEX_SYMBOLS)


def fetch_market_indices(market: str) -> list[dict[str, Any]]:
    if market == "us":
        return fetch_us_market_indices()
    if market == "kr":
        return fetch_kr_market_indices()
    return []


def format_market_indices(indices: list[dict[str, Any]]) -> str:
    if not indices:
        return "暂未取到大盘指数，策略推送继续执行"
    return "；".join(
        f"{item['name']} {float(item['price']):.2f}（{float(item.get('pct_change') or 0):+.2f}%）"
        for item in indices[:3]
    )


def fetch_important_news(market: str, *, limit: int = 3) -> list[dict[str, Any]]:
    try:
        service = IntelligenceService()
        markets = [market]
        if market in {"cn", "us", "kr"}:
            markets.append("global")
        collected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for selected_market in markets:
            rows = service.list_items(scope_type="market", market=selected_market, days=2, page=1, page_size=limit)
            for item in rows.get("items") or []:
                url = str(item.get("url") or "")
                title = str(item.get("title") or "").strip()
                key = url or title
                if not title or key in seen:
                    continue
                seen.add(key)
                collected.append(item)
                if len(collected) >= limit:
                    return collected
        return collected[:limit]
    except Exception:
        return []


def format_important_news(items: list[dict[str, Any]]) -> str:
    if not items:
        return "暂无新的重要快讯，按既有策略信号执行"
    titles = []
    for item in items[:3]:
        source = str(item.get("source_name") or item.get("source") or "快讯").strip()
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        titles.append(f"{source}：{title[:48]}")
    return "；".join(titles) if titles else "暂无新的重要快讯，按既有策略信号执行"


def status_on_skip_enabled() -> bool:
    return _env_flag("FEISHU_STATUS_ON_SKIP")


def build_status_card(
    *,
    title: str,
    market_label: str,
    conclusion: str,
    action: str,
    details: list[str] | None = None,
    template: str = "grey",
) -> dict[str, Any]:
    lines = [
        f"**明确结论：** {conclusion}",
        f"**处理意见：** {action}",
        f"**市场：** {market_label}　**检查时间：** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    if details:
        lines.append("**补充说明：** " + "；".join(details[:3]))
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "\n".join(lines),
                },
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "这张状态卡只在关键任务没有生成有效名单时发送，用来确认云端自动化仍在运行。",
                    }
                ],
            },
        ],
    }


def send_status_card_once(
    state: dict[str, Any],
    *,
    state_key: str,
    task_key: str,
    reason: str,
    card: dict[str, Any],
) -> bool:
    today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    signature = f"{today}|{state_key}|{task_key}|{reason}"
    section = state.setdefault(state_key, {})
    status_key = f"{task_key}_status_signature"
    if section.get(status_key) == signature:
        print(f"{state_key.upper()} {task_key} 状态卡今日已发送，跳过重复提醒")
        return False
    send_card(card)
    section[status_key] = signature
    section[f"{task_key}_status_at"] = datetime.now().isoformat(timespec="seconds")
    section[f"{task_key}_status_reason"] = reason
    state[state_key] = section
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)
    return True


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
    stable = sorted(
        eligible,
        key=lambda pick: (-(pick.score + (retention_bonus if pick.code in previous else 0)), pick.code),
    )
    if count <= 0:
        return stable
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
        "capital_trace_score": pick.capital_trace_score,
        "capital_trace_label": pick.capital_trace_label,
        "accumulation_20d": pick.accumulation_20d,
        "data_date": pick.data_date,
    }


def append_paper_trading_element(
    card: dict[str, Any],
    market: str,
    picks: list[StockPick],
    *,
    dry_run: bool,
) -> None:
    paper_summary = rebalance_to_picks(market, picks, dry_run=dry_run)
    paper_element = build_paper_element(paper_summary, mode="rebalance")
    if not paper_element:
        return
    elements = card.setdefault("elements", [])
    insert_at = max(0, len(elements) - 1)
    elements.insert(insert_at, {"tag": "hr"})
    elements.insert(insert_at + 1, paper_element)


def generate_market_selection(market: str) -> tuple[list[StockPick], list[str]]:
    count = market_pick_count(market)
    retention_bonus = max(0.0, float(os.getenv("DAILY_CARD_RETENTION_BONUS", "4")))
    state = load_state()

    if market == "us":
        pool = parse_tickers(os.getenv("US_STRATEGY_POOL", DEFAULT_US_POOL))
        ranked, errors = select_daily_picks(
            pool,
            market="us",
            count=count,
            minimum_liquidity=float(os.getenv("US_MIN_DOLLAR_VOLUME", "10000000")),
            selection_profile="us_quality",
            include_reserves=0,
            eligible_only=True,
        )
        picks = stabilize_picks(
            ranked,
            list(state.get("us", {}).get("codes", [])),
            count=count,
            retention_bonus=retention_bonus,
        )
        return picks, errors

    if market == "kr":
        pool = parse_tickers(os.getenv("KR_STRATEGY_POOL") or os.getenv("KR_SIGNAL_POOL") or DEFAULT_KR_POOL)
        ranked, errors = select_daily_picks(
            pool,
            market="kr",
            names=KR_STOCK_NAMES,
            count=count,
            minimum_liquidity=float(os.getenv("KR_MIN_DAILY_TURNOVER_KRW", "5000000000")),
            include_reserves=0,
            eligible_only=True,
        )
        picks = stabilize_picks(
            ranked,
            list(state.get("kr", {}).get("codes", [])),
            count=count,
            retention_bonus=retention_bonus,
        )
        return picks, errors

    raise ValueError(f"Unsupported strategy market: {market}")


def generate_selections() -> tuple[list[StockPick], list[StockPick], list[str], list[str]]:
    us_picks, us_errors = generate_market_selection("us")
    kr_picks, kr_errors = generate_market_selection("kr")
    return us_picks, kr_picks, us_errors, kr_errors


def generate_cards() -> tuple[dict[str, Any], dict[str, Any]]:
    us_picks, kr_picks, us_errors, kr_errors = generate_selections()
    us_indices = fetch_market_indices("us")
    kr_indices = fetch_market_indices("kr")
    us_news = fetch_important_news("us")
    kr_news = fetch_important_news("kr")

    count = market_pick_count("us")
    us_card = build_strategy_card(
        strategy_card_title("us", us_picks, count),
        "美国股票",
        us_picks,
        template="blue",
        market_indices=us_indices,
        important_news=us_news,
        errors=us_errors,
    )
    count = market_pick_count("kr")
    kr_card = build_strategy_card(
        strategy_card_title("kr", kr_picks, count),
        market_label("kr"),
        kr_picks,
        template="turquoise",
        market_indices=kr_indices,
        important_news=kr_news,
        errors=kr_errors,
    )
    return us_card, kr_card


def run_once(*, market: str = "both", dry_run: bool = False, force: bool = False) -> None:
    load_dotenv(ROOT / ".env")
    if not stock_strategy_cards_enabled():
        print(
            "Stock strategy cards are disabled by FEISHU_STOCK_CARDS_ENABLED=false; "
            "use scripts/push_binance_long_signals.py for Binance stock contract signals."
        )
        return
    markets = ("kr", "us") if market == "both" else (market,)
    cards: dict[str, dict[str, Any]] = {}
    picks_by_market: dict[str, list[StockPick]] = {}
    for selected_market in markets:
        count = market_pick_count(selected_market)
        picks, errors = generate_market_selection(selected_market)
        market_indices = fetch_market_indices(selected_market)
        important_news = fetch_important_news(selected_market)
        picks_by_market[selected_market] = picks
        if selected_market == "us":
            cards[selected_market] = build_strategy_card(
                strategy_card_title("us", picks, count),
                market_label("us"),
                picks,
                template="blue",
                market_indices=market_indices,
                important_news=important_news,
                errors=errors,
            )
        else:
            cards[selected_market] = build_strategy_card(
                strategy_card_title(selected_market, picks, count),
                market_label(selected_market),
                picks,
                template="turquoise" if selected_market == "kr" else "green",
                market_indices=market_indices,
                important_news=important_news,
                errors=errors,
            )
    if dry_run:
        for selected_market in markets:
            append_paper_trading_element(
                cards[selected_market],
                selected_market,
                picks_by_market[selected_market],
                dry_run=True,
            )
        print(json.dumps(cards, ensure_ascii=False, indent=2))
        return
    state = load_state()
    sent = []
    for selected_market in markets:
        state_key = market_state_key(selected_market)
        picks = picks_by_market[selected_market]
        if not picks:
            print(f"{state_key.upper()} 未选出有效标的，跳过本次推送")
            if status_on_skip_enabled():
                sent_status = send_status_card_once(
                    state,
                    state_key=state_key,
                    task_key="preopen_empty",
                    reason="no_valid_picks",
                    card=build_status_card(
                        title=(
                            "🇺🇸 美股盘前策略｜运行状态"
                            if selected_market == "us"
                            else "🇰🇷 韩股盘前策略｜运行状态"
                            if selected_market == "kr"
                            else f"{selected_market.upper()} 盘前策略｜运行状态"
                        ),
                        market_label=market_label(selected_market),
                        conclusion="云端盘前任务已经正常执行，本次没有筛出新的有效名单。",
                        action="保持上一版精选名单，不推送空卡，等待下一次有效信号。",
                        details=["数据源或筛选条件未达到策略门槛"],
                        template="blue" if selected_market == "us" else "turquoise",
                    ),
                )
                if sent_status:
                    sent.append(f"{state_key}-status")
            continue
        signature = selection_signature(picks)
        if not force and state.get(state_key, {}).get("signature") == signature:
            print(f"{state_key.upper()} 行情日期与名单未变化，跳过重复推送")
            continue
        append_paper_trading_element(cards[selected_market], selected_market, picks, dry_run=False)
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
    parser = argparse.ArgumentParser(description="生成美股/韩股每日策略飞书卡片")
    parser.add_argument("--dry-run", action="store_true", help="只生成JSON，不推送")
    parser.add_argument("--schedule", action="store_true", help="按韩/美股盘前时间常驻执行")
    parser.add_argument("--force", action="store_true", help="即使行情与名单未变化也强制推送")
    parser.add_argument("--market", choices=("kr", "us", "both"), default="both", help="只处理指定市场")
    args = parser.parse_args()
    if not args.schedule:
        run_once(market=args.market, dry_run=args.dry_run, force=args.force)
        return 0

    load_dotenv(ROOT / ".env")
    kr_time = os.getenv("KR_CARD_SCHEDULE_TIME", "07:40").strip()
    us_time = os.getenv("US_CARD_SCHEDULE_TIME", "21:10").strip()
    schedule.every().day.at(kr_time).do(run_once, market="kr", dry_run=args.dry_run, force=args.force)
    schedule.every().day.at(us_time).do(run_once, market="us", dry_run=args.dry_run, force=args.force)
    if os.getenv("DAILY_CARD_RUN_IMMEDIATELY", "true").lower() == "true":
        run_once(market=args.market, dry_run=args.dry_run, force=args.force)
    print(f"盘前卡片任务已启动：韩股 {kr_time}，美股 {us_time}")
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
