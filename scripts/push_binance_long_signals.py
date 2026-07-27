"""Push Binance stock perpetual long/short watch signals to Feishu.

This script is intentionally read-only toward Binance: it fetches public
contract market data, filters ``long_watch`` / ``short_watch`` candidates,
and pushes an interactive Feishu card. It is scoped to Binance TradFi/equity
perpetual contracts and never places orders.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_binance_contract_data import (
    BinanceContractSnapshot,
    DEFAULT_INTERVAL,
    DEFAULT_LIMIT,
    contract_symbols,
    fetch_contract_snapshots,
)
from scripts.push_daily_strategy_cards import send_card
from scripts.push_strategy_digest import configure_console_encoding


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
    signals = signal_candidates(snapshots, side=side, min_score=min_score)
    longs = [item for item in signals if item.contract_signal == "long_watch"]
    shorts = [item for item in signals if item.contract_signal == "short_watch"]
    card = build_contract_signal_card(
        signals,
        all_snapshots=snapshots,
        errors=errors,
        interval=interval,
        limit=limit,
        side=side,
    )
    result = {
        "long_count": len(longs),
        "short_count": len(shorts),
        "signal_count": len(signals),
        "snapshot_count": len(snapshots),
        "errors": errors,
        "longs": [item.symbol for item in longs],
        "shorts": [item.symbol for item in shorts],
        "signals": [item.symbol for item in signals],
        "card": card,
    }
    if dry_run:
        return result
    if signals or push_empty:
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
        default=float(os.getenv("BINANCE_SIGNAL_MIN_SCORE", os.getenv("BINANCE_LONG_SIGNAL_MIN_SCORE", "0"))),
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
