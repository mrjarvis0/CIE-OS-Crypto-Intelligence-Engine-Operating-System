"""
CIE-OS
A02 News Intelligence Agent

Module:
    intelligence.cluster

Purpose:
    Narrative clustering — group similar items into one story (Phase 2+).

    Similarity blends title-token Jaccard with entity overlap and semantic embeddings:
        score = w_title * title_jaccard + w_entity * entity_overlap + w_semantic * semantic_sim
    Temporal decay: older items have reduced influence on clustering.
    An item joins the best matching narrative when score >= threshold.
"""

from __future__ import annotations

import math
import re
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.A02_News_Intelligence.core.models import NormalizedItem

# ==============================================================================
# TOKENIZATION
# ==============================================================================

_STOPWORDS = frozenset(
    """
    a an the and or but if then else for of on in at by to from with without
    is are was were be been being have has had do does did will would shall
    should can could may might must not no nor as at about into over after
    under again further once here there when where why how all any both each
    few more most other some such only own same so than too very just also
    its it's their they this that these those what which who whom
    """.split()
)
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


def tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric tokens minus stopwords."""

    return {t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity of two token sets (0..1)."""

    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def entity_overlap_ratio(a: set[str], b: set[str]) -> float:
    """Shared entities over union (0..1)."""

    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ==============================================================================
# SEMANTIC EMBEDDINGS (lightweight, optional)
# ==============================================================================

_EMBEDDING_MODEL = None
_EMBEDDING_DIM = 384  # MiniLM default


def _get_embedding_model():
    """Lazy load sentence transformer model."""
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            # Use a small, fast model
            _EMBEDDING_MODEL = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        except Exception:
            _EMBEDDING_MODEL = False
    return _EMBEDDING_MODEL


def semantic_similarity(text_a: str, text_b: str) -> float:
    """Compute semantic similarity using sentence embeddings (0..1)."""
    model = _get_embedding_model()
    if model is False or not model:
        return 0.0
    try:
        emb_a = model.encode(text_a, normalize_embeddings=True)
        emb_b = model.encode(text_b, normalize_embeddings=True)
        # Cosine similarity
        sim = float(emb_a @ emb_b)
        return max(0.0, min(1.0, sim))
    except Exception:
        return 0.0


def semantic_similarity_batch(texts: list[str]) -> list[list[float]]:
    """Compute pairwise semantic similarity matrix."""
    model = _get_embedding_model()
    if model is False or not model:
        return [[0.0] * len(texts) for _ in texts]
    try:
        embeddings = model.encode(texts, normalize_embeddings=True)
        import numpy as np
        sim_matrix = embeddings @ embeddings.T
        return [[max(0.0, min(1.0, float(sim_matrix[i, j]))) for j in range(len(texts))] for i in range(len(texts))]
    except Exception:
        return [[0.0] * len(texts) for _ in texts]


# ==============================================================================
# TEMPORAL DECAY
# ==============================================================================

def temporal_decay(item_time: datetime, now: datetime, half_life_hours: float = 48.0) -> float:
    """
    Exponential temporal decay factor (0..1).
    
    Items older than half_life get exponentially lower weight.
    half_life_hours=48 means 2-day half-life.
    """
    if item_time is None:
        return 1.0
    delta_hours = (now - item_time).total_seconds() / 3600.0
    if delta_hours <= 0:
        return 1.0
    return math.exp(-math.log(2) * delta_hours / half_life_hours)


# ==============================================================================
# BLENDED SIMILARITY
# ==============================================================================

# Default weights (sum to 1.0)
DEFAULT_WEIGHTS = {
    "title": 0.4,
    "entity": 0.3,
    "semantic": 0.3,
}

# Minimum threshold for clustering
DEFAULT_THRESHOLD = 0.22


def similarity(
    item_a: "NormalizedItem",
    item_b: "NormalizedItem",
    weights: dict | None = None,
    use_semantic: bool = True,
    now: datetime | None = None,
    half_life_hours: float = 48.0,
) -> float:
    """
    Blended similarity between two items (0..1).

    Components:
    - Title Jaccard (token overlap)
    - Entity overlap ratio
    - Semantic similarity (optional, via embeddings)
    - Temporal decay applied to final score

    Shared entities boost the score; without any shared entity the
    title-only score is halved so pattern-like headlines (e.g.
    "X Q2 Earnings Call Highlights") do not merge unrelated companies.
    """
    w = weights or DEFAULT_WEIGHTS
    
    # Title similarity
    title_score = jaccard(tokenize(item_a.title), tokenize(item_b.title))
    
    # Entity similarity
    entities_a = {e.symbol for e in item_a.entities}
    entities_b = {e.symbol for e in item_b.entities}
    entity_score = entity_overlap_ratio(entities_a, entities_b)
    
    # Semantic similarity (optional)
    semantic_score = 0.0
    if use_semantic and w.get("semantic", 0) > 0:
        semantic_score = semantic_similarity(item_a.title + " " + (item_a.content or ""),
                                             item_b.title + " " + (item_b.content or ""))
    
    # Blended score
    if entity_score > 0.0:
        blended = (w.get("title", 0.4) * title_score +
                   w.get("entity", 0.3) * entity_score +
                   w.get("semantic", 0.3) * semantic_score)
    else:
        # Penalty for no shared entities: reduce title weight
        blended = 0.5 * (w.get("title", 0.4) * title_score +
                         w.get("semantic", 0.3) * semantic_score)
    
    # Temporal decay
    if now is not None:
        t_a = item_a.published_at or now
        t_b = item_b.published_at or now
        # Use the older item's time for decay
        older_time = min(t_a, t_b)
        decay = temporal_decay(older_time, now, half_life_hours)
        blended *= decay
    
    return max(0.0, min(1.0, blended))


def best_match(
    item: "NormalizedItem",
    narratives: list,
    threshold: float = DEFAULT_THRESHOLD,
    weights: dict | None = None,
    use_semantic: bool = True,
    now: datetime | None = None,
    half_life_hours: float = 48.0,
) -> object | None:
    """
    Return the best-matching narrative for an item, or None.

    `narratives` entries must expose `.items` (list of NormalizedItem-like)
    and `.entities` (set of symbols).
    """
    if now is None:
        now = datetime.now(UTC)
    
    best_score = 0.0
    best = None
    for narrative in narratives:
        if not narrative.items:
            continue
        # Score against most similar item in narrative
        scores = [similarity(item, other, weights, use_semantic, now, half_life_hours) 
                  for other in narrative.items]
        score = max(scores)
        if score > best_score:
            best_score = score
            best = narrative
    if best is not None and best_score >= threshold:
        return best
    return None


def cluster_items(
    items: list["NormalizedItem"],
    threshold: float = DEFAULT_THRESHOLD,
    weights: dict | None = None,
    use_semantic: bool = True,
    half_life_hours: float = 48.0,
) -> list[list["NormalizedItem"]]:
    """
    Cluster items into narratives using online clustering.
    
    Returns list of clusters (each cluster is a list of items).
    """
    if not items:
        return []
    
    now = datetime.now(UTC)
    clusters: list[list["NormalizedItem"]] = []
    
    # Sort by time (newest first)
    sorted_items = sorted(items, key=lambda x: x.published_at or now, reverse=True)
    
    for item in sorted_items:
        matched = False
        for cluster in clusters:
            # Check against cluster centroid (first item)
            score = similarity(item, cluster[0], weights, use_semantic, now, half_life_hours)
            if score >= threshold:
                cluster.append(item)
                matched = True
                break
        if not matched:
            clusters.append([item])
    
    return clusters


def merge_similar_narratives(
    narratives: list,
    threshold: float = 0.7,
    weights: dict | None = None,
    use_semantic: bool = True,
    now: datetime | None = None,
) -> list:
    """
    Merge narratives that are very similar to each other.
    Useful for post-processing to avoid over-clustering.
    """
    if now is None:
        now = datetime.now(UTC)
    
    merged = []
    used = set()
    
    for i, n1 in enumerate(narratives):
        if i in used:
            continue
        group = [n1]
        used.add(i)
        
        for j, n2 in enumerate(narratives):
            if j in used or i == j:
                continue
            # Compare first items
            if n1.items and n2.items:
                score = similarity(n1.items[0], n2.items[0], weights, use_semantic, now)
                if score >= threshold:
                    group.append(n2)
                    used.add(j)
        
        if len(group) > 1:
            # Merge into first narrative
            merged_narrative = group[0]
            for other in group[1:]:
                merged_narrative.items.extend(other.items)
                merged_narrative.entities.update(other.entities)
            merged.append(merged_narrative)
        else:
            merged.append(n1)
    
    return merged


__all__ = [
    "tokenize",
    "jaccard",
    "entity_overlap_ratio",
    "semantic_similarity",
    "semantic_similarity_batch",
    "temporal_decay",
    "similarity",
    "best_match",
    "cluster_items",
    "merge_similar_narratives",
    "DEFAULT_WEIGHTS",
    "DEFAULT_THRESHOLD",
]