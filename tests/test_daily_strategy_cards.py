import re
from dataclasses import replace
from datetime import datetime

import pandas as pd
import pytest
import requests

from integrations.card_language import sanitize_card, visible_card_text
from integrations.daily_stock_selector import rank_history, to_yahoo_symbol, trim_incomplete_session
import scripts.push_daily_strategy_cards as daily_cards
from scripts.push_daily_strategy_cards import build_strategy_card, market_pick_count, selection_signature, stabilize_picks


def _history():
    dates = pd.date_range("2026-01-01", periods=100, freq="B")
    close = pd.Series([100 + index * 0.8 for index in range(100)], index=dates)
    return pd.DataFrame(
        {
            "Close": close,
            "Open": close - 0.3,
            "High": close + 0.5,
            "Low": close - 0.5,
            "Volume": [1_000_000] * 99 + [1_500_000],
        },
        index=dates,
    )


def _contract_rebound_history():
    dates = pd.date_range("2026-01-01", periods=100, freq="B")
    close_values = [100.0] * 40
    close_values += [100 - 5 * (index + 1) / 30 for index in range(30)]
    close_values += [95.0] * 30
    close = pd.Series(close_values, index=dates)
    return pd.DataFrame(
        {
            "Close": close,
            "Open": close,
            "High": close,
            "Low": close,
            "Volume": [1_000_000] * 99 + [1_500_000],
        },
        index=dates,
    )


def test_yahoo_symbol_mapping():
    assert to_yahoo_symbol("600519", "cn") == "600519.SS"
    assert to_yahoo_symbol("300750", "cn") == "300750.SZ"
    assert to_yahoo_symbol("NVDA", "us") == "NVDA"
    assert to_yahoo_symbol("005930.KS", "kr") == "005930.KS"
    assert to_yahoo_symbol("035720.KQ", "kr") == "035720.KQ"
    assert to_yahoo_symbol("005930", "kr") == "005930.KS"


def test_rank_history_builds_pick():
    pick = rank_history("NVDA", "NVDA", _history(), name="NVIDIA")
    assert pick is not None
    assert pick.score > 50
    assert pick.volume_ratio == 1.5
    assert pick.name == "NVIDIA"


def test_us_contract_profile_relaxes_trend_gate():
    history = _contract_rebound_history()
    standard = rank_history("TSLA", "TSLA", history, name="Tesla")
    relaxed = rank_history("TSLA", "TSLA", history, name="Tesla", selection_profile="us_contract")
    assert standard is not None and relaxed is not None
    assert not standard.eligible
    assert relaxed.eligible


def test_us_quality_profile_rejects_unconfirmed_rebound():
    history = _contract_rebound_history()
    relaxed = rank_history("TSLA", "TSLA", history, name="Tesla", selection_profile="us_contract")
    quality = rank_history("TSLA", "TSLA", history, name="Tesla", selection_profile="us_quality")
    assert relaxed is not None and quality is not None
    assert relaxed.eligible
    assert not quality.eligible


def test_us_quality_profile_accepts_confirmed_high_quality_trend():
    dates = pd.date_range("2026-01-01", periods=100, freq="B")
    close = pd.Series(
        [100 + index * 0.25 + (1 if index % 3 else -1) for index in range(100)],
        index=dates,
    )
    history = pd.DataFrame(
        {"Close": close, "Volume": [1_000_000] * 99 + [1_500_000]},
        index=dates,
    )
    quality = rank_history("NVDA", "NVDA", history, name="NVIDIA", selection_profile="us_quality")
    assert quality is not None
    assert quality.eligible
    assert quality.confidence_points >= 8
    assert quality.capital_trace_score >= 58


def test_market_pick_count_defaults(monkeypatch):
    monkeypatch.delenv("DAILY_CARD_PICK_COUNT", raising=False)
    monkeypatch.delenv("US_DAILY_CARD_PICK_COUNT", raising=False)
    monkeypatch.delenv("KR_DAILY_CARD_PICK_COUNT", raising=False)
    assert market_pick_count("us") == 0
    assert market_pick_count("kr") == 0
    monkeypatch.setenv("DAILY_CARD_PICK_COUNT", "3")
    assert market_pick_count("us") == 0
    assert market_pick_count("kr") == 0
    monkeypatch.setenv("US_DAILY_CARD_PICK_COUNT", "4")
    assert market_pick_count("us") == 4


def test_stock_strategy_cards_disabled_by_default(monkeypatch):
    called = []
    monkeypatch.delenv("FEISHU_STOCK_CARDS_ENABLED", raising=False)
    monkeypatch.setattr(daily_cards, "generate_market_selection", lambda market: called.append(market))

    daily_cards.run_once(market="us")

    assert called == []


def test_card_contains_three_ranked_names():
    picks = [
        rank_history(code, code, _history(), name=code)
        for code in ("NVDA", "MSFT", "AVGO")
    ]
    card = build_strategy_card(
        "美股策略",
        "美国股票",
        [pick for pick in picks if pick is not None],
        template="blue",
    )
    content = str(sanitize_card(card))
    assert "英伟达" in content
    assert "微软" in content
    assert "博通" in content
    assert "英伟达（NVDA）" in content
    assert "微软（MSFT）" in content
    assert "博通（AVGO）" in content
    visible = visible_card_text(sanitize_card(card))
    residual = re.sub(r"（[A-Z][A-Z0-9.\-]{0,9}）", "", visible)
    assert re.search(r"[A-Za-z]", residual) is None


def test_stability_bonus_retains_close_incumbent():
    incumbent = rank_history("OLD", "OLD", _history(), name="OLD")
    challenger = rank_history("NEW", "NEW", _history() * 1.001, name="NEW")
    assert incumbent is not None and challenger is not None
    incumbent = replace(incumbent, eligible=True)
    challenger = replace(challenger, eligible=True)
    stable = stabilize_picks(
        [challenger, incumbent],
        ["OLD"],
        count=1,
        retention_bonus=4,
    )
    assert stable[0].code == "OLD"
    assert selection_signature(stable).endswith("|OLD")


def test_stability_uses_triggered_picks_without_fixed_count():
    triggered = rank_history("TRG", "TRG", _history(), name="TRG")
    reserve = rank_history("RSV", "RSV", _history(), name="RSV")
    assert triggered is not None and reserve is not None
    triggered = replace(triggered, eligible=True)
    reserve = replace(reserve, eligible=False, score=99)
    stable = stabilize_picks(
        [reserve, triggered],
        [],
        count=0,
        retention_bonus=4,
    )
    assert [pick.code for pick in stable] == ["TRG"]


def test_trim_incomplete_cn_session(monkeypatch):
    history = _history()
    today = datetime.now().date()
    history.index = list(history.index[:-1]) + [pd.Timestamp(today)]
    trimmed = trim_incomplete_session(history, "cn")
    # During/after session this helper may retain the completed bar; it must never add rows.
    assert len(trimmed) in {len(history), len(history) - 1}


class _FakeWebhookResponse:
    def __init__(self, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {"code": 0}

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"{self.status_code} error")
            error.response = self
            raise error

    def json(self):
        return self._body


def test_send_card_retries_transient_connection_reset(monkeypatch):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) == 1:
            raise requests.ConnectionError("remote host forcibly closed the connection")
        return _FakeWebhookResponse(200)

    monkeypatch.setenv("STOCK_FEISHU_WEBHOOK_URL", "https://open.feishu.cn/open-apis/bot/v2/hook/test")
    monkeypatch.setattr(daily_cards.requests, "post", fake_post)
    monkeypatch.setattr(daily_cards.time, "sleep", lambda _seconds: None)

    daily_cards.send_card({"config": {}, "header": {"title": {"tag": "plain_text", "content": "t"}}, "elements": []})

    assert len(calls) == 2


def test_send_card_does_not_retry_non_retryable_http_error(monkeypatch):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeWebhookResponse(400)

    monkeypatch.setenv("STOCK_FEISHU_WEBHOOK_URL", "https://open.feishu.cn/open-apis/bot/v2/hook/test")
    monkeypatch.setattr(daily_cards.requests, "post", fake_post)
    monkeypatch.setattr(daily_cards.time, "sleep", lambda _seconds: None)

    with pytest.raises(requests.HTTPError):
        daily_cards.send_card({"config": {}, "header": {"title": {"tag": "plain_text", "content": "t"}}, "elements": []})

    assert len(calls) == 1
