import json
from dataclasses import replace

import pytest

from scripts.fetch_binance_contract_data import (
    BinanceContractSnapshot,
    classify_contract_signal,
    contract_symbols,
    filter_stock_contract_symbols,
    kline_metrics,
)
import scripts.fetch_binance_contract_data as contract_data
import scripts.push_binance_long_signals as long_signals
from scripts.push_binance_long_signals import (
    build_long_signal_card,
    long_candidates,
    selected_signals,
    signal_candidates,
)


@pytest.fixture(autouse=True)
def isolate_binance_sim_state(tmp_path, monkeypatch):
    monkeypatch.setattr(long_signals, "SIM_STATE_PATH", tmp_path / "binance_contract_sim_state.json")


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


def test_classify_contract_signal_uses_oi_and_official_taker_flow_confirmation():
    long_signal, long_score = classify_contract_signal(
        price_change_pct_24h=2.0,
        kline_return_pct=1.4,
        taker_buy_quote_ratio=0.49,
        last_funding_rate=0.0001,
        open_interest_change_pct=3.0,
        taker_buy_sell_buy_ratio=0.56,
    )
    short_signal, short_score = classify_contract_signal(
        price_change_pct_24h=-2.0,
        kline_return_pct=-1.4,
        taker_buy_quote_ratio=0.51,
        last_funding_rate=-0.0001,
        open_interest_change_pct=3.0,
        taker_buy_sell_buy_ratio=0.44,
    )
    exhausted_signal, _ = classify_contract_signal(
        price_change_pct_24h=2.0,
        kline_return_pct=1.4,
        taker_buy_quote_ratio=0.56,
        last_funding_rate=0.0001,
        open_interest_change_pct=-3.0,
    )

    assert long_signal == "long_watch"
    assert long_score > 0
    assert short_signal == "short_watch"
    assert short_score < 0
    assert exhausted_signal == "neutral"


def test_classify_contract_signal_blocks_or_downgrades_mark_index_deviation():
    normal_signal, normal_score = classify_contract_signal(
        price_change_pct_24h=2.0,
        kline_return_pct=1.4,
        taker_buy_quote_ratio=0.56,
        last_funding_rate=0.0001,
        open_interest_change_pct=3.0,
        mark_index_deviation_pct=0.2,
    )
    downgraded_signal, downgraded_score = classify_contract_signal(
        price_change_pct_24h=2.0,
        kline_return_pct=1.4,
        taker_buy_quote_ratio=0.56,
        last_funding_rate=0.0001,
        open_interest_change_pct=3.0,
        mark_index_deviation_pct=0.5,
    )
    blocked_signal, _ = classify_contract_signal(
        price_change_pct_24h=2.0,
        kline_return_pct=1.4,
        taker_buy_quote_ratio=0.56,
        last_funding_rate=0.0001,
        open_interest_change_pct=3.0,
        mark_index_deviation_pct=0.81,
    )

    assert normal_signal == "long_watch"
    assert downgraded_signal == "long_watch"
    assert downgraded_score < normal_score
    assert blocked_signal == "neutral"


def test_taker_buy_sell_metrics_calculates_aggregate_buy_ratio(monkeypatch):
    def fake_optional_request_json(*args, **kwargs):
        return [
            {"buyVol": "30", "sellVol": "20", "buySellRatio": "1.5"},
            {"buyVol": "70", "sellVol": "30", "buySellRatio": "2.3333"},
        ]

    monkeypatch.setattr(contract_data, "optional_request_json", fake_optional_request_json)

    metrics = contract_data.taker_buy_sell_metrics(
        "https://fapi.binance.com",
        "MUUSDT",
        interval="1h",
        limit=2,
        timeout=10,
    )

    assert round(metrics["taker_buy_sell_ratio"], 2) == 2.0
    assert round(metrics["taker_buy_sell_buy_ratio"], 2) == 0.67


def _snapshot(
    symbol: str,
    signal: str,
    score: float,
    *,
    price: float = 100,
    kline_range_pct: float = 3.0,
) -> BinanceContractSnapshot:
    return BinanceContractSnapshot(
        symbol=symbol,
        market="usdm",
        last_price=price,
        mark_price=price,
        index_price=price,
        price_change_pct_24h=2,
        high_price_24h=110,
        low_price_24h=90,
        quote_volume_24h=10_000_000,
        trade_count_24h=1000,
        last_funding_rate=0.0001,
        next_funding_time="2026-01-01T00:00:00+00:00",
        kline_interval="15m",
        kline_return_pct=1.2,
        kline_range_pct=kline_range_pct,
        taker_buy_quote_ratio=0.55,
        contract_signal=signal,
        signal_score=score,
        fetched_at="2026-01-01T00:00:00+00:00",
        open_interest=10_000,
        open_interest_change_pct=1.0,
        taker_buy_sell_ratio=1.22,
        taker_buy_sell_buy_ratio=0.55,
    )


def test_long_candidates_filters_long_watch_by_score():
    snapshots = [
        _snapshot("TSLAUSDT", "long_watch", 3.0),
        _snapshot("AAPLUSDT", "long_watch", -1.0),
        _snapshot("NVDAUSDT", "neutral", 5.0),
    ]
    assert [item.symbol for item in long_candidates(snapshots, min_score=0)] == ["TSLAUSDT"]


def test_signal_candidates_respects_requested_side(monkeypatch):
    monkeypatch.setenv("BINANCE_SIGNAL_MIN_QUOTE_VOLUME_24H", "0")
    snapshots = [
        _snapshot("TSLAUSDT", "long_watch", 3.0),
        _snapshot("AAPLUSDT", "short_watch", -4.0),
        _snapshot("NVDAUSDT", "neutral", 5.0),
    ]
    assert {item.symbol for item in signal_candidates(snapshots, side="both", min_score=0)} == {"TSLAUSDT", "AAPLUSDT"}
    assert [item.symbol for item in signal_candidates(snapshots, side="short", min_score=0)] == ["AAPLUSDT"]


def test_signal_candidates_filters_low_liquidity(monkeypatch):
    monkeypatch.setenv("BINANCE_SIGNAL_MIN_QUOTE_VOLUME_24H", "20000000")
    snapshots = [_snapshot("TSLAUSDT", "long_watch", 3.0)]
    assert signal_candidates(snapshots, side="both", min_score=2) == []


def _card_text(card: dict) -> str:
    parts = [card["header"]["title"]["content"]]
    for element in card["elements"]:
        if "text" in element:
            parts.append(element["text"]["content"])
        for note in element.get("elements", []):
            parts.append(note.get("content", ""))
    return "\n".join(parts)


def test_contract_signal_card_includes_long_and_short_sections():
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
    assert "开多精选" in text
    assert "信号强度怎么看" in text
    assert "做多逻辑" in text
    assert "信号强度含义" in text
    assert "模拟胜率" in text
    assert "买入点" in text
    assert "止损" in text
    assert "止盈1" in text
    assert "止盈2" in text
    assert "模拟开单" in text
    assert "方向 做多" in text
    assert "预估保证金" in text
    assert "0.5%-1%" in text


def test_selected_signals_keeps_top_three_per_side():
    snapshots = [
        _snapshot("L1USDT", "long_watch", 1.0),
        _snapshot("L2USDT", "long_watch", 2.0),
        _snapshot("L3USDT", "long_watch", 3.0),
        _snapshot("L4USDT", "long_watch", 4.0),
        _snapshot("S1USDT", "short_watch", -1.0),
        _snapshot("S2USDT", "short_watch", -2.0),
        _snapshot("S3USDT", "short_watch", -3.0),
        _snapshot("S4USDT", "short_watch", -4.0),
    ]

    selected = selected_signals(snapshots)

    assert [item.symbol for item in selected] == [
        "L4USDT", "L3USDT", "L2USDT", "S4USDT", "S3USDT", "S2USDT"
    ]


def test_contract_signal_card_shows_top_three_rows_per_side():
    signals = [
        _snapshot("L1USDT", "long_watch", 1.0),
        _snapshot("L2USDT", "long_watch", 2.0),
        _snapshot("L3USDT", "long_watch", 3.0),
        _snapshot("L4USDT", "long_watch", 4.0),
        _snapshot("S1USDT", "short_watch", -1.0),
        _snapshot("S2USDT", "short_watch", -2.0),
        _snapshot("S3USDT", "short_watch", -3.0),
        _snapshot("S4USDT", "short_watch", -4.0),
    ]
    card = long_signals.build_contract_signal_card(
        signals,
        all_snapshots=[],
        errors=[],
        interval="15m",
        limit=96,
        side="both",
    )
    text = _card_text(card)

    assert "开多精选（最多 3 支）" in text
    assert "开空精选（最多 3 支）" in text
    assert "L4USDT" in text
    assert "L3USDT" in text
    assert "L2USDT" in text
    assert "L1USDT" not in text
    assert "S4USDT" in text
    assert "S3USDT" in text
    assert "S2USDT" in text
    assert "S1USDT" not in text


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
    assert "买卖点：等待确认，当前不提供入场点" in text
    assert "早期观察阶段不建仓" in text


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


def test_run_pushes_selected_short_signal(monkeypatch):
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
    assert sent_cards


def test_run_opens_simulated_order_only_when_signal_triggers(monkeypatch):
    sent_cards = []
    monkeypatch.setattr(
        long_signals,
        "fetch_contract_snapshots",
        lambda *args, **kwargs: ([_snapshot("TSLAUSDT", "long_watch", 3.0)], []),
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

    state = json.loads(long_signals.SIM_STATE_PATH.read_text(encoding="utf-8"))
    assert result["simulation"]["stats"]["open_count"] == 1
    assert state["orders"][0]["symbol"] == "TSLAUSDT"
    assert state["orders"][0]["status"] == "open"
    assert sent_cards


def test_early_start_watch_does_not_open_simulated_order():
    early = replace(
        _snapshot("TSLAUSDT", "long_watch", 3.0),
        last_price=95,
        mark_price=95,
        index_price=95,
    )

    assert long_signals._long_signal_phase(early) == "early_start_watch"
    assert long_signals._trade_plan_values(early) is None
    result = long_signals._update_sim_orders(snapshots=[early], signals=[], dry_run=False)
    assert result["stats"]["open_count"] == 0


def test_simulated_order_closes_on_take_profit_and_updates_win_rate():
    open_result = long_signals._update_sim_orders(
        snapshots=[_snapshot("TSLAUSDT", "long_watch", 3.0, price=100, kline_range_pct=3.0)],
        signals=[_snapshot("TSLAUSDT", "long_watch", 3.0, price=100, kline_range_pct=3.0)],
        dry_run=False,
    )
    assert open_result["stats"]["open_count"] == 1

    close_result = long_signals._update_sim_orders(
        snapshots=[_snapshot("TSLAUSDT", "neutral", 0.0, price=102.2, kline_range_pct=3.0)],
        signals=[],
        dry_run=False,
    )
    assert close_result["stats"]["open_count"] == 0
    assert close_result["stats"]["closed_count"] == 1
    assert close_result["stats"]["wins"] == 1
    assert close_result["stats"]["win_rate"] == 100.0
    assert close_result["events"][0]["type"] == "close"


def test_run_pushes_card_when_simulated_order_closes_without_new_signal(monkeypatch):
    long_signals._update_sim_orders(
        snapshots=[_snapshot("TSLAUSDT", "long_watch", 3.0, price=100, kline_range_pct=3.0)],
        signals=[_snapshot("TSLAUSDT", "long_watch", 3.0, price=100, kline_range_pct=3.0)],
        dry_run=False,
    )
    sent_cards = []
    monkeypatch.setattr(
        long_signals,
        "fetch_contract_snapshots",
        lambda *args, **kwargs: ([_snapshot("TSLAUSDT", "neutral", 0.0, price=102.2, kline_range_pct=3.0)], []),
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

    assert result["signal_count"] == 0
    assert result["simulation"]["stats"]["closed_count"] == 1
    assert result["pushed"] is True
    assert sent_cards


def test_side_short_selects_only_short_signals(monkeypatch):
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


def test_run_limits_pushed_signals_to_top_three_per_side(monkeypatch):
    sent_cards = []
    snapshots = [
        _snapshot("L1USDT", "long_watch", 1.0),
        _snapshot("L2USDT", "long_watch", 2.0),
        _snapshot("L3USDT", "long_watch", 3.0),
        _snapshot("L4USDT", "long_watch", 4.0),
        _snapshot("S1USDT", "short_watch", -1.0),
        _snapshot("S2USDT", "short_watch", -2.0),
        _snapshot("S3USDT", "short_watch", -3.0),
        _snapshot("S4USDT", "short_watch", -4.0),
    ]
    monkeypatch.setattr(long_signals, "fetch_contract_snapshots", lambda *args, **kwargs: (snapshots, []))
    monkeypatch.setattr(long_signals, "send_card", lambda card: sent_cards.append(card))

    result = long_signals.run(
        market="usdm",
        symbols="L1USDT,L2USDT,L3USDT,L4USDT,S1USDT,S2USDT,S3USDT,S4USDT",
        interval="15m",
        limit=96,
        timeout=10,
        side="both",
        min_score=0,
        dry_run=False,
        push_empty=False,
    )
    state = json.loads(long_signals.SIM_STATE_PATH.read_text(encoding="utf-8"))

    assert result["raw_signal_count"] == 8
    assert result["signal_count"] == 6
    assert result["longs"] == ["L4USDT", "L3USDT", "L2USDT"]
    assert result["shorts"] == ["S4USDT", "S3USDT", "S2USDT"]
    assert [order["symbol"] for order in state["orders"]] == ["L4USDT", "L3USDT", "L2USDT"]
    assert sent_cards
