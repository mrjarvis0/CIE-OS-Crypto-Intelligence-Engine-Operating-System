"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    schemas.stance

Purpose:
    The vocabulary for what a conclusion asserts.

    Lives here rather than in ``decision.conclusions`` so that modules below
    the decision layer (notably ``intelligence.narrative``) can refer to it
    without an upward import. The ``decision`` package re-exports it under its
    original name so existing callers are unaffected.
"""

from __future__ import annotations

from enum import StrEnum


class Stance(StrEnum):
    """What a conclusion asserts."""

    #: Something was observed. Supported by evidence of its presence.
    AFFIRMED = "affirmed"
    #: Something was looked for and not found, over a window deep enough to
    #: make that meaningful.
    NEGATED = "negated"
    #: The question could not be answered. Distinct from a negative.
    UNDETERMINED = "undetermined"


__all__ = ["Stance"]
