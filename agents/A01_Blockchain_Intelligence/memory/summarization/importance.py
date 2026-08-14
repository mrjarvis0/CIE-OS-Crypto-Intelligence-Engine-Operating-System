"""
Importance Scorer

Scores memory entries by importance to guide retention, summarization,
and eviction decisions.

Research foundations
--------------------
* Recency decay — exponential forgetting curve. Newer entries outrank
  older ones, and value decays with age (agent-memory-compressor;
  Mem0 decay mechanisms).
* Type weight — decisions and facts outrank routine turns and tool noise
  (agent-memory-compressor; Mem0 "memory formation" selective storage).
* Keyword boost — entries matching goal-related keywords are promoted
  (agent-memory-compressor).
* Frequency — repeatedly accessed entries carry higher value (Mem0
  conflict/decay literature).
* Confidence — higher-confidence records are retained over speculative
  ones (principles IP-04; NFR-AI02).

Scores are normalized to [0, 1] and combined from multiple weighted
signals. The scorer is deterministic-first: it needs no model and is
safe to run on every write path.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Sequence

# ============================================================
# Public Constants
# ============================================================

DEFAULT_HALF_LIFE_HOURS = 24.0 * 7.0

DEFAULT_BASE_SCORE = 0.30

MAX_SCORE = 1.0

TOKEN_SPLIT_RE = re.compile(r"\s+")


def _contains_word(text: str, tokens: frozenset[str]) -> bool:
    """Return True when any token appears as a whole word in ``text``."""
    return any(re.search(rf"\b{re.escape(token)}\b", text) for token in tokens)

# ============================================================
# Signal Vocabulary
# ============================================================

URGENT_TOKENS = frozenset(
    {"urgent", "critical", "important", "must", "immediately", "asap"}
)

DECISION_TOKENS = frozenset(
    {"decided", "decision", "final", "concluded", "resolved", "agreed"}
)

FACT_TOKENS = frozenset(
    {"is", "are", "was", "were", "fact", "known", "confirmed"}
)

PREFERENCE_TOKENS = frozenset(
    {"prefer", "preferred", "like", "dislike", "favorite", "want"}
)

MONETARY_TOKENS = frozenset(
    {"money", "funds", "usd", "btc", "eth", "invest", "loss",
     "gain", "stolen", "transfer", "whale", "reserve"}
)

TYPE_WEIGHT_DEFAULTS: dict[str, float] = {
    "decision": 0.95,
    "fact": 0.90,
    "preference": 0.85,
    "task": 0.80,
    "event": 0.75,
    "entity": 0.70,
    "topic": 0.60,
    "message": 0.40,
    "noise": 0.05,
}


@dataclass(slots=True)
class ImportanceScorerConfig:
    """Tunable weights for the multi-signal importance scorer."""

    half_life_hours: float = DEFAULT_HALF_LIFE_HOURS
    base_score: float = DEFAULT_BASE_SCORE
    recency_weight: float = 0.25
    type_weight: float = 0.35
    keyword_weight: float = 0.20
    frequency_weight: float = 0.10
    confidence_weight: float = 0.10
    enable_decay: bool = True

    def __post_init__(self) -> None:
        if self.half_life_hours <= 0:
            raise ValueError("half_life_hours must be positive")
        if not 0.0 <= self.base_score <= 1.0:
            raise ValueError("base_score must be in [0, 1]")
        weights = (
            self.recency_weight
            + self.type_weight
            + self.keyword_weight
            + self.frequency_weight
            + self.confidence_weight
        )
        if weights <= 0:
            raise ValueError("signal weights must sum to a positive value")


@dataclass(slots=True)
class SignalBundle:
    """Individual signal values for one entry."""

    recency: float
    type_weight: float
    keyword: float
    frequency: float
    confidence: float

    def to_dict(self) -> dict[str, float]:
        return {
            "recency": round(self.recency, 4),
            "type": round(self.type_weight, 4),
            "keyword": round(self.keyword, 4),
            "frequency": round(self.frequency, 4),
            "confidence": round(self.confidence, 4),
        }


@dataclass(slots=True)
class ScoredEntry:
    """An entry together with its importance score and signals."""

    entry: Any
    score: float
    signals: SignalBundle


class MemoryImportanceLevel(str, Enum):
    """Human-readable importance buckets."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NOISE = "noise"


class ImportanceScorer:
    """
    Computes a normalized importance score for memory content.

    Works on two input shapes:

    * ``MemoryEntry`` objects (from ``memory.base.memory``) — full signal
      computation including metadata confidence and timestamps.
    * plain text / dicts — fast text-only scoring for hot write paths.

    The scorer is deterministic and model-free. It is used by the
    compressor and the memory filter to guide retention decisions.
    """

    def __init__(
        self,
        config: ImportanceScorerConfig | None = None,
    ) -> None:
        self._config = config or ImportanceScorerConfig()
        self._access_counts: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Configuration & Properties
    # ------------------------------------------------------------------

    @property
    def config(self) -> ImportanceScorerConfig:
        return self._config

    def record_access(self, key: str) -> None:
        """Increment the access counter for a memory key."""
        count = self._access_counts.get(key, 0)
        self._access_counts[key] = count + 1

    def access_count(self, key: str) -> int:
        """Return recorded access count for a key."""
        return self._access_counts.get(key, 0)

    # ------------------------------------------------------------------
    # Signal Computation
    # ------------------------------------------------------------------

    def _recency_signal(
        self,
        age_seconds: float | None,
    ) -> float:
        if age_seconds is None or not self._config.enable_decay:
            return 1.0
        hours = max(0.0, age_seconds / 3600.0)
        half_life = self._config.half_life_hours
        return float(math.exp(-(math.log(2.0) * hours) / half_life))

    def _keyword_signal(self, text: str) -> float:
        lower = text.lower()
        score = 0.0
        if _contains_word(lower, URGENT_TOKENS):
            score += 0.5
        if _contains_word(lower, DECISION_TOKENS):
            score += 0.4
        if _contains_word(lower, MONETARY_TOKENS):
            score += 0.4
        if _contains_word(lower, PREFERENCE_TOKENS):
            score += 0.3
        if _contains_word(lower, FACT_TOKENS):
            score += 0.2
        return min(1.0, score)

    def _type_weight(self, tags: Sequence[str] | None) -> float:
        if not tags:
            return TYPE_WEIGHT_DEFAULTS["message"]
        weight = TYPE_WEIGHT_DEFAULTS["message"]
        for tag in tags:
            candidate = TYPE_WEIGHT_DEFAULTS.get(tag)
            if candidate is not None and candidate > weight:
                weight = candidate
        return weight

    def _frequency_signal(self, key: str) -> float:
        count = self._access_counts.get(key, 0)
        if count <= 0:
            return 0.0
        return min(1.0, 0.25 + 0.15 * count)

    @staticmethod
    def _confidence_value(confidence: Any) -> float:
        try:
            value = float(confidence)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, value))

    def _text_from(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="replace")
        if isinstance(content, dict):
            return " ".join(f"{key}: {value}" for key, value in content.items())
        return str(content)

    def _entry_shapes(
        self,
        entry: Any,
    ) -> tuple[Any, Any, Any, Any, Any]:
        """
        Normalize arbitrary input into (key, text, tags, confidence,
        age_seconds).

        Recognizes MemoryEntry-like objects via duck typing so the module
        works with memory.base.memory without a hard import.
        """
        metadata = getattr(entry, "metadata", None)
        key = getattr(entry, "key", None) or ""
        content = getattr(entry, "value", entry)
        text = self._text_from(content)
        tags = None
        confidence = None
        age_seconds = None

        if metadata is not None:
            tags = getattr(metadata, "tags", None)
            confidence = getattr(metadata, "confidence", None)
            created_at = getattr(metadata, "created_at", None)
            if isinstance(created_at, datetime):
                now = datetime.now(timezone.utc)
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                age_seconds = max(0.0, (now - created_at).total_seconds())

        return key, text, tags, confidence, age_seconds

    # ------------------------------------------------------------------
    # Public Scoring API
    # ------------------------------------------------------------------

    def score(self, entry: Any) -> ScoredEntry:
        """
        Return a normalized importance score in [0, 1].

        Accepts MemoryEntry objects or raw text / dicts.
        """
        key, text, tags, confidence, age_seconds = self._entry_shapes(entry)

        recency = self._recency_signal(age_seconds)
        type_weight = self._type_weight(tags)
        keyword = self._keyword_signal(text)
        frequency = self._frequency_signal(key)
        conf_value = self._confidence_value(confidence)

        signals = SignalBundle(
            recency=recency,
            type_weight=type_weight,
            keyword=keyword,
            frequency=frequency,
            confidence=conf_value,
        )

        cfg = self._config
        weighted = (
            cfg.recency_weight * recency
            + cfg.type_weight * type_weight
            + cfg.keyword_weight * keyword
            + cfg.frequency_weight * frequency
            + cfg.confidence_weight * conf_value
        )
        total_weight = (
            cfg.recency_weight
            + cfg.type_weight
            + cfg.keyword_weight
            + cfg.frequency_weight
            + cfg.confidence_weight
        )

        score = (weighted / total_weight) if total_weight else 0.0
        score = cfg.base_score + (1.0 - cfg.base_score) * score
        score = max(0.0, min(MAX_SCORE, score))

        return ScoredEntry(
            entry=entry,
            score=round(score, 4),
            signals=signals,
        )

    def score_text(self, text: str) -> float:
        """Fast text-only scoring; returns a score in [0, 1]."""
        return self.score(text).score

    def level(self, score: float) -> MemoryImportanceLevel:
        """Bucket a score into a human-readable level."""
        if score >= 0.75:
            return MemoryImportanceLevel.HIGH
        if score >= 0.50:
            return MemoryImportanceLevel.MEDIUM
        if score >= 0.25:
            return MemoryImportanceLevel.LOW
        return MemoryImportanceLevel.NOISE

    def rank(
        self,
        entries: Iterable[Any],
    ) -> list[ScoredEntry]:
        """Score every entry and sort by descending importance."""
        scored = [self.score(entry) for entry in entries]
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored

    def above_threshold(
        self,
        entry: Any,
        threshold: float = 0.5,
    ) -> bool:
        """Return True when an entry clears the retention threshold."""
        return self.score(entry).score >= threshold
