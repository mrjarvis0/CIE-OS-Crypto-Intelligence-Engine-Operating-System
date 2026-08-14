"""
CIE-OS
A02 News Intelligence Agent

Module:
    intelligence.manipulation

Purpose:
    Coordination / manipulation detection (Phase 3).

    coordination_score (0-100) is SEPARATE from truth and FOMO.
    Signals: identical text (copy-paste), timing bursts,
    author concentration, platform concentration.
"""

from __future__ import annotations

from collections import Counter, defaultdict

_BURST_WINDOW_MINUTES = 30
_BURST_MIN_ITEMS = 3


def coordination_score(narrative) -> tuple[float, dict]:
    """Return (coordination_score 0-100, flags dict) for a narrative."""

    items = narrative.items
    count = len(items)
    flags: dict = {}

    if count < 2:
        flags.update({"identical_text_ratio": 0.0, "timing_burst": False,
                      "author_concentration": 1.0, "platform_concentration": 1.0})
        return (0.0, flags)

    # identical text: items sharing a content fingerprint
    groups = defaultdict(list)
    for item in items:
        key = item.content_fingerprint or f"title:{item.title_fingerprint}"
        groups[key].append(item)
    identical_ratio = sum(len(g) - 1 for g in groups.values()) / max(1, count)
    flags["identical_text_ratio"] = round(identical_ratio, 3)

    # timing burst: many items within a short window
    timestamps = sorted(
        (item.published_at or item.fetched_at) for item in items
    )
    burst = False
    if len(timestamps) >= _BURST_MIN_ITEMS:
        span = (timestamps[-1] - timestamps[0]).total_seconds() / 60.0
        burst = span <= _BURST_WINDOW_MINUTES and count >= _BURST_MIN_ITEMS
    flags["timing_burst"] = burst

    # author concentration: few distinct authors across many items
    authors = [a for a in (item.author for item in items) if a]
    if authors:
        top_author_share = Counter(authors).most_common(1)[0][1] / len(authors)
    else:
        top_author_share = 1.0  # no authors at all = opaque
    flags["author_concentration"] = round(top_author_share, 3)

    # platform concentration
    platforms = Counter(item.platform for item in items)
    top_platform_share = platforms.most_common(1)[0][1] / count
    flags["platform_concentration"] = round(top_platform_share, 3)

    score = (
        0.35 * identical_ratio
        + 0.25 * (1.0 if burst else 0.0)
        + 0.2 * top_author_share
        + 0.2 * top_platform_share
    )
    return (round(100 * min(1.0, score), 1), flags)


__all__ = ["coordination_score"]
