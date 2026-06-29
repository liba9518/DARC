"""Read structured research outputs produced by wesson9527/chokepoint-atlas."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


SCORE_FIELDS = (
    "constraint_score",
    "evidence_score",
    "consensus_score",
    "mispricing_score",
    "catalyst_score",
)
SUPPORTED_FILENAMES = {
    "research_pack.json",
    "lane_ranking.json",
    "lane_compare_input.json",
    "ai_factory_lane_input.json",
}


@dataclass(frozen=True)
class ChokepointLane:
    pack_id: str
    title: str
    lane: str
    end_system: str
    bottleneck: str
    total_score: float
    priority: str
    as_of_date: str
    top_names: tuple[str, ...]
    catalysts: tuple[str, ...]
    source_file: str
    stale: bool = False


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _priority(score: float) -> str:
    if score >= 4.2:
        return "极高优先级"
    if score >= 3.6:
        return "高优先级"
    if score >= 3.0:
        return "重点观察"
    return "暂低优先级"


def _company_score(company: dict[str, Any]) -> float:
    values = [_as_float(company.get(field)) for field in SCORE_FIELDS if company.get(field) is not None]
    return mean(values) if values else 0.0


def _lane_score(payload: dict[str, Any]) -> float:
    lane_score = payload.get("lane_score")
    if isinstance(lane_score, dict):
        total = lane_score.get("total_average")
        if total is not None:
            return round(_as_float(total), 2)
    companies = payload.get("companies")
    if isinstance(companies, list):
        values = [_company_score(company) for company in companies if isinstance(company, dict)]
        values = [value for value in values if value > 0]
        if values:
            return round(mean(values), 2)
    return 0.0


def _top_names(payload: dict[str, Any], limit: int = 5) -> tuple[str, ...]:
    top = payload.get("top_names")
    if isinstance(top, list):
        names = [
            str(item.get("ticker") if isinstance(item, dict) else item).strip().upper()
            for item in top
        ]
        return tuple(name for name in names if name)[:limit]
    companies = payload.get("companies")
    if not isinstance(companies, list):
        return ()
    ranked = sorted(
        (company for company in companies if isinstance(company, dict)),
        key=_company_score,
        reverse=True,
    )
    return tuple(str(company.get("ticker") or "").strip().upper() for company in ranked[:limit] if company.get("ticker"))


def _catalysts(payload: dict[str, Any], limit: int = 4) -> tuple[str, ...]:
    catalysts = payload.get("catalysts")
    if not isinstance(catalysts, list):
        return ()
    result = []
    for item in catalysts:
        if isinstance(item, dict):
            label = str(item.get("label") or "").strip()
            watch_for = str(item.get("watch_for") or "").strip()
            text = f"{label}：{watch_for}" if label and watch_for else label or watch_for
        else:
            text = str(item).strip()
        if text:
            result.append(text)
    return tuple(result[:limit])


def _is_stale(as_of_date: str, max_age_days: int) -> bool:
    if max_age_days <= 0 or not as_of_date:
        return False
    try:
        parsed = datetime.strptime(as_of_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return (date.today() - parsed).days > max_age_days


def _normalize_lane(payload: dict[str, Any], source: Path, max_age_days: int) -> ChokepointLane | None:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    thesis = payload.get("thesis") if isinstance(payload.get("thesis"), dict) else {}
    lane = str(payload.get("lane") or thesis.get("lane") or "").strip()
    title = str(payload.get("title") or meta.get("title") or lane).strip()
    if not lane or not title:
        return None
    score = _lane_score(payload)
    lane_score = payload.get("lane_score") if isinstance(payload.get("lane_score"), dict) else {}
    priority = str(payload.get("priority") or payload.get("lane_priority") or "").strip()
    if not priority:
        priority = _priority(score)
    as_of_date = str(payload.get("as_of_date") or meta.get("as_of_date") or "").strip()
    bottleneck = str(payload.get("bottleneck_call") or thesis.get("bottleneck_call") or "").strip()
    end_system = str(payload.get("end_system") or thesis.get("end_system") or "").strip()
    if not score and lane_score:
        score = _as_float(lane_score.get("total_average"))
    return ChokepointLane(
        pack_id=str(payload.get("pack_id") or meta.get("pack_id") or title).strip(),
        title=title,
        lane=lane,
        end_system=end_system,
        bottleneck=bottleneck,
        total_score=round(score, 2),
        priority=priority,
        as_of_date=as_of_date,
        top_names=_top_names(payload),
        catalysts=_catalysts(payload),
        source_file=str(source),
        stale=_is_stale(as_of_date, max_age_days),
    )


def _extract_lanes(payload: Any, source: Path, max_age_days: int) -> list[ChokepointLane]:
    if not isinstance(payload, dict):
        return []
    raw_lanes = payload.get("lanes")
    if isinstance(raw_lanes, list):
        return [
            lane
            for item in raw_lanes
            if isinstance(item, dict)
            for lane in [_normalize_lane(item, source, max_age_days)]
            if lane is not None
        ]
    lane = _normalize_lane(payload, source, max_age_days)
    return [lane] if lane is not None else []


def discover_json_files(paths: Iterable[str | Path]) -> list[Path]:
    result: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if path.is_file() and path.suffix.lower() == ".json":
            result.append(path)
        elif path.is_dir():
            result.extend(
                candidate
                for candidate in path.rglob("*.json")
                if candidate.name in SUPPORTED_FILENAMES
            )
    return sorted(set(path.resolve() for path in result))


def collect_chokepoint_lanes(
    paths: Iterable[str | Path],
    *,
    max_age_days: int = 45,
) -> tuple[list[ChokepointLane], list[str]]:
    lanes: dict[str, ChokepointLane] = {}
    errors: list[str] = []
    for path in discover_json_files(paths):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for lane in _extract_lanes(payload, path, max_age_days):
                dedupe_key = f"{lane.end_system.strip().lower()}|{lane.lane.strip().lower()}"
                existing = lanes.get(dedupe_key)
                if existing is None or lane.total_score > existing.total_score:
                    lanes[dedupe_key] = lane
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name} 读取失败：{exc}")
    return sorted(lanes.values(), key=lambda item: item.total_score, reverse=True), errors
