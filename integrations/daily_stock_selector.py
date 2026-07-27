"""Daily cross-market ranking with regime, quality and consistency filters."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf
import yfinance.cache as yf_cache


ROOT = Path(__file__).resolve().parents[1]


def configure_yfinance_cache() -> None:
    """Keep yfinance's sqlite caches in a writable project-local directory."""
    raw_path = os.getenv("YFINANCE_CACHE_DIR")
    cache_dir = Path(raw_path).expanduser() if raw_path else ROOT / "data" / "cache" / "yfinance"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        yf_cache.set_cache_location(str(cache_dir))
        yf.set_tz_cache_location(str(cache_dir))
    except Exception:
        # Cache setup is an optimization; data fetch failures are handled per symbol.
        return


configure_yfinance_cache()


@dataclass(frozen=True)
class StockPick:
    code: str
    symbol: str
    name: str
    price: float
    day_change: float
    return_5d: float
    return_20d: float
    volume_ratio: float
    rsi14: float
    return_60d: float
    relative_strength_20d: float
    max_drawdown_20d: float
    liquidity: float
    capital_trace_score: float
    capital_trace_label: str
    accumulation_20d: float
    score: float
    confidence: str
    confidence_points: int
    regime: str
    eligible: bool
    reasons: tuple[str, ...]
    risks: tuple[str, ...]
    data_date: str


def to_yahoo_symbol(code: str, market: str) -> str:
    value = code.strip().upper()
    if market == "us":
        return value
    if market == "kr":
        if value.endswith((".KS", ".KQ")):
            return value
        if value.isdigit() and len(value) == 6:
            return f"{value}.KS"
        return value
    if market == "jp":
        return value
    if not (value.isdigit() and len(value) == 6):
        return value
    return f"{value}.SS" if value.startswith(("5", "6", "9")) else f"{value}.SZ"


def calculate_rsi(close: pd.Series, periods: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(periods).mean()
    loss = -delta.clip(upper=0).rolling(periods).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    value = rsi.iloc[-1]
    return 100.0 if pd.isna(value) and gain.iloc[-1] > 0 else float(value) if not pd.isna(value) else 50.0


def trim_incomplete_session(history: pd.DataFrame, market: str) -> pd.DataFrame:
    """Remove today's still-open daily bar when a provider exposes it early."""
    if history is None or history.empty:
        return history
    if market == "us":
        timezone = ZoneInfo("America/New_York")
        session_close = time(16, 10)
    elif market == "kr":
        timezone = ZoneInfo("Asia/Seoul")
        session_close = time(15, 40)
    elif market == "jp":
        timezone = ZoneInfo("Asia/Tokyo")
        session_close = time(15, 40)
    else:
        timezone = ZoneInfo("Asia/Shanghai")
        session_close = time(15, 10)
    now = datetime.now(timezone)
    last_timestamp = pd.Timestamp(history.index[-1])
    if last_timestamp.tzinfo is not None:
        last_date = last_timestamp.tz_convert(timezone).date()
    else:
        last_date = last_timestamp.date()
    if last_date == now.date() and now.time() < session_close:
        return history.iloc[:-1].copy()
    return history


def market_regime(history: pd.DataFrame) -> tuple[str, float]:
    if history is None or len(history) < 61:
        return "未知", 0.0
    frame = history.copy()
    frame.columns = [str(column).lower() for column in frame.columns]
    close = frame["close"].dropna().astype(float)
    if len(close) < 61:
        return "未知", 0.0
    price = float(close.iloc[-1])
    ma20 = float(close.tail(20).mean())
    ma60 = float(close.tail(60).mean())
    ret20 = (price / float(close.iloc[-21]) - 1) * 100
    if price >= ma20 >= ma60 and ret20 >= 0:
        return "顺风", 6.0
    if price < ma20 < ma60:
        return "逆风", -10.0
    return "震荡", -3.0


def rank_history(
    code: str,
    symbol: str,
    history: pd.DataFrame,
    *,
    name: str = "",
    benchmark_history: pd.DataFrame | None = None,
    regime: str = "未知",
    regime_adjustment: float = 0.0,
    minimum_liquidity: float = 0.0,
    selection_profile: str = "standard",
) -> StockPick | None:
    if history is None or len(history) < 81:
        return None
    frame = history.copy()
    frame.columns = [str(column).lower() for column in frame.columns]
    if "close" not in frame or "volume" not in frame:
        return None
    frame = frame.dropna(subset=["close"])
    if len(frame) < 81:
        return None

    close = frame["close"].astype(float)
    volume = frame["volume"].astype(float)
    if (close <= 0).any() or close.tail(60).isna().any() or volume.tail(20).isna().any():
        return None
    price = float(close.iloc[-1])
    ma20 = float(close.tail(20).mean())
    ma60 = float(close.tail(60).mean())
    ma20_5d_ago = float(close.iloc[-25:-5].mean())
    return_1d = (price / float(close.iloc[-2]) - 1) * 100
    return_5d = (price / float(close.iloc[-6]) - 1) * 100
    return_20d = (price / float(close.iloc[-21]) - 1) * 100
    return_60d = (price / float(close.iloc[-61]) - 1) * 100
    average_volume = float(volume.iloc[-21:-1].mean())
    volume_ratio = float(volume.iloc[-1] / average_volume) if average_volume > 0 else 1.0
    liquidity = float((close.iloc[-21:-1] * volume.iloc[-21:-1]).mean())
    rsi14 = calculate_rsi(close)
    annualized_volatility = float(close.pct_change().tail(20).std() * np.sqrt(252) * 100)
    rolling_peak = close.tail(20).cummax()
    max_drawdown_20d = float(((close.tail(20) / rolling_peak) - 1).min() * 100)
    turnover = close * volume
    turnover_20d = turnover.tail(20)
    signed_turnover_20d = np.sign(close.diff().tail(20)) * turnover_20d
    accumulation_20d = (
        float(signed_turnover_20d.sum() / turnover_20d.sum() * 100)
        if float(turnover_20d.sum()) > 0
        else 0.0
    )
    positive_weeks = sum(
        float(close.iloc[-offset] / close.iloc[-offset - 5] - 1) > 0
        for offset in (1, 6, 11, 16)
    )

    benchmark_return_20d = 0.0
    if benchmark_history is not None and len(benchmark_history) >= 21:
        benchmark = benchmark_history.copy()
        benchmark.columns = [str(column).lower() for column in benchmark.columns]
        benchmark_close = benchmark["close"].dropna().astype(float)
        if len(benchmark_close) >= 21:
            benchmark_return_20d = (float(benchmark_close.iloc[-1]) / float(benchmark_close.iloc[-21]) - 1) * 100
    relative_strength_20d = return_20d - benchmark_return_20d
    capital_trace_score = 45.0
    capital_trace_score += float(np.clip(accumulation_20d, -20, 22) * 0.7)
    capital_trace_score += float(np.clip(relative_strength_20d / 20 * 15, -10, 15))
    capital_trace_score += float(np.clip((volume_ratio - 0.8) / 1.2 * 12, -6, 12))
    capital_trace_score += 8 if price >= ma20 >= ma60 else 3 if price >= ma20 else -8
    capital_trace_score += 5 if 50 <= rsi14 <= 74 else -7 if rsi14 > 82 else 0
    capital_trace_score += 5 if max_drawdown_20d >= -10 and return_20d > 0 else -5 if max_drawdown_20d < -16 else 0
    if return_1d > 6 and volume_ratio > 1.8:
        capital_trace_score -= 8
    if return_20d > 38:
        capital_trace_score -= 6
    capital_trace_score = round(float(np.clip(capital_trace_score, 0, 100)), 1)
    capital_trace_label = (
        "强承接"
        if capital_trace_score >= 70
        else "承接确认"
        if capital_trace_score >= 58
        else "有资金痕迹"
        if capital_trace_score >= 45
        else "资金链路弱"
    )

    score = 5.0
    score += 12 if price >= ma20 else -15
    score += 10 if ma20 >= ma60 else -10
    score += 5 if ma20 > ma20_5d_ago else -5
    score += float(np.clip((return_5d + 8) / 20 * 10, 0, 10))
    score += float(np.clip((return_20d + 12) / 36 * 14, 0, 14))
    score += float(np.clip((relative_strength_20d + 8) / 24 * 14, 0, 14))
    score += positive_weeks * 2
    score += float(np.clip((volume_ratio - 0.65) / 1.5 * 5, 0, 5))
    score += 5 if 48 <= rsi14 <= 70 else 2 if 40 <= rsi14 < 48 else -10 if rsi14 > 80 else -3
    score -= float(np.clip((annualized_volatility - 40) / 4, 0, 14))
    score -= float(np.clip((-max_drawdown_20d - 8) / 2, 0, 10))
    score += float(np.clip((capital_trace_score - 50) / 50 * 8, -5, 8))
    if abs(return_1d) >= 8 or return_20d >= 35:
        score -= 8
    score += float(np.clip(regime_adjustment, -10, 5))
    score = round(float(np.clip(score, 0, 100)), 1)

    confidence_points = min(
        10,
        sum(
        (
            price >= ma20,
            ma20 >= ma60,
            ma20 > ma20_5d_ago,
            return_20d > 0,
            relative_strength_20d > 0,
            positive_weeks >= 3,
            45 <= rsi14 <= 72,
            annualized_volatility <= 55,
            max_drawdown_20d >= -12,
            liquidity >= minimum_liquidity,
            capital_trace_score >= 55,
            accumulation_20d > 0,
        )
        ),
    )
    confidence = "A" if confidence_points >= 8 else "B" if confidence_points >= 6 else "C"
    if selection_profile == "us_contract":
        eligible = (
            price >= ma20
            and return_20d > -3
            and relative_strength_20d > -5
            and rsi14 < 86
            and liquidity >= minimum_liquidity
            and capital_trace_score >= (52 if regime == "逆风" else 45)
            and confidence_points >= (7 if regime == "逆风" else 5)
        )
    else:
        eligible = (
            price >= ma20
            and ma20 >= ma60
            and ma20 > ma20_5d_ago
            and return_20d > 0
            and relative_strength_20d > -2
            and rsi14 < 82
            and liquidity >= minimum_liquidity
            and capital_trace_score >= (58 if regime == "逆风" else 50)
            and confidence_points >= (8 if regime == "逆风" else 6)
        )

    reasons = []
    if price >= ma20 and ma20 >= ma60:
        reasons.append("价格站上20日线，且中期趋势向上")
    elif price >= ma20:
        reasons.append("价格站上20日均线")
    if return_20d > 0:
        reasons.append(f"近20日动量 {return_20d:+.1f}%")
    if relative_strength_20d > 0:
        reasons.append(f"近20日跑赢基准 {relative_strength_20d:+.1f}%")
    if volume_ratio >= 1.15:
        reasons.append(f"量能放大至20日均量 {volume_ratio:.1f} 倍")
    if capital_trace_score >= 58:
        reasons.append(f"资金链路{capital_trace_label}，承接分 {capital_trace_score:.0f}")
    elif accumulation_20d > 8:
        reasons.append(f"近20日上涨成交占优 {accumulation_20d:+.1f}%")
    if 50 <= rsi14 <= 72:
        reasons.append(f"强弱指标 {rsi14:.0f}，走势有力且没有明显过热")
    if not reasons:
        reasons.append("综合趋势与风险调整后排名靠前")

    risks = []
    if rsi14 > 78:
        risks.append("短线指标偏热，避免追高")
    if annualized_volatility > 55:
        risks.append("近期波动较高")
    if volume_ratio < 0.75:
        risks.append("量能不足，突破确认度偏低")
    if capital_trace_score < 45:
        risks.append("资金承接证据不足")
    if return_1d > 6 and volume_ratio > 1.8:
        risks.append("短线放量过急，避免追高")
    if return_20d > 25:
        risks.append("近月涨幅较大，注意回撤")
    if regime == "逆风":
        risks.append("市场环境逆风，仅保留高一致性标的")
    if not risks:
        risks.append("跌破20日均线则趋势转弱")

    data_date = str(frame.index[-1])[:10]
    return StockPick(
        code=code,
        symbol=symbol,
        name=name or code,
        price=price,
        day_change=round(return_1d, 2),
        return_5d=round(return_5d, 2),
        return_20d=round(return_20d, 2),
        volume_ratio=round(volume_ratio, 2),
        rsi14=round(rsi14, 1),
        return_60d=round(return_60d, 2),
        relative_strength_20d=round(relative_strength_20d, 2),
        max_drawdown_20d=round(max_drawdown_20d, 2),
        liquidity=round(liquidity, 2),
        capital_trace_score=capital_trace_score,
        capital_trace_label=capital_trace_label,
        accumulation_20d=round(accumulation_20d, 2),
        score=score,
        confidence=confidence,
        confidence_points=confidence_points,
        regime=regime,
        eligible=eligible,
        reasons=tuple(reasons[:3]),
        risks=tuple(risks[:2]),
        data_date=data_date,
    )


def _download_one(
    code: str,
    market: str,
    name: str,
    benchmark_history: pd.DataFrame,
    regime: str,
    regime_adjustment: float,
    minimum_liquidity: float,
    selection_profile: str,
) -> StockPick | None:
    symbol = to_yahoo_symbol(code, market)
    history = yf.Ticker(symbol).history(period="6mo", interval="1d", auto_adjust=True)
    history = trim_incomplete_session(history, market)
    return rank_history(
        code,
        symbol,
        history,
        name=name,
        benchmark_history=benchmark_history,
        regime=regime,
        regime_adjustment=regime_adjustment,
        minimum_liquidity=minimum_liquidity,
        selection_profile=selection_profile,
    )


def select_daily_picks(
    codes: Iterable[str],
    *,
    market: str,
    names: dict[str, str] | None = None,
    count: int | None = 3,
    workers: int = 4,
    benchmark_symbol: str | None = None,
    minimum_liquidity: float = 0.0,
    include_reserves: int = 3,
    selection_profile: str = "standard",
    eligible_only: bool = False,
) -> tuple[list[StockPick], list[str]]:
    normalized = list(dict.fromkeys(code.strip().upper() for code in codes if code.strip()))
    name_map = names or {}
    picks: list[StockPick] = []
    errors: list[str] = []
    benchmark_code = benchmark_symbol or (
        "SPY"
        if market == "us"
        else "^KS11"
        if market == "kr"
        else "^N225"
        if market == "jp"
        else "000300.SS"
    )
    try:
        benchmark_history = yf.Ticker(benchmark_code).history(period="6mo", interval="1d", auto_adjust=True)
        benchmark_history = trim_incomplete_session(benchmark_history, market)
        regime, regime_adjustment = market_regime(benchmark_history)
    except Exception as exc:
        benchmark_history = pd.DataFrame()
        regime, regime_adjustment = "未知", 0.0
        errors.append(f"市场基准 {benchmark_code} 获取失败：{exc}")
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(normalized) or 1))) as executor:
        futures = {
            executor.submit(
                _download_one,
                code,
                market,
                name_map.get(code, code),
                benchmark_history,
                regime,
                regime_adjustment,
                minimum_liquidity,
                selection_profile,
            ): code
            for code in normalized
        }
        for future in as_completed(futures):
            code = futures[future]
            try:
                pick = future.result()
                if pick is not None:
                    picks.append(pick)
                else:
                    errors.append(f"{code} 历史数据不足")
            except Exception as exc:
                errors.append(f"{code} 获取失败：{exc}")
    picks.sort(key=lambda item: (-int(item.eligible), -item.score, item.code))
    if eligible_only:
        picks = [pick for pick in picks if pick.eligible]
    if count is None or count <= 0:
        return picks, errors
    limit = count if eligible_only else count + max(0, include_reserves)
    return picks[:limit], errors
