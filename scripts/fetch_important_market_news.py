"""Fetch important A-share / US-stock related flash news into the local intelligence pool."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.intelligence_service import (  # noqa: E402
    IntelligenceService,
    IntelligenceServiceError,
    _IMPORTANT_KEYWORDS_MARKER,
)
from src.storage import IntelligenceSource  # noqa: E402


DEFAULT_MARKETS = {"cn", "us", "global"}


def _enable_existing_source(service: IntelligenceService, source_id: int) -> None:
    with service.repo.db.get_session() as session:
        row = session.get(IntelligenceSource, source_id)
        if row is None:
            return
        row.enabled = True
        row.updated_at = datetime.now()
        session.commit()


def _template_is_important(template: dict[str, Any], markets: set[str]) -> bool:
    if template.get("source_type") != "newsnow":
        return False
    if str(template.get("market") or "").lower() not in markets:
        return False
    return _IMPORTANT_KEYWORDS_MARKER in str(template.get("description") or "")


def ensure_important_sources(service: IntelligenceService, *, markets: set[str]) -> list[dict[str, Any]]:
    templates = service.list_source_templates(source_type="newsnow")["items"]
    selected = [template for template in templates if _template_is_important(template, markets)]
    ensured: list[dict[str, Any]] = []
    for template in selected:
        existing = service.repo.get_source_by_name(str(template["name"]))
        if existing is not None:
            if not existing.enabled:
                _enable_existing_source(service, existing.id)
            ensured.append({"created": False, "source_id": existing.id, "name": existing.name})
            continue
        try:
            source = service.create_source_from_template(str(template["template_id"]), {"enabled": True})
        except IntelligenceServiceError as exc:
            print(f"important-news source skipped: {template['template_id']} error={exc}")
            continue
        ensured.append({"created": True, "source_id": source["id"], "name": source["name"]})
    return ensured


def fetch_important_sources(service: IntelligenceService, ensured: list[dict[str, Any]], *, dry_run: bool) -> dict[str, Any]:
    results = []
    saved_count = 0
    fetched_count = 0
    for item in ensured:
        source_id = int(item["source_id"])
        try:
            result = service.fetch_source(source_id, dry_run=dry_run)
        except Exception as exc:
            message = service._sanitize_error(exc)
            results.append({"ok": False, "source_id": source_id, "name": item["name"], "error": message})
            print(f"important-news fetch failed: {item['name']} error={message}")
            continue
        result["name"] = item["name"]
        results.append(result)
        saved_count += int(result.get("saved_count") or 0)
        fetched_count += int(result.get("fetched_count") or 0)
    return {
        "ok": True,
        "source_count": len(ensured),
        "fetched_count": fetched_count,
        "saved_count": saved_count,
        "dry_run": dry_run,
        "results": results,
    }


def parse_markets(value: str) -> set[str]:
    markets = {item.strip().lower() for item in value.split(",") if item.strip()}
    return markets or set(DEFAULT_MARKETS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch important A-share / US-stock related flash news.")
    parser.add_argument("--markets", default=os.getenv("IMPORTANT_MARKET_NEWS_MARKETS", "cn,us,global"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    service = IntelligenceService()
    ensured = ensure_important_sources(service, markets=parse_markets(args.markets))
    result = fetch_important_sources(service, ensured, dry_run=args.dry_run)
    print(
        "important-news done: "
        f"sources={result['source_count']} fetched={result['fetched_count']} "
        f"saved={result['saved_count']} dry_run={result['dry_run']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
