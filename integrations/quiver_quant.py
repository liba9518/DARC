"""Small, fail-open client for the official Quiver Quant API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import requests


API_BASE_URL = "https://api.quiverquant.com"


class QuiverError(RuntimeError):
    """Raised when Quiver returns an unusable response."""


@dataclass(frozen=True)
class QuiverDataset:
    name: str
    path: str
    params: dict[str, Any]


class QuiverClient:
    def __init__(
        self,
        token: str,
        *,
        timeout: float = 20,
        session: requests.Session | None = None,
    ) -> None:
        self.token = token.strip()
        self.timeout = timeout
        self.session = session or requests.Session()

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def get(self, path: str, **params: Any) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        response = self.session.get(
            f"{API_BASE_URL}{path}",
            params={key: value for key, value in params.items() if value is not None},
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "User-Agent": "daily-stock-analysis-quiver/1.0",
            },
            timeout=self.timeout,
        )
        if response.status_code in {401, 403}:
            raise QuiverError("Quiver API token无效或当前套餐无权访问此数据集")
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("results", "data", "items"):
                rows = payload.get(key)
                if isinstance(rows, list):
                    return [item for item in rows if isinstance(item, dict)]
        raise QuiverError(f"Quiver响应格式异常: {path}")

    def collect(self, tickers: Iterable[str], *, page_size: int = 100) -> dict[str, list[dict[str, Any]]]:
        watchlist = {ticker.strip().upper() for ticker in tickers if ticker.strip()}
        datasets = (
            QuiverDataset("国会交易", "/beta/live/congresstrading", {"normalized": True}),
            QuiverDataset("内部人交易", "/beta/live/insiders", {"page": 1, "page_size": page_size}),
            QuiverDataset("政府合同", "/beta/live/govcontractsall", {"page": 1, "page_size": page_size}),
            QuiverDataset("场外/暗池", "/beta/live/offexchange", {"page": 1, "page_size": page_size}),
            QuiverDataset("Quiver新闻", "/beta/live/quivernews", {"page": 1, "page_size": page_size}),
        )
        result: dict[str, list[dict[str, Any]]] = {}
        for dataset in datasets:
            rows = self.get(dataset.path, **dataset.params)
            if watchlist and dataset.name != "Quiver新闻":
                rows = [
                    row
                    for row in rows
                    if str(row.get("Ticker") or row.get("ticker") or "").upper() in watchlist
                ]
            result[dataset.name] = rows
        return result

