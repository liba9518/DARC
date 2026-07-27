from scripts.fetch_binance_contract_data import (
    BinanceContractSnapshot,
    classify_contract_signal,
    contract_symbols,
    filter_stock_contract_symbols,
    kline_metrics,
)
import scripts.fetch_binance_contract_data as contract_data
import scripts.push_binance_long_signals as long_signals
from scripts.push_binance_long_signals import build_long_signal_card, long_candidates, signal_candidates


def test_contract_symbols_defaults_to_stock_perp_pool(monkeypatch):
    monkeypatch.delenv("BINANCE_CONTRACT_SYMBOLS", raising=False)
    symbols = contract_symbols("usdm")
    assert symbols[:3] == ["TSLAUSDT", "AAPLUSDT", "NVDAUSDT"]
    assert "BTCUSDT" not in symbols


def test_contract_symbols_allows_env_override(monkeypatch):
    monkeypatch.setenv("BINANCE_CONTRACT_SYMBOLS", "TSLAUSDT, AAPLUSDT")
    assert contract_symbols("usdm") == ["TSLAUSDT", "AAPLUSDT"]


def test_contract_symbols_accepts_bare_stock_tickers_and_sand_alias(monkeypatch):
    monkeypatch.delenv("BINANCE_CONTRACT_SYMBOLS", raising=False)
    assert contract_symbols("usdm", "MU,SAND,SNDK") == ["MUUSDT", "SNDKUSDT", "SNDKUSDT"]


def test_filter_stock_contract_symbols_skips_crypto_contracts(monkeypatch):
    def fake_request_json(*args, **kwargs):
        return {
            "symbols": [
                {
                    "symbol": "TSLAUSDT",
                    "status": "TRADING",
                    "underlyingType": "EQUITY",
                    "contractType": "TRADIFI_PERPETUAL",
                },
                {
                    "symbol": "BTCUSDT",
                    "status": "TRADING",
                    "underlyingType": "COIN",
                    "contractType": "PERPETUAL",
                },
                {
                    "symbol": "SANDUSDT",
                    "status": "TRADING",
                    "underlyingType": "COIN",
                    "contractType": "PERPETUAL",
                },
                {
                    "symbol": "SNDKUSDT",
                    "status": "TRADING",
                    "underlyingType": "EQUITY",
                    "contractType": "TRADIFI_PERPETUAL",
                },
            ]
        }

    monkeypatch.setattr(contract_data, "request_json", fake_request_json)

    selected, errors = filter_stock_contract_symbols(
        ["TSLAUSDT", "BTCUSDT", "SANDUSDT", "SNDKUSDT"],
        market="usdm",
        timeout=10,
    )

    assert selected == ["TSLAUSDT", "SNDKUSDT"]
    assert any("BTCUSDT skipped" in error for error in errors)
    assert any("SANDUSDT skipped" in error for error in errors)


def test_kline_metrics_calculates_return_range_and_taker_ratio():
    klines = [
        [1, "100", "110", "95", "105", "10", 2, "1000", 3, "5", "600", "0"],
        [2, "105", "120", "100", "115", "12", 3, "1400", 4, "6", "700", "0"],
    ]
    metrics = kline_metrics(klines)
    assert round(metrics["return_pct"], 2) == 15.0
    assert round(metrics["range_pct"], 2) == 26.32
    assert round(metrics["taker_buy_quote_ratio"], 2) == 0.54


def test_classify_contract_signal_detects_long_and_short_watch():
    long_signal, long_score = classify_contract_signal(
        price_change_pct_24h=2.0,
        kline_return_pct=1.5,
        taker_buy_quote_ratio=0.55,
        last_funding_rate=0.0001,
    )
    short_signal, short_score = classify_contract_signal(
        price_change_pct_24h=-2.0,
        kline_return_pct=-1.5,
        taker_buy_quote_ratio=0.45,
        last_funding_rate=-0.0001,
    )
    neutral_signal, _ = classify_contract_signal(
        price_change_pct_24h=0.2,
        kline_return_pct=0.1,
        taker_buy_quote_ratio=0.50,
        last_funding_rate=0.0001,
    )
    assert long_signal == "long_watch"
    assert long_score > 0
    assert short_signal == "short_watch"
    assert short_score < 0
    assert neutral_signal == "neutral"


def _snapshot(symbol: str, signal: str, score: float) -> BinanceContractSnapshot:
    return BinanceContractSnapshot(
        symbol=symbol,
        market="usdm",
        last_price=100,
        mark_price=100,
        index_price=100,
        price_change_pct_24h=2,
        high_price_24h=110,
        low_price_24h=90,
        quote_volume_24h=1_000_000,
        trade_count_24h=1000,
        last_funding_rate=0.0001,
        next_funding_time="2026-01-01T00:00:00+00:00",
        kline_interval="15m",
        kline_return_pct=1.2,
        kline_range_pct=3.0,
        taker_buy_quote_ratio=0.55,
        contract_signal=signal,
        signal_score=score,
        fetched_at="2026-01-01T00:00:00+00:00",
    )


def test_long_candidates_filters_long_watch_by_score():
    snapshots = [
        _snapshot("TSLAUSDT", "long_watch", 3.0),
        _snapshot("AAPLUSDT", "long_watch", -1.0),
        _snapshot("NVDAUSDT", "neutral", 5.0),
    ]
    assert [item.symbol for item in long_candidates(snapshots, min_score=0)] == ["TSLAUSDT"]


def test_signal_candidates_filters_long_and_short_watch_by_side():
    snapshots = [
        _snapshot("TSLAUSDT", "long_watch", 3.0),
        _snapshot("AAPLUSDT", "short_watch", -4.0),
        _snapshot("NVDAUSDT", "neutral", 5.0),
    ]
    assert [item.symbol for item in signal_candidates(snapshots, side="both", min_score=0)] == [
        "TSLAUSDT",
        "AAPLUSDT",
    ]
    assert [item.symbol for item in signal_candidates(snapshots, side="short", min_score=0)] == ["AAPLUSDT"]


def _card_text(card: dict) -> str:
    parts = [card["header"]["title"]["content"]]
    for element in card["elements"]:
        if "text" in element:
            parts.append(element["text"]["content"])
        for note in element.get("elements", []):
            parts.append(note.get("content", ""))
    return "\n".join(parts)


def test_contract_signal_card_includes_trade_plan_for_long_and_short():
    card = long_signals.build_contract_signal_card(
        [_snapshot("TSLAUSDT", "long_watch", 3.0), _snapshot("AAPLUSDT", "short_watch", -4.0)],
        all_snapshots=[],
        errors=[],
        interval="15m",
        limit=96,
        side="both",
    )
    text = _card_text(card)

    assert "TSLAUSDT" in text
    assert "AAPLUSDT" in text
    assert "Entry" in text
    assert "SL" in text
    assert "TP1" in text
    assert "TP2" in text
    assert "0.5%-1%" in text


def test_contract_signal_card_does_not_show_entry_plan_for_neutral():
    card = long_signals.build_contract_signal_card(
        [],
        all_snapshots=[_snapshot("NVDAUSDT", "neutral", 0.2)],
        errors=[],
        interval="15m",
        limit=96,
        side="both",
    )
    text = _card_text(card)

    assert "NVDAUSDT" in text
    assert "无触发" in text or "鏈Е鍙" in text
    assert "不提供 Entry / SL / TP" in text


def test_build_long_signal_card_marks_empty_status():
    card = build_long_signal_card(
        [],
        all_snapshots=[_snapshot("TSLAUSDT", "neutral", 0.2)],
        errors=[],
        interval="15m",
        limit=96,
    )
    assert card["header"]["template"] == "grey"
    assert "当前无触发" in card["header"]["title"]["content"]
    assert "股票合约" in card["header"]["title"]["content"]


def test_run_does_not_push_empty_long_signal_card(monkeypatch):
    sent_cards = []
    monkeypatch.setattr(
        long_signals,
        "fetch_contract_snapshots",
        lambda *args, **kwargs: ([_snapshot("TSLAUSDT", "neutral", 0.2)], []),
    )
    monkeypatch.setattr(long_signals, "send_card", lambda card: sent_cards.append(card))

    result = long_signals.run(
        market="usdm",
        symbols="TSLAUSDT",
        interval="15m",
        limit=96,
        timeout=10,
        side="both",
        min_score=0,
        dry_run=False,
        push_empty=False,
    )

    assert result["long_count"] == 0
    assert result["pushed"] is False
    assert sent_cards == []


def test_run_pushes_short_signal_when_side_allows(monkeypatch):
    sent_cards = []
    monkeypatch.setattr(
        long_signals,
        "fetch_contract_snapshots",
        lambda *args, **kwargs: ([_snapshot("AAPLUSDT", "short_watch", -3.0)], []),
    )
    monkeypatch.setattr(long_signals, "send_card", lambda card: sent_cards.append(card))

    result = long_signals.run(
        market="usdm",
        symbols="AAPLUSDT",
        interval="15m",
        limit=96,
        timeout=10,
        side="both",
        min_score=0,
        dry_run=False,
        push_empty=False,
    )

    assert result["long_count"] == 0
    assert result["short_count"] == 1
    assert result["pushed"] is True
    assert len(sent_cards) == 1


def test_run_side_short_excludes_long_candidates_from_result(monkeypatch):
    sent_cards = []
    monkeypatch.setattr(
        long_signals,
        "fetch_contract_snapshots",
        lambda *args, **kwargs: (
            [
                _snapshot("TSLAUSDT", "long_watch", 3.0),
                _snapshot("AAPLUSDT", "short_watch", -4.0),
            ],
            [],
        ),
    )
    monkeypatch.setattr(long_signals, "send_card", lambda card: sent_cards.append(card))

    result = long_signals.run(
        market="usdm",
        symbols="TSLAUSDT,AAPLUSDT",
        interval="15m",
        limit=96,
        timeout=10,
        side="short",
        min_score=0,
        dry_run=False,
        push_empty=False,
    )

    assert result["long_count"] == 0
    assert result["short_count"] == 1
    assert result["longs"] == []
    assert result["shorts"] == ["AAPLUSDT"]
    assert result["signals"] == ["AAPLUSDT"]
    assert result["pushed"] is True
