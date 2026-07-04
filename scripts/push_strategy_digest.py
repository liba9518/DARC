"""Collect Quiver/A-share signals and push a compact digest to Feishu."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import schedule
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from integrations.a_stock_direct import fetch_tencent_quotes, is_a_share
from integrations.card_language import chinese_visible_text
from integrations.chokepoint_atlas import ChokepointLane, collect_chokepoint_lanes
from integrations.quiver_quant import QuiverClient


def configure_console_encoding() -> None:
    """Keep Windows terminals from failing on emoji/Chinese report output."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def parse_tickers(value: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in value.replace("，", ",").split(","):
        ticker = raw.strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            result.append(ticker)
    return result


def parse_data_paths(value: str, *, default: Path) -> list[Path]:
    raw_paths = [item.strip() for item in value.replace("\n", ";").split(";") if item.strip()]
    if not raw_paths:
        return [default]
    return [path if path.is_absolute() else ROOT / path for path in map(Path, raw_paths)]


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(value: Any) -> str:
    amount = _number(value)
    if abs(amount) >= 1_000_000_000:
        return f"{amount / 100_000_000:.2f}亿美元"
    if abs(amount) >= 1_000_000:
        return f"{amount / 1_000_000:.2f}百万美元"
    if abs(amount) >= 1_000:
        return f"{amount / 1_000:.1f}千美元"
    return f"{amount:,.0f}美元"


def _date(value: Any) -> str:
    return str(value or "")[:10]


def build_quiver_digest(
    data: dict[str, list[dict[str, Any]]],
    watchlist: list[str],
    *,
    max_items: int,
) -> list[str]:
    lines: list[str] = []
    scores: defaultdict[str, float] = defaultdict(float)

    congress = data.get("国会交易", [])
    if congress:
        lines.append("### 🇺🇸 国会交易")
        for row in congress[:max_items]:
            ticker = str(row.get("Ticker") or "-").upper()
            action = str(row.get("Transaction") or "")
            scores[ticker] += 2 if "purchase" in action.lower() else -1 if "sale" in action.lower() else 0
            lines.append(
                f"- **{ticker}** {action}｜{row.get('Representative', '-')} "
                f"({row.get('Party', '-')})｜{row.get('Range') or _money(row.get('Amount'))}｜{_date(row.get('TransactionDate'))}"
            )

    insiders = data.get("内部人交易", [])
    if insiders:
        lines.append("\n### 🧑‍💼 内部人交易")
        ranked = sorted(
            insiders,
            key=lambda row: abs(_number(row.get("Shares")) * _number(row.get("PricePerShare"))),
            reverse=True,
        )
        for row in ranked[:max_items]:
            ticker = str(row.get("Ticker") or "-").upper()
            acquired = str(row.get("AcquiredDisposedCode") or "").upper() == "A"
            value = _number(row.get("Shares")) * _number(row.get("PricePerShare"))
            scores[ticker] += 2.5 if acquired else -2
            lines.append(
                f"- **{ticker}** {'增持' if acquired else '减持'} {_number(row.get('Shares')):,.0f}股 "
                f"≈ {_money(value)}｜{row.get('Name', '-')} {row.get('officerTitle') or ''}｜{_date(row.get('Date'))}"
            )

    contracts = data.get("政府合同", [])
    if contracts:
        lines.append("\n### 🏛️ 政府合同")
        ranked = sorted(contracts, key=lambda row: _number(row.get("Amount")), reverse=True)
        for row in ranked[:max_items]:
            ticker = str(row.get("Ticker") or "-").upper()
            amount = _number(row.get("Amount"))
            scores[ticker] += min(3, max(0.5, math.log10(max(amount, 1)) - 5))
            description = str(row.get("Description") or "").replace("\n", " ")[:90]
            lines.append(
                f"- **{ticker}** {_money(amount)}｜{row.get('Agency') or '-'}｜{description}｜{_date(row.get('Date'))}"
            )

    offexchange = data.get("场外/暗池", [])
    if offexchange:
        lines.append("\n### 🌑 场外/暗池空头占比")
        ranked = sorted(offexchange, key=lambda row: _number(row.get("DPI")), reverse=True)
        for row in ranked[:max_items]:
            ticker = str(row.get("Ticker") or "-").upper()
            dpi = _number(row.get("DPI"))
            scores[ticker] -= max(0, dpi - 50) / 10
            lines.append(
                f"- **{ticker}** 场外空头占比 {dpi:.1f}%｜场外空头 {_number(row.get('OTC_Short')):,.0f}股｜{_date(row.get('Date'))}"
            )

    news = data.get("Quiver新闻", [])
    if news:
        lines.append("\n### 📰 另类财经消息")
        for row in news[:max_items]:
            headline = str(row.get("headline") or row.get("summary") or "Quiver News").strip()
            url = str(row.get("url") or "").strip()
            lines.append(f"- [{headline[:110]}]({url})" if url else f"- {headline[:110]}")

    watchlist_set = set(watchlist)
    ranked_scores = [(ticker, score) for ticker, score in scores.items() if ticker in watchlist_set]
    if ranked_scores:
        lines.append("\n### 🧭 另类数据观察分")
        for ticker, score in sorted(ranked_scores, key=lambda item: item[1], reverse=True):
            label = "偏积极" if score >= 2 else "偏谨慎" if score <= -2 else "中性"
            lines.append(f"- **{ticker}**：{score:+.1f}（{label}，仅用于信息排序）")
    return lines


def build_a_share_digest(quotes: list[dict[str, Any]]) -> list[str]:
    if not quotes:
        return []
    lines = ["### 🇨🇳 沪深股票直连行情"]
    for row in sorted(quotes, key=lambda item: abs(item["pct_change"]), reverse=True):
        lines.append(
            f"- **{row['name']}({row['code']})** {row['price']:.2f} "
            f"({row['pct_change']:+.2f}%)｜市盈率 {row['pe_ttm']:.1f}｜市净率 {row['pb']:.2f}｜换手 {row['turnover']:.2f}%"
        )
    return lines


def build_chokepoint_digest(lanes: list[ChokepointLane], *, max_items: int) -> list[str]:
    if not lanes:
        return []
    lines = ["### 🏗️ 人工智能供应链瓶颈研究"]
    for lane in lanes[:max_items]:
        score = f"{lane.total_score:.2f}/5" if lane.total_score else "未评分"
        stale = "｜⚠️ 资料待更新" if lane.stale else ""
        lines.append(f"- **{lane.lane}**｜{score}｜{lane.priority}{stale}")
        if lane.end_system:
            lines.append(f"  - 系统：{lane.end_system}")
        if lane.bottleneck:
            lines.append(f"  - 瓶颈：{lane.bottleneck}")
        if lane.top_names:
            lines.append(f"  - 候选公司：{', '.join(lane.top_names)}")
        if lane.catalysts:
            lines.append(f"  - 下一催化：{lane.catalysts[0]}")
        if lane.as_of_date:
            lines.append(f"  - 研究日期：{lane.as_of_date}")
    return lines


def build_message(
    tickers: list[str],
    quiver_data: dict[str, list[dict[str, Any]]],
    a_share_quotes: list[dict[str, Any]],
    *,
    chokepoint_lanes: list[ChokepointLane] | None = None,
    max_items: int,
    errors: list[str],
) -> str:
    lines = [
        f"# 📡 多源股票策略雷达｜{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"自选范围：{', '.join(tickers) if tickers else '未配置'}",
        "",
    ]
    lines.extend(build_quiver_digest(quiver_data, tickers, max_items=max_items))
    lines.append("")
    lines.extend(build_a_share_digest(a_share_quotes))
    lines.append("")
    lines.extend(build_chokepoint_digest(chokepoint_lanes or [], max_items=max_items))
    if errors:
        lines.extend(["", "### ⚠️ 降级信息", *[f"- {error}" for error in errors]])
    if len([line for line in lines[3:] if line.strip()]) == 0:
        lines.append("本次没有获取到可展示的新数据。")
    lines.extend(
        [
            "",
            "> 数据源：Quiver Quant 官方 API、腾讯财经直连接口、Chokepoint Atlas结构化研究包；仅供研究和信息筛选，不构成投资建议。",
        ]
    )
    return chinese_visible_text("\n".join(lines))


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


def send_feishu(message: str) -> None:
    webhook, secret, keyword = _stock_feishu_config()
    if not webhook:
        raise RuntimeError("未配置 STOCK_FEISHU_WEBHOOK_URL 或 FEISHU_WEBHOOK_URL")
    content = chinese_visible_text(f"{keyword}\n{message}" if keyword else message)
    payload: dict[str, Any] = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "多源股票策略雷达"}},
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": content}}],
        },
    }
    if secret:
        payload.update(_sign(secret))
    response = requests.post(webhook, json=payload, timeout=30)
    response.raise_for_status()
    result = response.json()
    if result.get("code", result.get("StatusCode", 0)) not in {0, None}:
        raise RuntimeError(f"飞书推送失败: {result}")


def run_once(*, dry_run: bool = False) -> str:
    load_dotenv(ROOT / ".env")
    tickers = parse_tickers(os.getenv("STOCK_LIST", ""))
    us_tickers = [ticker for ticker in tickers if not is_a_share(ticker) and ticker.isascii()]
    a_tickers = [ticker for ticker in tickers if is_a_share(ticker)]
    max_items = max(1, int(os.getenv("ALT_DATA_MAX_ITEMS", "8")))
    errors: list[str] = []
    quiver_data: dict[str, list[dict[str, Any]]] = {}

    token = os.getenv("QUIVER_API_TOKEN", "").strip()
    if token and us_tickers:
        try:
            quiver_data = QuiverClient(token).collect(us_tickers)
        except Exception as exc:
            errors.append(f"Quiver采集失败：{exc}")
    elif us_tickers:
        errors.append("未配置 QUIVER_API_TOKEN，已跳过Quiver数据")

    try:
        quotes = fetch_tencent_quotes(a_tickers)
    except Exception as exc:
        quotes = []
        errors.append(f"A股腾讯行情采集失败：{exc}")

    chokepoint_paths = parse_data_paths(
        os.getenv("CHOKEPOINT_ATLAS_PATHS", ""),
        default=ROOT / "data" / "chokepoint-atlas",
    )
    max_age_days = max(0, int(os.getenv("CHOKEPOINT_ATLAS_MAX_AGE_DAYS", "45")))
    chokepoint_lanes, chokepoint_errors = collect_chokepoint_lanes(
        chokepoint_paths,
        max_age_days=max_age_days,
    )
    errors.extend(f"Chokepoint Atlas：{error}" for error in chokepoint_errors)

    message = build_message(
        tickers,
        quiver_data,
        quotes,
        chokepoint_lanes=chokepoint_lanes,
        max_items=max_items,
        errors=errors,
    )
    if dry_run:
        print(message)
    else:
        send_feishu(message)
        print("策略雷达已推送到飞书")
    return message


def main() -> int:
    configure_console_encoding()
    parser = argparse.ArgumentParser(description="采集Quiver/A股直连数据并推送飞书")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不推送")
    parser.add_argument("--schedule", action="store_true", help="按ALT_DATA_SCHEDULE_TIME常驻定时运行")
    args = parser.parse_args()
    if not args.schedule:
        run_once(dry_run=args.dry_run)
        return 0

    load_dotenv(ROOT / ".env")
    schedule_time = os.getenv("ALT_DATA_SCHEDULE_TIME", "17:45").strip()
    schedule.every().day.at(schedule_time).do(run_once, dry_run=args.dry_run)
    if os.getenv("ALT_DATA_RUN_IMMEDIATELY", "true").lower() == "true":
        run_once(dry_run=args.dry_run)
    print(f"策略雷达定时任务已启动，每日 {schedule_time} 执行")
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
