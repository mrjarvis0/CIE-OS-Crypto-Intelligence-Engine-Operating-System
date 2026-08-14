"""
CIE-OS
A02 News Intelligence Agent

Module:
    core.pipeline

Purpose:
    Orchestrates one ingestion cycle (Phase 1):
    fetch -> normalize -> dedup -> entity extraction -> store
"""

from __future__ import annotations

from agents.A02_News_Intelligence.config.paths import DATABASE_FILE
from agents.A02_News_Intelligence.config.settings import Settings
from agents.A02_News_Intelligence.intelligence.narrative import NarrativeEngine

from .dedup import looks_duplicate, note_seen
from .entities import extract_entities
from .fetch import fetch_all
from .models import IngestReport, NormalizedItem, RawItem
from .normalize import normalize_item
from .storage import Storage


def _process_batch(raw_items: list[RawItem]) -> list[NormalizedItem]:
    """Normalize + extract entities for raw items (pure, testable)."""

    normalized = []
    for raw in raw_items:
        item = normalize_item(raw)
        item.entities = extract_entities(f"{item.title} {item.content}")
        normalized.append(item)
    return normalized


async def ingest(settings: Settings | None = None, db_path: str | None = None) -> IngestReport:
    """Run one full ingestion cycle. Returns a report — never raises on data errors."""

    settings = settings or Settings()
    db_path = db_path or str(DATABASE_FILE)

    report = IngestReport()
    storage = Storage(db_path)
    await storage.init()

    raw_items, errors = await fetch_all(settings)
    report.fetched = len(raw_items)
    report.errors = errors
    report.failed = len(errors)
    report.sources = sorted({item.source for item in raw_items})

    seen_urls: set[str] = set()
    seen_title_fps: set[str] = set()
    seen_content_fps: set[str] = set()

    new_items: list[NormalizedItem] = []
    for item in _process_batch(raw_items):
        if looks_duplicate(
            item.url,
            item.title_fingerprint,
            item.content_fingerprint,
            seen_urls,
            seen_title_fps,
            seen_content_fps,
        ):
            report.duplicates += 1
            continue
        note_seen(
            item.url,
            item.title_fingerprint,
            item.content_fingerprint,
            seen_urls,
            seen_title_fps,
            seen_content_fps,
        )
        try:
            if await storage.is_duplicate(item.url, item.title_fingerprint, item.content_fingerprint):
                report.duplicates += 1
                continue
            await storage.insert_item(item)
            report.stored += 1
            new_items.append(item)
        except Exception as exc:  # keep the cycle alive on single-item failures
            report.failed += 1
            report.errors.append(f"{item.source}:{exc}")

    if new_items:
        engine = NarrativeEngine(
            window_hours=settings.narrative.window_hours,
            min_mentions=settings.narrative.min_mentions,
        )
        narratives = await engine.update(storage, new_items)
        report.narratives = len(narratives)

    return report


__all__ = ["ingest", "_process_batch"]
