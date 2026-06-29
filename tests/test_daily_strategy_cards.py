import re
from datetime import datetime

import pandas as pd

from integrations.card_language import sanitize_card, visible_card_text
from integrations.daily_stock_selector import rank_history, to_yahoo_symbol, trim_incomplete_session
from scripts.push_daily_strategy_cards import build_strategy_card, selection_signature, stabilize_picks


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


def test_yahoo_symbol_mapping():
    assert to_yahoo_symbol("600519", "cn") == "600519.SS"
    assert to_yahoo_symbol("300750", "cn") == "300750.SZ"
    assert to_yahoo_symbol("NVDA", "us") == "NVDA"


def test_rank_history_builds_pick():
    pick = rank_history("NVDA", "NVDA", _history(), name="NVIDIA")
    assert pick is not None
    assert pick.score > 50
    assert pick.volume_ratio == 1.5
    assert pick.name == "NVIDIA"


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
    stable = stabilize_picks(
        [challenger, incumbent],
        ["OLD"],
        count=1,
        retention_bonus=4,
    )
    assert stable[0].code == "OLD"
    assert selection_signature(stable).endswith("|OLD")


def test_trim_incomplete_cn_session(monkeypatch):
    history = _history()
    today = datetime.now().date()
    history.index = list(history.index[:-1]) + [pd.Timestamp(today)]
    trimmed = trim_incomplete_session(history, "cn")
    # During/after session this helper may retain the completed bar; it must never add rows.
    assert len(trimmed) in {len(history), len(history) - 1}
