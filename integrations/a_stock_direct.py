"""Low-frequency A-share quote collection following a-stock-data's source priority."""

from __future__ import annotations

from typing import Any, Iterable

import requests


def is_a_share(code: str) -> bool:
    value = code.strip().upper()
    return value.isdigit() and len(value) == 6 and value.startswith(("0", "3", "4", "6", "8", "9"))


def _market_prefix(code: str) -> str:
    if code.startswith(("6", "9")):
        return "sh"
    if code.startswith(("4", "8")):
        return "bj"
    return "sz"


def fetch_tencent_quotes(
    codes: Iterable[str],
    *,
    timeout: float = 15,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    symbols = [code.strip() for code in codes if is_a_share(code)]
    if not symbols:
        return []
    query = ",".join(f"{_market_prefix(code)}{code}" for code in symbols)
    client = session or requests.Session()
    response = client.get(
        "https://qt.gtimg.cn/q=" + query,
        headers={"User-Agent": "Mozilla/5.0 daily-stock-analysis/1.0"},
        timeout=timeout,
    )
    response.raise_for_status()
    response.encoding = "gbk"
    rows: list[dict[str, Any]] = []
    for line in response.text.splitlines():
        if '"' not in line:
            continue
        fields = line.split('"', 2)[1].split("~")
        if len(fields) < 47:
            continue
        try:
            rows.append(
                {
                    "name": fields[1],
                    "code": fields[2],
                    "price": float(fields[3] or 0),
                    "prev_close": float(fields[4] or 0),
                    "pct_change": float(fields[32] or 0),
                    "turnover": float(fields[38] or 0),
                    "pe_ttm": float(fields[39] or 0),
                    "market_cap_yi": float(fields[44] or 0),
                    "pb": float(fields[46] or 0),
                }
            )
        except (ValueError, IndexError):
            continue
    return rows

