"""Self-heal missed Feishu strategy pushes inside critical market windows."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.push_daily_strategy_cards import load_state, run_once as push_preopen
from scripts.push_post_close_review import run_once as push_review
from scripts.push_strategy_digest import configure_console_encoding


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class WatchdogTask:
    key: str
    label: str
    market: str
    state_key: str
    timestamp_key: str
    start: time
    end: time
    weekdays: tuple[int, ...]
    runner: Callable[[], None]


def _run_cn_preopen() -> None:
    push_preopen(market="cn", force=True)


def _run_us_preopen() -> None:
    push_preopen(market="us", force=True)


def _run_cn_midday_review() -> None:
    push_review(market="cn", session="midday", force=True)


def _run_cn_close_review() -> None:
    push_review(market="cn", session="close", force=True)


def _run_us_close_review() -> None:
    push_review(market="us", session="close", force=True)


TASKS: tuple[WatchdogTask, ...] = (
    WatchdogTask(
        key="cn-preopen",
        label="A-share pre-open strategy",
        market="cn",
        state_key="a",
        timestamp_key="pushed_at",
        start=time(8, 50),
        end=time(13, 30),
        weekdays=(0, 1, 2, 3, 4),
        runner=_run_cn_preopen,
    ),
    WatchdogTask(
        key="cn-midday-review",
        label="A-share midday review",
        market="cn",
        state_key="a",
        timestamp_key="midday_reviewed_at",
        start=time(11, 45),
        end=time(13, 30),
        weekdays=(0, 1, 2, 3, 4),
        runner=_run_cn_midday_review,
    ),
    WatchdogTask(
        key="cn-review",
        label="A-share post-close review",
        market="cn",
        state_key="a",
        timestamp_key="reviewed_at",
        start=time(15, 20),
        end=time(17, 0),
        weekdays=(0, 1, 2, 3, 4),
        runner=_run_cn_close_review,
    ),
    WatchdogTask(
        key="us-preopen",
        label="US-stock pre-open strategy",
        market="us",
        state_key="us",
        timestamp_key="pushed_at",
        start=time(20, 50),
        end=time(21, 29),
        weekdays=(0, 1, 2, 3, 4),
        runner=_run_us_preopen,
    ),
    WatchdogTask(
        key="us-review",
        label="US-stock post-close review",
        market="us",
        state_key="us",
        timestamp_key="reviewed_at",
        start=time(6, 30),
        end=time(8, 0),
        weekdays=(1, 2, 3, 4, 5),
        runner=_run_us_close_review,
    ),
)


def _parse_local_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(LOCAL_TZ)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


def _timestamp_local_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ).date()


def _env_flag(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def task_is_in_window(task: WatchdogTask, now: datetime) -> bool:
    local_now = now.astimezone(LOCAL_TZ)
    return local_now.weekday() in task.weekdays and task.start <= local_now.time() <= task.end


def task_already_sent_today(task: WatchdogTask, state: dict[str, Any], now: datetime) -> bool:
    section = state.get(task.state_key) or {}
    return _timestamp_local_date(section.get(task.timestamp_key)) == now.astimezone(LOCAL_TZ).date()


def due_tasks(
    *,
    state: dict[str, Any],
    now: datetime,
    task_filter: str = "all",
) -> list[WatchdogTask]:
    selected: list[WatchdogTask] = []
    for task in TASKS:
        if task_filter != "all" and task.key != task_filter:
            continue
        if not task_is_in_window(task, now):
            continue
        if task_already_sent_today(task, state, now):
            continue
        selected.append(task)
    return selected


def run_watchdog(*, task_filter: str = "all", dry_run: bool = False, now: datetime | None = None) -> list[str]:
    load_dotenv(ROOT / ".env")
    if not _env_flag("FEISHU_STRATEGY_WATCHDOG_ENABLED", "true"):
        print("Strategy watchdog disabled by FEISHU_STRATEGY_WATCHDOG_ENABLED")
        return []

    current = now or datetime.now(LOCAL_TZ)
    state = load_state()
    selected = due_tasks(state=state, now=current, task_filter=task_filter)
    if dry_run:
        print(
            json.dumps(
                {
                    "now": current.astimezone(LOCAL_TZ).isoformat(timespec="seconds"),
                    "due_tasks": [task.key for task in selected],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return [task.key for task in selected]

    completed: list[str] = []
    for task in selected:
        print(f"Watchdog补发开始：{task.key} ({task.label})")
        task.runner()
        completed.append(task.key)
    if completed:
        print("Watchdog补发完成：" + ", ".join(completed))
    else:
        print("Watchdog检查完成：没有需要补发的任务")
    return completed


def main() -> int:
    configure_console_encoding()
    parser = argparse.ArgumentParser(description="补发错过窗口的飞书策略关键卡片")
    parser.add_argument(
        "--task",
        choices=("all", *(task.key for task in TASKS)),
        default="all",
        help="Only check one task",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only print due tasks")
    parser.add_argument("--now", help="Override local time for deterministic checks")
    args = parser.parse_args()
    run_watchdog(task_filter=args.task, dry_run=args.dry_run, now=_parse_local_now(args.now))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
