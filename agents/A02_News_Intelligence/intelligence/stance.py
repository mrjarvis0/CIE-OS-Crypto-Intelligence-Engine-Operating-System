"""
CIE-OS
A02 News Intelligence Agent

Module:
    intelligence.stance

Purpose:
    Stance classification of an item toward its claim (Phase 2+6):
    - Rule-based (default)
    - ML-enhanced (optional, Phase 6)

    Stances: support | deny | neutral | question
    Priority: deny > support > question > neutral
"""

from __future__ import annotations

import re

try:
    from agents.A02_News_Intelligence.models.ml_models import classify_stance_ml
    ML_AVAILABLE = True
except Exception:
    ML_AVAILABLE = False

# ==============================================================================
# MARKERS (longest first for safe matching)
# ==============================================================================

_DENY_MARKERS = (
    "not true",
    "no truth",
    "denies",
    "denied",
    "refutes",
    "refuted",
    "debunked",
    "debunks",
    "untrue",
    "fabricated",
    "fake news",
    "disproven",
    "no evidence",
    "rejects",
    "rejected",
    "dismisses",
    "dismissed",
    "baseless",
    "misleading",
    "false rumor",
)

_SUPPORT_MARKERS = (
    "confirms",
    "confirmed",
    "announces",
    "announced",
    "officially",
    "approved",
    "approves",
    "authorized",
    "authorizes",
    "signs off",
    "finalized",
)

_QUESTION_MARKERS = (
    "reportedly",
    "allegedly",
    "unconfirmed",
    "speculation",
    "rumor",
    "rumour",
    "rumors",
    "rumours",
    "sources say",
    "claims to",
    "whether",
    "might",
    "maybe",
    "possible",
    "possibly",
    "expected to",
    "set to",
    "may be",
    "leaked",
    "insider says",
    "investigating",
    "looking into",
    "under review",
    "reviewing",
    "examining",
    "predicts",
    "forecast",
    "will never",
    "expects",
)


def _contains(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def classify_stance(text: str, use_ml: bool = True) -> str:
    """Classify item stance toward the narrative claim.

    Tries ML first (if available and use_ml=True), falls back to rules.
    """

    if use_ml and ML_AVAILABLE:
        try:
            ml_result = classify_stance_ml(text)
            if ml_result in ("support", "deny", "neutral", "question"):
                return ml_result
        except Exception:
            pass
    # Rule fallback
    if _contains(text, _DENY_MARKERS):
        return "deny"
    if _contains(text, _SUPPORT_MARKERS):
        return "support"
    if _contains(text, _QUESTION_MARKERS):
        return "question"
    return "neutral"


__all__ = ["classify_stance"]
