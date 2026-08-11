"""Self-heal Feishu Binance stock contract signal pushes.

The Feishu robot is intentionally limited to Binance TradFi/equity perpetual
long/short signals. It does not run crypto perpetual contracts, US/Korea stock
pre-open cards, post-close reviews, or intraday stock monitors.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_binance_contract_data import DEFAULT_INTERVAL, DEFAULT_LIMIT
from scripts.push_binance_long_signals import run as push_contract_signals
from scripts.push_strategy_digest import configure_console_encoding


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class WatchdogTask:
    key: str
    label: str
    runner: Callable[[], dict[str, Any]]


def _env_flag(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return min(maximum, max(minimum, int(raw_value)))
    except ValueError:
        return default


def _env_float(name: str, default: float, *, minimum: float) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return max(minimum, float(raw_value))
    except ValueError:
        return default


def _run_binance_contract_signals() -> dict[str, Any]:
    market = os.getenv("BINANCE_CONTRACT_MARKET", "usdm")
    symbols = os.getenv("BINANCE_CONTRACT_SYMBOLS") or None
    side = "long"
    min_score = float(os.getenv("BINANCE_SIGNAL_MIN_SCORE", os.getenv("BINANCE_LONG_SIGNAL_MIN_SCORE", "2")))
    return push_contract_signals(
        market=market,
        symbols=symbols,
        interval=os.getenv("BINANCE_CONTRACT_INTERVAL", DEFAULT_INTERVAL),
        limit=_env_int("BINANCE_CONTRACT_KLINE_LIMIT", DEFAULT_LIMIT, minimum=2, maximum=1000),
        timeout=_env_float("BINANCE_CONTRACT_TIMEOUT_SEC", 10.0, minimum=1.0),
        side=side,
        min_score=min_score,
        dry_run=False,
        push_empty=False,
    )


TASKS: tuple[WatchdogTask, ...] = (
    WatchdogTask(
        key="binance-contract",
        label="Binance stock contract selected long signals",
        runner=_run_binance_contract_signals,
    ),
)


def _parse_local_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(LOCAL_TZ)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


def due_tasks(
    *,
    now: datetime,
    task_filter: str = "all",
) -> list[WatchdogTask]:
    _ = now
    selected: list[WatchdogTask] = []
    for task in TASKS:
        if task_filter != "all" and task.key != task_filter:
            continue
        selected.append(task)
    return selected


def run_watchdog(*, task_filter: str = "all", dry_run: bool = False, now: datetime | None = None) -> list[str]:
    load_dotenv(ROOT / ".env")
    if not _env_flag("BINANCE_CONTRACT_WATCHDOG_ENABLED", os.getenv("FEISHU_STRATEGY_WATCHDOG_ENABLED", "true")):
        print("Binance contract watchdog disabled by BINANCE_CONTRACT_WATCHDOG_ENABLED")
        return []

    current = now or datetime.now(LOCAL_TZ)
    selected = due_tasks(now=current, task_filter=task_filter)
    if dry_run:
        print(
            json.dumps(
                {
                    "now": current.astimezone(LOCAL_TZ).isoformat(timespec="seconds"),
                    "due_tasks": [task.key for task in selected],
                    "note": "Only Binance stock contract signals are scanned; no crypto or stock pre-open/review tasks are run.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return [task.key for task in selected]

    completed: list[str] = []
    for task in selected:
        print(f"Watchdog scan started: {task.key} ({task.label})")
        result = task.runner()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        completed.append(task.key)
    if completed:
        print("Watchdog scan completed: " + ", ".join(completed))
    else:
        print("Watchdog scan completed: no task selected")
    return completed


def main() -> int:
    configure_console_encoding()
    parser = argparse.ArgumentParser(description="Scan Binance stock contract signals and push Feishu only when triggered.")
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
