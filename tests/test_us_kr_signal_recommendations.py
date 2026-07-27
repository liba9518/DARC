from scripts.recommend_us_kr_signals import (
    DEFAULT_KR_SIGNAL_POOL,
    minimum_liquidity,
    signal_count,
    signal_pool,
)


def test_kr_signal_pool_defaults(monkeypatch):
    monkeypatch.delenv("KR_SIGNAL_POOL", raising=False)
    assert signal_pool("kr") == DEFAULT_KR_SIGNAL_POOL.split(",")


def test_us_signal_pool_prefers_signal_pool(monkeypatch):
    monkeypatch.setenv("US_STRATEGY_POOL", "NVDA,TSLA")
    monkeypatch.setenv("US_SIGNAL_POOL", "AAPL,MSFT")
    assert signal_pool("us") == ["AAPL", "MSFT"]


def test_signal_count_defaults_and_override(monkeypatch):
    monkeypatch.delenv("KR_SIGNAL_MAX_COUNT", raising=False)
    monkeypatch.delenv("KR_SIGNAL_PICK_COUNT", raising=False)
    assert signal_count("kr") == 0
    monkeypatch.setenv("KR_SIGNAL_PICK_COUNT", "3")
    assert signal_count("kr") == 3
    monkeypatch.setenv("KR_SIGNAL_MAX_COUNT", "0")
    assert signal_count("kr") == 0
    assert signal_count("kr", override=7) == 7


def test_signal_minimum_liquidity(monkeypatch):
    monkeypatch.delenv("KR_MIN_DAILY_TURNOVER_KRW", raising=False)
    assert minimum_liquidity("kr") == 5_000_000_000
    monkeypatch.setenv("KR_MIN_DAILY_TURNOVER_KRW", "12000000000")
    assert minimum_liquidity("kr") == 12_000_000_000
