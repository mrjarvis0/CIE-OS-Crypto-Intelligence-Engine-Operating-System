"""
CIE-OS
A02 News Intelligence Agent

Module:
    core.models

Purpose:
    Canonical data models for the ingestion pipeline (Phase 1).

Design goals:
    - Pydantic v2
    - Plain data — no business logic
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

EntityType = Literal["stock", "crypto", "forex"]


class RawItem(BaseModel):
    """Raw item as returned by a connector, before any processing."""

    source: str
    source_key: str
    url: str | None = None
    title: str
    content: str = ""
    author: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    platform: str = "web"


class NormalizedItem(BaseModel):
    """Cleaned, deduplicated, entity-tagged item ready for storage."""

    id: int | None = None
    source: str
    source_key: str
    url: str | None = None
    title: str
    content: str = ""
    author: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    language: str = "en"
    platform: str = "web"
    title_fingerprint: str = ""
    content_fingerprint: str = ""
    entities: list["Entity"] = Field(default_factory=list)


class Entity(BaseModel):
    """A financial entity mentioned in an item."""

    type: EntityType
    symbol: str
    name: str | None = None
    context: str | None = None


class IngestReport(BaseModel):
    """Result of one ingestion cycle."""

    fetched: int = 0
    stored: int = 0
    duplicates: int = 0
    failed: int = 0
    narratives: int = 0
    errors: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


__all__ = [
    "EntityType",
    "RawItem",
    "NormalizedItem",
    "Entity",
    "IngestReport",
]
