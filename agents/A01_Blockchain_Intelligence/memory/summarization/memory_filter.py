"""
Memory Filter

Filters low-value memories before summarization or eviction.

Research foundations
--------------------
* Selective storage over bulk compression — memory formation wins over
  compressing everything; identify the facts, preferences and decisions
  worth keeping and drop the rest (Mem0: "memory formation beats
  summarization", 80-90% token savings with 26% better quality).
* Semantic deduplication — discard records that are semantically similar
  to kept records and add no new information (AgeMem learned policy:
  "selectively discarding records that are semantically similar to
  existing ones but add no new information").
* Priority preservation — protected and high-importance records always
  survive, even below the default threshold
  (agent-memory-compressor protected entries).
* Expiry — records past their ``expires_at`` are dropped before any
  scoring (memory.base MemoryMetadata).

Design principles
-----------------
* Deterministic-first: similarity and importance are computed with
  local, dependency-free logic.
* Non-destructive: the filter never mutates entries; it returns a
  FilterResult with kept and dropped records for the caller to act on.
* Explainable: every drop records a reason
  (low_importance / duplicate / expired).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Sequence

from .importance import ImportanceScorer

# ============================================================
# Public Constants
# ============================================================

DEFAULT_IMPORTANCE_THRESHOLD = 0.50

DEFAULT_DUPLICATE_THRESHOLD = 0.75

DEFAULT_PROTECTED_TAGS = frozenset({"decision", "fact", "preference"})

TOKEN_SPLIT_RE = re.compile(r"\s+")


def _normalize_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    if isinstance(content, dict):
        return " ".join(f"{key}: {value}" for key, value in content.items())
    return str(content)


def token_overlap_similarity(left: str, right: str) -> float:
    """
    Jaccard similarity over token sets, in [0, 1].

    Used for deterministic semantic-duplicate detection. A value >= 0.75
    generally indicates the second record adds little new information.
    """
    left_tokens = set(TOKEN_SPLIT_RE.split(_normalize_text(left).lower()))
    right_tokens = set(TOKEN_SPLIT_RE.split(_normalize_text(right).lower()))
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return intersection / union if union else 0.0


# ============================================================
# Filter Results
# ============================================================


class DropReason(str, Enum):
    """Why a memory entry was not retained."""

    LOW_IMPORTANCE = "low_importance"
    DUPLICATE = "duplicate"
    EXPIRED = "expired"


class RetainReason(str, Enum):
    """Why a memory entry was retained."""

    ABOVE_THRESHOLD = "above_threshold"
    PROTECTED = "protected"
    UNIQUE = "unique"


@dataclass(slots=True)
class FilterDecision:
    """Outcome of evaluating one memory entry."""

    entry: Any
    score: float
    reason: RetainReason | DropReason

    @property
    def retained(self) -> bool:
        return isinstance(self.reason, RetainReason)


@dataclass(slots=True)
class FilterResult:
    """Outcome of running the memory filter over a batch."""

    kept: list[FilterDecision] = field(default_factory=list)
    dropped: list[FilterDecision] = field(default_factory=list)
    total: int = 0
    dropped_count: int = 0

    @property
    def kept_count(self) -> int:
        return len(self.kept)

    def keep(self, decision: FilterDecision) -> None:
        self.kept.append(decision)

    def drop(self, decision: FilterDecision) -> None:
        self.dropped.append(decision)
        self.dropped_count += 1

    def kept_entries(self) -> list[Any]:
        """Return the retained entry objects in input order."""
        return [decision.entry for decision in self.kept]

    def dropped_entries(self) -> list[Any]:
        """Return the dropped entry objects."""
        return [decision.entry for decision in self.dropped]

    def reasons(self) -> dict[str, int]:
        """Count drops by reason for observability."""
        counts: dict[str, int] = {}
        for decision in self.dropped:
            counts[decision.reason.value] = (
                counts.get(decision.reason.value, 0) + 1
            )
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "kept": self.kept_count,
            "dropped": self.dropped_count,
            "reasons": self.reasons(),
        }


# ============================================================
# Memory Filter
# ============================================================


@dataclass(slots=True)
class MemoryFilterConfig:
    """Tunable retention policy."""

    importance_threshold: float = DEFAULT_IMPORTANCE_THRESHOLD
    duplicate_threshold: float = DEFAULT_DUPLICATE_THRESHOLD
    protected_tags: frozenset[str] = DEFAULT_PROTECTED_TAGS
    drop_expired: bool = True
    deduplicate: bool = True

    def __post_init__(self) -> None:
        if not 0.0 <= self.importance_threshold <= 1.0:
            raise ValueError("importance_threshold must be in [0, 1]")
        if not 0.0 <= self.duplicate_threshold <= 1.0:
            raise ValueError("duplicate_threshold must be in [0, 1]")


class MemoryFilter:
    """
    Filters memory entries by value and relevance.

    Pipeline for a batch of entries:
        1. Drop expired entries (when enabled).
        2. Score every entry for importance.
        3. Retain protected / above-threshold entries.
        4. Deduplicate semantically similar records, keeping the
           higher-scoring representative.

    Responsibilities:
        * Drop low-value entries
        * Apply importance and priority thresholds
        * Preserve high-importance memories
        * Remove semantic duplicates without information loss
    """

    def __init__(
        self,
        config: MemoryFilterConfig | None = None,
        scorer: ImportanceScorer | None = None,
    ) -> None:
        self._config = config or MemoryFilterConfig()
        self._scorer = scorer or ImportanceScorer()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def config(self) -> MemoryFilterConfig:
        return self._config

    @property
    def scorer(self) -> ImportanceScorer:
        return self._scorer

    # ------------------------------------------------------------------
    # Entry Introspection
    # ------------------------------------------------------------------

    @staticmethod
    def _entry_parts(entry: Any) -> tuple[str, str, list[str], Any]:
        metadata = getattr(entry, "metadata", None)
        content = getattr(entry, "value", entry)
        text = _normalize_text(content)
        tags: list[str] = []
        expires_at: Any = None

        if metadata is not None:
            tags = list(getattr(metadata, "tags", None) or [])
            expires_at = getattr(metadata, "expires_at", None)

        return text, _normalize_text(content), tags, expires_at

    @staticmethod
    def _is_expired(expires_at: Any) -> bool:
        if not isinstance(expires_at, datetime):
            return False
        now = datetime.now(timezone.utc)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= now

    def _is_protected(self, tags: Sequence[str]) -> bool:
        return any(tag in self._config.protected_tags for tag in tags)

    # ------------------------------------------------------------------
    # Batch Filtering
    # ------------------------------------------------------------------

    def filter(
        self,
        entries: Iterable[Any],
    ) -> FilterResult:
        """
        Filter a batch of memory entries.

        Accepts MemoryEntry objects or raw content. Non-destructive: the
        input entries are returned unchanged in the result.
        """
        result = FilterResult()
        entry_list = list(entries)
        result.total = len(entry_list)

        scored: list[tuple[float, Any]] = []
        for entry in entry_list:
            _, text, tags, expires_at = self._entry_parts(entry)

            if self._config.drop_expired and self._is_expired(expires_at):
                result.drop(
                    FilterDecision(
                        entry=entry,
                        score=0.0,
                        reason=DropReason.EXPIRED,
                    )
                )
                continue

            decision = self._scorer.score(entry)
            score = decision.score
            scored.append((score, entry, text, tags))

        # Order by descending importance so dedup keeps the best rep.
        scored.sort(key=lambda item: item[0], reverse=True)

        kept_reps: list[tuple[float, str]] = []
        for score, entry, text, tags in scored:
            protected = self._is_protected(tags)
            above = score >= self._config.importance_threshold

            if not (protected or above):
                result.drop(
                    FilterDecision(
                        entry=entry,
                        score=score,
                        reason=DropReason.LOW_IMPORTANCE,
                    )
                )
                continue

            if self._config.deduplicate and not protected:
                duplicate = False
                for kept_score, kept_text in kept_reps:
                    if token_overlap_similarity(text, kept_text) >= (
                        self._config.duplicate_threshold
                    ):
                        duplicate = True
                        break
                if duplicate:
                    result.drop(
                        FilterDecision(
                            entry=entry,
                            score=score,
                            reason=DropReason.DUPLICATE,
                        )
                    )
                    continue

            kept_reps.append((score, text))
            result.keep(
                FilterDecision(
                    entry=entry,
                    score=score,
                    reason=(
                        RetainReason.PROTECTED
                        if protected
                        else RetainReason.ABOVE_THRESHOLD
                    ),
                )
            )

        return result

    # ------------------------------------------------------------------
    # Single-Entry API
    # ------------------------------------------------------------------

    def should_keep(self, entry: Any) -> bool:
        """Return True when a single entry clears the retention policy."""
        _, _, tags, expires_at = self._entry_parts(entry)
        if self._config.drop_expired and self._is_expired(expires_at):
            return False
        if self._is_protected(tags):
            return True
        return self._scorer.above_threshold(
            entry,
            self._config.importance_threshold,
        )

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def summarize(
        self,
        result: FilterResult,
    ) -> dict[str, Any]:
        """Return a compact summary of a filter run."""
        return result.to_dict()
