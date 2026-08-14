"""
CIE-OS
A02 News Intelligence Agent

Module:
    intelligence.narrative

Purpose:
    Narrative intelligence engine (Phase 2):
    claims, clustering, stance, propagation metrics, FOMO score.

    FOMO is a SEPARATE score from truth/verification. It measures
    hype/urgency, never truthfulness.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from agents.A02_News_Intelligence.config.constants import (
    COORDINATION_MAX,
    EpistemicStatus,
    FOMO_MAX,
    NarrativeStatus,
)
from agents.A02_News_Intelligence.core.models import NormalizedItem

from .claims import extract_claim
from .cluster import best_match, similarity, DEFAULT_WEIGHTS
from .manipulation import coordination_score
from .stance import classify_stance
from .verification import verify_narrative

# ==============================================================================
# NARRATIVE ENGINE CONFIG
# ==============================================================================

# Clustering weights
NARRATIVE_WEIGHTS = {
    "title": 0.35,
    "entity": 0.35,
    "semantic": 0.30,
}

# Semantic similarity threshold for narrative matching
NARRATIVE_SEMANTIC_THRESHOLD = 0.65

# Temporal decay half-life for clustering (hours)
CLUSTER_HALF_LIFE_HOURS = 48.0

# ==============================================================================
# FOMO PARAMETERS
# ==============================================================================

_VELOCITY_CAP_PER_HOUR = 10.0
_PEAK_VELOCITY_PER_HOUR = 5.0
_URGENCY_WORDS = re.compile(
    r"\b(breaking|urgent|alert|just in|now|flash|exclusive|leak|insider|"
    r"shock|crash|surge|imminent|emergency|soaring|plunge)\b",
    re.IGNORECASE,
)


class Narrative(BaseModel):
    """A rumor/story cluster with propagation, verification and manipulation metrics."""

    id: int | None = None
    claim_text: str = ""
    entities: list[str] = Field(default_factory=list)
    status: str = NarrativeStatus.EMERGING
    first_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    mention_count: int = 1
    source_count: int = 1
    platforms: list[str] = Field(default_factory=list)
    stance_counts: dict[str, int] = Field(default_factory=lambda: {"support": 0, "deny": 0, "neutral": 0, "question": 0})
    fomo_score: float = 0.0
    velocity: float = 0.0
    epistemic_status: str = EpistemicStatus.UNCONFIRMED
    confidence: float = 0.0
    coordination_score: float = 0.0
    manipulation_flags: dict = Field(default_factory=dict)
    evidence: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    items: list[NormalizedItem] = Field(default_factory=list)


def _urgency_score(items: list[NormalizedItem]) -> float:
    """Fraction of items whose title contains urgency words (0..1)."""

    if not items:
        return 0.0
    hits = sum(1 for item in items if _URGENCY_WORDS.search(item.title))
    return hits / len(items)


def compute_fomo(narrative: Narrative, now: datetime | None = None) -> float:
    """FOMO 0-100: blend of mention velocity, source spread, platforms, urgency."""

    now = now or datetime.now(UTC)
    window_start = now - timedelta(hours=24)
    recent = [i for i in narrative.items if (i.published_at or i.fetched_at) >= window_start]
    hours_active = max(1.0, (narrative.last_seen - narrative.first_seen).total_seconds() / 3600.0)
    velocity = min(_VELOCITY_CAP_PER_HOUR, len(recent) / hours_active)
    narrative.velocity = round(velocity, 2)

    v = velocity / _VELOCITY_CAP_PER_HOUR
    s = min(1.0, narrative.source_count / 3.0)
    p = min(1.0, len(narrative.platforms) / 2.0)
    u = _urgency_score(narrative.items)

    narrative.fomo_score = round(
        FOMO_MAX * (0.35 * v + 0.25 * s + 0.2 * p + 0.2 * u),
        1,
    )
    return narrative.fomo_score


def compute_status(narrative: Narrative, now: datetime | None = None) -> str:
    """Lifecycle status based on velocity, stance and age."""

    now = now or datetime.now(UTC)
    stale_hours = (now - narrative.last_seen).total_seconds() / 3600.0
    if stale_hours > 48:
        return NarrativeStatus.RESOLVED
    if narrative.stance_counts.get("deny", 0) > 0:
        return NarrativeStatus.VERIFYING
    if narrative.velocity >= _PEAK_VELOCITY_PER_HOUR:
        return NarrativeStatus.PEAK_HYPE
    if narrative.mention_count >= 3:
        return NarrativeStatus.SPREADING
    return NarrativeStatus.EMERGING


def _add_item_to_narrative(narrative: Narrative, item: NormalizedItem, now: datetime) -> None:
    """Attach an item, updating propagation metrics."""

    narrative.items.append(item)
    narrative.mention_count += 1
    published = item.published_at or now
    if published < narrative.first_seen:
        narrative.first_seen = published
    narrative.last_seen = now
    narrative.updated_at = now
    sources = {i.source for i in narrative.items}
    platforms = {i.platform for i in narrative.items}
    narrative.source_count = len(sources)
    narrative.platforms = sorted(platforms)


# ==============================================================================
# ENGINE
# ==============================================================================


def _item_from_row(row: dict) -> NormalizedItem:
    """Reconstruct a NormalizedItem from a storage row dict."""

    return NormalizedItem(
        id=row["id"],
        source=row["source"],
        source_key=row["source_key"],
        url=row["url"],
        title=row["title"],
        content=row["content"] or "",
        author=row["author"],
        published_at=_parse_dt(row["published_at"]),
        fetched_at=_parse_dt(row["fetched_at"]) or datetime.now(UTC),
        language=row["language"] or "en",
        platform=row["platform"] or "web",
        title_fingerprint=row["title_fp"],
        content_fingerprint=row["content_fp"],
        entities=[
            {"type": e["entity_type"], "symbol": e["symbol"], "name": e["name"], "context": None}
            for e in row["entities"]
        ],
    )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed


def _narrative_from_row(row: dict) -> Narrative:
    """Reconstruct a Narrative from a storage row dict."""

    return Narrative(
        id=row["id"],
        claim_text=row["claim_text"],
        entities=row["entities"],
        status=row["status"],
        first_seen=_parse_dt(row["first_seen"]) or datetime.now(UTC),
        last_seen=_parse_dt(row["last_seen"]) or datetime.now(UTC),
        mention_count=row["mention_count"],
        source_count=row["source_count"],
        platforms=row["platforms"],
        stance_counts=row["stance_counts"],
        fomo_score=row["fomo_score"],
        velocity=row["velocity"],
        epistemic_status=row.get("epistemic_status", EpistemicStatus.UNCONFIRMED),
        confidence=row.get("confidence", 0.0),
        coordination_score=row.get("coordination_score", 0.0),
        manipulation_flags=row.get("manipulation_flags", {}),
        evidence=row.get("evidence", {}),
        created_at=_parse_dt(row["created_at"]) or datetime.now(UTC),
        updated_at=_parse_dt(row["updated_at"]) or datetime.now(UTC),
        items=[_item_from_row(item) for item in row["items"]],
    )


def _narrative_to_dict(narrative: Narrative) -> dict:
    """Serialize a Narrative to a storage-compatible dict."""

    return {
        "claim_text": narrative.claim_text,
        "status": narrative.status,
        "first_seen": narrative.first_seen.isoformat(),
        "last_seen": narrative.last_seen.isoformat(),
        "mention_count": narrative.mention_count,
        "source_count": narrative.source_count,
        "platforms": narrative.platforms,
        "stance_counts": narrative.stance_counts,
        "fomo_score": narrative.fomo_score,
        "velocity": narrative.velocity,
        "entities": narrative.entities,
        "epistemic_status": narrative.epistemic_status,
        "confidence": narrative.confidence,
        "coordination_score": narrative.coordination_score,
        "manipulation_flags": narrative.manipulation_flags,
        "evidence": narrative.evidence,
        "created_at": narrative.created_at.isoformat(),
        "updated_at": narrative.updated_at.isoformat(),
    }


class NarrativeEngine:
    """Clusters new items into narratives and keeps them fresh."""

    def __init__(
        self,
        window_hours: int = 24,
        min_mentions: int = 3,
        match_threshold: float = 0.22,
        use_semantic: bool = True,
        half_life_hours: float = CLUSTER_HALF_LIFE_HOURS,
    ) -> None:
        self.window_hours = window_hours
        self.min_mentions = min_mentions
        self.match_threshold = match_threshold
        self.use_semantic = use_semantic
        self.half_life_hours = half_life_hours

    async def update(self, storage, items: list[NormalizedItem], now: datetime | None = None) -> list[Narrative]:
        """Run one narrative update cycle. Returns all active narratives."""

        now = now or datetime.now(UTC)
        rows = await storage.load_active_narratives(
            (now - timedelta(hours=self.window_hours)).isoformat()
        )
        narratives = [_narrative_from_row(row) for row in rows]

        for item in items:
            match = best_match(
                item,
                narratives,
                self.match_threshold,
                weights=NARRATIVE_WEIGHTS,
                use_semantic=self.use_semantic,
                now=now,
                half_life_hours=self.half_life_hours,
            )
            if match is not None:
                stance = classify_stance(f"{item.title} {item.content}", use_ml=True)
                match.stance_counts[stance] += 1
                _add_item_to_narrative(match, item, now)
                await storage.add_narrative_item(match.id, item, stance)
            else:
                narrative = self._create_narrative(item, now)
                stance = classify_stance(f"{item.title} {item.content}", use_ml=True)
                narrative.stance_counts[stance] = 1
                narrative_id = await storage.insert_narrative(_narrative_to_dict(narrative))
                narrative.id = narrative_id
                await storage.add_narrative_item(narrative_id, item, stance)
                narratives.append(narrative)

        # Post-process: merge very similar narratives
        narratives = self._merge_similar_narratives(narratives, now)

        for narrative in narratives:
            compute_fomo(narrative, now)
            narrative.status = compute_status(narrative, now)
            narrative.epistemic_status, narrative.confidence, narrative.evidence = verify_narrative(narrative, use_ml=True)
            narrative.coordination_score, narrative.manipulation_flags = coordination_score(narrative)
            if narrative.id is not None:
                await storage.update_narrative(narrative.id, _narrative_to_dict(narrative))
        return narratives

    def _merge_similar_narratives(self, narratives: list[Narrative], now: datetime) -> list[Narrative]:
        """Merge narratives that are extremely similar (e.g., same story from different sources)."""
        from .cluster import merge_similar_narratives
        return merge_similar_narratives(
            narratives,
            threshold=0.85,
            weights=NARRATIVE_WEIGHTS,
            use_semantic=self.use_semantic,
            now=now,
        )

    def _create_narrative(self, item: NormalizedItem, now: datetime) -> Narrative:
        claim = extract_claim(item.title, item.content, [e.symbol for e in item.entities])
        published = item.published_at or now
        first_seen = published if published <= now else now
        return Narrative(
            claim_text=claim.claim_text,
            entities=claim.entities,
            first_seen=first_seen,
            last_seen=first_seen,
            created_at=now,
            updated_at=now,
            items=[item],
        )


__all__ = ["Narrative", "NarrativeEngine", "compute_fomo", "compute_status"]
