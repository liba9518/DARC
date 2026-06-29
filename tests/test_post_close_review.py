import re

from integrations.card_language import sanitize_card, visible_card_text
from integrations.daily_stock_selector import rank_history
from scripts.push_post_close_review import build_review_card, evaluate_previous
from tests.test_daily_strategy_cards import _history


def test_evaluate_previous_calculates_strategy_performance():
    results = evaluate_previous(
        [{"code": "AAA", "name": "Alpha", "signal_price": 100}],
        {"AAA": {"price": 103, "day_change": 2, "name": "Alpha"}},
    )
    assert results[0]["performance"] == 3


def test_review_card_contains_results_and_next_preview():
    pick = rank_history("AAA", "AAA", _history(), name="Alpha")
    assert pick is not None
    card = build_review_card(
        "us",
        [
            {
                "code": "AAA",
                "name": "Alpha",
                "signal_price": 100,
                "current_price": 103,
                "performance": 3,
                "day_change": 2,
            }
        ],
        [pick],
        ["AAA"],
        errors=[],
    )
    content = str(card)
    assert "收盘复盘" in content
    assert "明日优先关注名单" in content
    assert "3.00%" in content
    sanitized = sanitize_card(card)
    visible = visible_card_text(sanitized)
    residual = re.sub(r"（[A-Z][A-Z0-9.\-]{0,9}）", "", visible)
    assert re.search(r"[A-Za-z]", residual) is None
