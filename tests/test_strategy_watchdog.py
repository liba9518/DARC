from datetime import datetime
from zoneinfo import ZoneInfo

import scripts.push_strategy_watchdog as watchdog
from scripts.push_strategy_watchdog import TASKS, due_tasks, run_watchdog


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def _task(key: str):
    return next(task for task in TASKS if task.key == key)


def test_watchdog_only_contains_binance_contract_task():
    assert [task.key for task in TASKS] == ["binance-contract"]


def test_watchdog_selects_binance_contract_task_any_time():
    now = datetime(2026, 7, 3, 8, 40, tzinfo=LOCAL_TZ)
    assert due_tasks(now=now, task_filter="all") == [_task("binance-contract")]
    assert due_tasks(now=now, task_filter="binance-contract") == [_task("binance-contract")]


def test_watchdog_does_not_run_legacy_stock_tasks():
    now = datetime(2026, 7, 3, 8, 40, tzinfo=LOCAL_TZ)
    assert due_tasks(now=now, task_filter="kr-preopen") == []
    assert due_tasks(now=now, task_filter="us-review") == []


def test_run_watchdog_calls_contract_signal_runner(monkeypatch):
    calls = []

    def fake_runner(**kwargs):
        calls.append(kwargs)
        return {
            "long_count": 1,
            "short_count": 0,
            "signal_count": 1,
            "signals": ["BTCUSDT"],
            "pushed": True,
        }

    monkeypatch.setattr(watchdog, "push_contract_signals", fake_runner)

    completed = run_watchdog(
        task_filter="binance-contract",
        dry_run=False,
        now=datetime(2026, 7, 3, 8, 40, tzinfo=LOCAL_TZ),
    )

    assert completed == ["binance-contract"]
    assert calls[0]["market"] == "usdm"
    assert calls[0]["side"] == "both"
    assert calls[0]["push_empty"] is False
