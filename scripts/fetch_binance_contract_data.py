"""Fetch Binance stock perpetual contract market data for strategy signals.

The script only uses public market-data endpoints. It does not place orders,
does not require API keys, and is intentionally scoped to Binance TradFi
equity perpetual contracts instead of crypto perpetual contracts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_STOCK_PERP_SYMBOLS = (
    "TSLAUSDT,AAPLUSDT,NVDAUSDT,MSFTUSDT,AMZNUSDT,METAUSDT,GOOGLUSDT,AVGOUSDT,"
    "TSMUSDT,AMDUSDT,MUUSDT,SNDKUSDT,MSTRUSDT,COINUSDT,PLTRUSDT,CRCLUSDT,HOODUSDT,BABAUSDT"
)
DEFAULT_USDM_SYMBOLS = DEFAULT_STOCK_PERP_SYMBOLS
DEFAULT_STOCK_SYMBOL_ALIASES = {
    "MU": "MUUSDT",
    "SAND": "SNDKUSDT",
    "SNDK": "SNDKUSDT",
}
DEFAULT_USDM_BASE_URL = "https://fapi.binance.com"
DEFAULT_INTERVAL = "15m"
DEFAULT_LIMIT = 96


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


@dataclass(frozen=True)
class BinanceContractSnapshot:
    symbol: str
    market: str
    last_price: float
    mark_price: float
    index_price: float
    price_change_pct_24h: float
    high_price_24h: float
    low_price_24h: float
    quote_volume_24h: float
    trade_count_24h: int
    last_funding_rate: float | None
    next_funding_time: str | None
    kline_interval: str
    kline_return_pct: float
    kline_range_pct: float
    taker_buy_quote_ratio: float
    contract_signal: str
    signal_score: float
    fetched_at: str


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _iso_from_ms(value: Any) -> str | None:
    timestamp = _int(value)
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).isoformat()


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return min(maximum, max(minimum, int(raw_value)))
    except ValueError:
        return default


def base_url_for_market(market: str) -> str:
    _ = market
    return os.getenv("BINANCE_FUTURES_BASE_URL", DEFAULT_USDM_BASE_URL).rstrip("/")


def default_symbols_for_market(market: str) -> str:
    _ = market
    return DEFAULT_USDM_SYMBOLS


def contract_symbols(market: str, override: str | None = None) -> list[str]:
    raw = override or os.getenv("BINANCE_CONTRACT_SYMBOLS") or default_symbols_for_market(market)
    aliases = dict(DEFAULT_STOCK_SYMBOL_ALIASES)
    extra_aliases = os.getenv("BINANCE_STOCK_CONTRACT_ALIASES", "").strip()
    if extra_aliases:
        for pair in parse_tickers(extra_aliases.replace(";", ",")):
            if "=" not in pair:
                continue
            key, value = pair.split("=", 1)
            if key.strip() and value.strip():
                aliases[key.strip().upper()] = value.strip().upper()

    symbols: list[str] = []
    for item in parse_tickers(raw):
        normalized = aliases.get(item, item)
        if normalized == item and not normalized.endswith("USDT"):
            normalized = f"{normalized}USDT"
        symbols.append(normalized)
    return symbols


def api_prefix(market: str) -> str:
    _ = market
    return "/fapi/v1"


def request_json(base_url: str, path: str, params: dict[str, Any], timeout: float) -> Any:
    response = requests.get(
        f"{base_url}{path}",
        params=params,
        timeout=timeout,
        headers={"User-Agent": "daily-stock-analysis/binance-contract-signal"},
    )
    response.raise_for_status()
    return response.json()


def _env_flag(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def stock_contract_allowlist() -> set[str]:
    raw = os.getenv("BINANCE_STOCK_CONTRACT_ALLOWLIST") or DEFAULT_STOCK_PERP_SYMBOLS
    return set(parse_tickers(raw))


def discover_stock_contract_symbols(*, market: str, timeout: float) -> set[str]:
    if market != "usdm":
        return set()
    exchange_info = request_json(base_url_for_market(market), f"{api_prefix(market)}/exchangeInfo", {}, timeout)
    symbols = exchange_info.get("symbols", []) if isinstance(exchange_info, dict) else []
    selected: set[str] = set()
    for item in symbols:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "TRADING":
            continue
        if item.get("underlyingType") != "EQUITY":
            continue
        if item.get("contractType") != "TRADIFI_PERPETUAL":
            continue
        selected.add(str(item.get("symbol", "")).upper())
    return selected


def filter_stock_contract_symbols(
    symbols: list[str],
    *,
    market: str,
    timeout: float,
) -> tuple[list[str], list[str]]:
    if not _env_flag("BINANCE_CONTRACT_STOCK_ONLY", "true"):
        return symbols, []

    errors: list[str] = []
    if market != "usdm":
        return [], [f"{market} skipped: Binance stock/TradFi perpetual contracts are USDⓈ-M only"]

    try:
        allowed = discover_stock_contract_symbols(market=market, timeout=timeout)
    except Exception as exc:
        allowed = stock_contract_allowlist()
        errors.append(f"exchangeInfo validation failed, using stock contract allowlist: {exc}")

    selected: list[str] = []
    for symbol in symbols:
        normalized = symbol.upper()
        if normalized in allowed:
            selected.append(normalized)
        else:
            errors.append(f"{normalized} skipped: not a Binance EQUITY TRADIFI_PERPETUAL contract")
    return selected, errors


def kline_metrics(klines: list[list[Any]]) -> dict[str, float]:
    if not klines:
        return {
            "return_pct": 0.0,
            "range_pct": 0.0,
            "taker_buy_quote_ratio": 0.0,
        }

    first_open = _float(klines[0][1])
    last_close = _float(klines[-1][4])
    highs = [_float(row[2]) for row in klines]
    lows = [_float(row[3]) for row in klines]
    quote_volumes = [_float(row[7]) for row in klines]
    taker_buy_quote_volumes = [_float(row[10]) for row in klines]
    total_quote_volume = sum(quote_volumes)
    high = max(highs) if highs else 0.0
    low = min(value for value in lows if value > 0) if any(value > 0 for value in lows) else 0.0
    return_pct = (last_close / first_open - 1) * 100 if first_open > 0 else 0.0
    range_pct = (high / low - 1) * 100 if low > 0 else 0.0
    taker_buy_quote_ratio = (
        sum(taker_buy_quote_volumes) / total_quote_volume if total_quote_volume > 0 else 0.0
    )
    return {
        "return_pct": return_pct,
        "range_pct": range_pct,
        "taker_buy_quote_ratio": taker_buy_quote_ratio,
    }


def classify_contract_signal(
    *,
    price_change_pct_24h: float,
    kline_return_pct: float,
    taker_buy_quote_ratio: float,
    last_funding_rate: float | None,
) -> tuple[str, float]:
    funding = last_funding_rate or 0.0
    momentum_score = price_change_pct_24h * 0.4 + kline_return_pct * 0.6
    flow_score = (taker_buy_quote_ratio - 0.5) * 100
    funding_penalty = abs(funding) * 10_000
    score = momentum_score + flow_score - funding_penalty * 0.15
    if kline_return_pct >= 1.0 and price_change_pct_24h >= 0 and taker_buy_quote_ratio >= 0.52:
        return "long_watch", round(score, 2)
    if kline_return_pct <= -1.0 and price_change_pct_24h <= 0 and taker_buy_quote_ratio <= 0.48:
        return "short_watch", round(score, 2)
    return "neutral", round(score, 2)


def fetch_contract_snapshot(
    symbol: str,
    *,
    market: str,
    interval: str,
    limit: int,
    timeout: float,
) -> BinanceContractSnapshot:
    base_url = base_url_for_market(market)
    prefix = api_prefix(market)
    ticker = request_json(base_url, f"{prefix}/ticker/24hr", {"symbol": symbol}, timeout)
    premium = request_json(base_url, f"{prefix}/premiumIndex", {"symbol": symbol}, timeout)
    klines = request_json(
        base_url,
        f"{prefix}/klines",
        {"symbol": symbol, "interval": interval, "limit": limit},
        timeout,
    )
    metrics = kline_metrics(klines if isinstance(klines, list) else [])
    funding_rate = _float(premium.get("lastFundingRate"), 0.0) if isinstance(premium, dict) else None
    price_change_pct = _float(ticker.get("priceChangePercent"))
    signal, signal_score = classify_contract_signal(
        price_change_pct_24h=price_change_pct,
        kline_return_pct=metrics["return_pct"],
        taker_buy_quote_ratio=metrics["taker_buy_quote_ratio"],
        last_funding_rate=funding_rate,
    )
    return BinanceContractSnapshot(
        symbol=symbol,
        market=market,
        last_price=_float(ticker.get("lastPrice")),
        mark_price=_float(premium.get("markPrice")) if isinstance(premium, dict) else 0.0,
        index_price=_float(premium.get("indexPrice")) if isinstance(premium, dict) else 0.0,
        price_change_pct_24h=price_change_pct,
        high_price_24h=_float(ticker.get("highPrice")),
        low_price_24h=_float(ticker.get("lowPrice")),
        quote_volume_24h=_float(ticker.get("quoteVolume")),
        trade_count_24h=_int(ticker.get("count")),
        last_funding_rate=funding_rate,
        next_funding_time=_iso_from_ms(premium.get("nextFundingTime")) if isinstance(premium, dict) else None,
        kline_interval=interval,
        kline_return_pct=metrics["return_pct"],
        kline_range_pct=metrics["range_pct"],
        taker_buy_quote_ratio=metrics["taker_buy_quote_ratio"],
        contract_signal=signal,
        signal_score=signal_score,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


def fetch_contract_snapshots(
    symbols: list[str],
    *,
    market: str,
    interval: str,
    limit: int,
    timeout: float,
) -> tuple[list[BinanceContractSnapshot], list[str]]:
    snapshots: list[BinanceContractSnapshot] = []
    selected_symbols, errors = filter_stock_contract_symbols(symbols, market=market, timeout=timeout)
    for symbol in selected_symbols:
        try:
            snapshots.append(
                fetch_contract_snapshot(
                    symbol,
                    market=market,
                    interval=interval,
                    limit=limit,
                    timeout=timeout,
                )
            )
        except Exception as exc:
            errors.append(f"{symbol} fetch failed: {exc}")
    snapshots.sort(key=lambda item: (item.contract_signal == "neutral", -item.signal_score, -item.quote_volume_24h))
    return snapshots, errors


def render_text(snapshots: list[BinanceContractSnapshot], errors: list[str]) -> str:
    lines = ["## Binance stock perpetual contract signals"]
    if not snapshots:
        lines.append("- No contract data fetched.")
    for index, item in enumerate(snapshots, start=1):
        funding_text = "n/a" if item.last_funding_rate is None else f"{item.last_funding_rate * 100:+.4f}%"
        lines.append(
            f"{index}. {item.symbol} [{item.contract_signal}] score={item.signal_score:+.2f} "
            f"last={item.last_price:g} mark={item.mark_price:g} "
            f"24h={item.price_change_pct_24h:+.2f}% kline={item.kline_return_pct:+.2f}% "
            f"buyRatio={item.taker_buy_quote_ratio:.2f} funding={funding_text} "
            f"quoteVol={item.quote_volume_24h:,.0f}"
        )
    if errors:
        lines.append("errors:")
        lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines)


def run(
    *,
    market: str,
    symbols: str | None,
    interval: str,
    limit: int,
    timeout: float,
    output_format: str,
) -> str:
    snapshots, errors = fetch_contract_snapshots(
        contract_symbols(market, symbols),
        market=market,
        interval=interval,
        limit=limit,
        timeout=timeout,
    )
    if output_format == "json":
        return json.dumps(
            {"snapshots": [asdict(item) for item in snapshots], "errors": errors},
            ensure_ascii=False,
            indent=2,
        )
    return render_text(snapshots, errors)


def main() -> int:
    configure_console_encoding()
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Fetch Binance stock perpetual contract data.")
    parser.add_argument("--market", choices=("usdm",), default=os.getenv("BINANCE_CONTRACT_MARKET", "usdm"))
    parser.add_argument("--symbols", help="Comma separated stock perpetual symbols, e.g. TSLAUSDT,AAPLUSDT,NVDAUSDT.")
    parser.add_argument("--interval", default=os.getenv("BINANCE_CONTRACT_INTERVAL", DEFAULT_INTERVAL))
    parser.add_argument(
        "--limit",
        type=int,
        default=_env_int("BINANCE_CONTRACT_KLINE_LIMIT", DEFAULT_LIMIT, minimum=2, maximum=1000),
    )
    parser.add_argument("--timeout", type=float, default=float(os.getenv("BINANCE_CONTRACT_TIMEOUT_SEC", "10")))
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    print(
        run(
            market=args.market,
            symbols=args.symbols,
            interval=args.interval,
            limit=max(2, min(1000, args.limit)),
            timeout=max(1.0, args.timeout),
            output_format=args.format,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
