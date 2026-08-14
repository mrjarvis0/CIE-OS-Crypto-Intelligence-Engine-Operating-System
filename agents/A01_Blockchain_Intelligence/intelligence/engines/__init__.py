"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    intelligence.engines

Purpose:
    Higher-order components that combine skills into an investigation.

Layer contract
--------------
A skill answers one question. An engine combines several into something neither
could state alone, and it is the only layer allowed to do so.

:class:`SubjectComposer` is the first of them, and the one that connects A01's
two halves: it runs the skills layer against stored history and assembles the
subject the detectors consume. Before it existed, the detectors could analyse
only what a caller had already described by hand, so five phases of captured
history went unread.

Composition preserves the weakest caveat rather than the best answer. Each skill
states what its window licenses; the composed subject carries the minimum, so a
deep window on one field cannot license an absence claim about a field that came
from a shallow one.
"""

from __future__ import annotations

from .composition import Composition, SubjectComposer

__all__ = ["Composition", "SubjectComposer"]
