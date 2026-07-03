from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.push_strategy_watchdog import TASKS, due_tasks, task_already_sent_today


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def _task(key: str):
    return next(task for task in TASKS if task.key == key)


def test_watchdog_selects_missing_cn_preopen_inside_grace_window():
    now = datetime(2026, 7, 3, 12, 55, tzinfo=LOCAL_TZ)
    selected = due_tasks(state={}, now=now, task_filter="all")
    keys = {task.key for task in selected}
    assert "cn-preopen" in keys
    assert "cn-midday-review" in keys
    assert "cn-review" not in keys


def test_watchdog_skips_task_already_sent_today():
    now = datetime(2026, 7, 3, 9, 10, tzinfo=LOCAL_TZ)
    task = _task("cn-preopen")
    state = {"a": {"pushed_at": "2026-07-03T08:59:00"}}
    assert task_already_sent_today(task, state, now) is True
    assert due_tasks(state=state, now=now, task_filter="cn-preopen") == []


def test_watchdog_us_close_uses_beijing_tuesday_to_saturday():
    monday_morning = datetime(2026, 7, 6, 6, 40, tzinfo=LOCAL_TZ)
    tuesday_morning = datetime(2026, 7, 7, 6, 40, tzinfo=LOCAL_TZ)
    assert due_tasks(state={}, now=monday_morning, task_filter="us-review") == []
    assert due_tasks(state={}, now=tuesday_morning, task_filter="us-review") == [_task("us-review")]
