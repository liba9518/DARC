"""Recommend cross-market US/KR signal candidates.

This is a lightweight CLI for widening the strategy signal universe without
changing the existing Feishu CN/US scheduled card workflow.  It reuses the
daily selector and Yahoo Finance symbols so it works for US tickers and Korea
suffix symbols such as ``005930.KS`` / ``035720.KQ``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from integrations.daily_stock_selector import StockPick, select_daily_picks
from scripts.push_daily_strategy_cards import DEFAULT_US_POOL
from scripts.push_strategy_digest import configure_console_encoding, parse_tickers


DEFAULT_KR_SIGNAL_POOL = (
    "005930.KS,000660.KS,373220.KS,005380.KS,035420.KS,"
    "051910.KS,006400.KS,035720.KQ,247540.KQ,091990.KQ"
)

KR_SIGNAL_NAMES = {
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


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return max(1, int(raw_value))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return max(0.0, float(raw_value))
    except ValueError:
        return default


def signal_pool(market: str) -> list[str]:
    if market == "us":
        raw = os.getenv("US_SIGNAL_POOL") or os.getenv("US_STRATEGY_POOL") or DEFAULT_US_POOL
    elif market == "kr":
        raw = os.getenv("KR_SIGNAL_POOL") or DEFAULT_KR_SIGNAL_POOL
    else:
        raise ValueError(f"Unsupported market: {market}")
    return parse_tickers(raw)


def signal_count(market: str, override: int | None = None) -> int:
    if override is not None:
        return max(1, override)
    if market == "us":
        raw_value = os.getenv("US_SIGNAL_MAX_COUNT") or os.getenv("US_SIGNAL_PICK_COUNT")
    else:
        raw_value = os.getenv("KR_SIGNAL_MAX_COUNT") or os.getenv("KR_SIGNAL_PICK_COUNT")
    if not raw_value or raw_value.strip() in {"0", "none", "None", "NONE"}:
        return 0
    try:
        return max(0, int(raw_value))
    except ValueError:
        return 0


def minimum_liquidity(market: str) -> float:
    if market == "us":
        return _env_float("US_MIN_DOLLAR_VOLUME", 10_000_000)
    return _env_float("KR_MIN_DAILY_TURNOVER_KRW", 5_000_000_000)


def select_signal_candidates(market: str, *, count: int | None = None) -> tuple[list[StockPick], list[str]]:
    pool = signal_pool(market)
    names = KR_SIGNAL_NAMES if market == "kr" else None
    return select_daily_picks(
        pool,
        market=market,
        names=names,
        count=signal_count(market, count),
        minimum_liquidity=minimum_liquidity(market),
        selection_profile="us_quality" if market == "us" else "standard",
        include_reserves=0,
        eligible_only=True,
    )


def pick_to_dict(pick: StockPick) -> dict[str, Any]:
    return {
        "code": pick.code,
        "name": pick.name,
        "price": pick.price,
        "day_change": pick.day_change,
        "return_20d": pick.return_20d,
        "relative_strength_20d": pick.relative_strength_20d,
        "volume_ratio": pick.volume_ratio,
        "liquidity": pick.liquidity,
        "score": pick.score,
        "confidence": pick.confidence,
        "eligible": pick.eligible,
        "data_date": pick.data_date,
        "reasons": list(pick.reasons),
        "risks": list(pick.risks),
    }


def render_text(result: dict[str, tuple[list[StockPick], list[str]]]) -> str:
    lines: list[str] = []
    labels = {"us": "US signals", "kr": "KR signals"}
    for market, (picks, errors) in result.items():
        lines.append(f"## {labels[market]}")
        if not picks:
            lines.append("- No valid candidates.")
        for index, pick in enumerate(picks, start=1):
            status = "eligible" if pick.eligible else "reserve"
            lines.append(
                f"{index}. {pick.code} {pick.name} [{status}] "
                f"score={pick.score:.1f} conf={pick.confidence} "
                f"20d={pick.return_20d:+.1f}% rs={pick.relative_strength_20d:+.1f}% "
                f"vol={pick.volume_ratio:.2f}x date={pick.data_date}"
            )
        if errors:
            lines.append("errors:")
            lines.extend(f"- {error}" for error in errors)
        lines.append("")
    return "\n".join(lines).strip()


def run(markets: tuple[str, ...], *, count: int | None, output_format: str) -> str:
    result = {market: select_signal_candidates(market, count=count) for market in markets}
    if output_format == "json":
        payload = {
            market: {
                "picks": [pick_to_dict(pick) for pick in picks],
                "errors": errors,
            }
            for market, (picks, errors) in result.items()
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return render_text(result)


def main() -> int:
    configure_console_encoding()
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Recommend US/KR stock signal candidates.")
    parser.add_argument("--market", choices=("us", "kr", "both"), default="both")
    parser.add_argument("--count", type=int, help="Maximum triggered candidates per market; omit or set env to 0 for no cap.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    markets = ("us", "kr") if args.market == "both" else (args.market,)
    print(run(markets, count=args.count, output_format=args.format))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
