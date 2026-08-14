"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    intelligence.narrative

Purpose:
    The AI layer. Explains evidence; never becomes a source of it.

The contract
------------
`evidence-standard.md` §6: a model may **structure, summarise and explain**
evidence and **propose hypotheses**, and may **never introduce a factual claim**
absent from the evidence chain. Anything it states that is not already there is
a hallucination by definition and must be detected and stripped.

`capabilities.md` §7.1 draws the same line for machine learning: permitted for
**triage and ranking**, never for **conclusion**. A model may decide what gets
examined next; it may not be the component that asserts a fact.

How that is enforced
--------------------
* :class:`NarrativeComposer` writes the explanation from the decision's own
  fields. It cannot fabricate a particular because it never writes one it was
  not handed, and it prints the qualifier the decision computed rather than
  choosing a verb.
* :class:`GroundingCheck` verifies every checkable particular — address, hash,
  quantity — against the evidence, including the abbreviated `0xabcd…wxyz`
  form at **both** ends. Deterministic on purpose: a model must not be what
  decides whether a model hallucinated.
* :class:`NarrativeService` is the only path to published prose. A provider
  proposes; the service grounds, and falls back to the composer on failure
  rather than publishing a hedged version.

Current state
-------------
**No model is configured.** Narratives are composed deterministically, which
means they are grounded by construction, reproducible, and usable as a
regression baseline. The seam exists now because the only moment to make the
checked path the *only* path is before anyone needs a narrative shipped.

Known limit
-----------
Grounding catches fabricated **particulars**, not fabricated **relations**
between real ones — "A sent to B" and "B sent to A" contain the same
particulars. That is why sentences are built from evidence fields rather than
phrased by a model: the check is a backstop for the composer's guarantee, not a
replacement for it.
"""

from __future__ import annotations

from .composer import Narrative, NarrativeComposer
from .grounding import (
    NUMERIC_TOLERANCE,
    SMALL_NUMBER_CEILING,
    Finding,
    GroundingCheck,
    GroundingReport,
    Particular,
)
from .provider import (
    ModelIdentity,
    NarrativeProvider,
    NarrativeService,
    Publication,
)

__all__ = [
    "NUMERIC_TOLERANCE",
    "SMALL_NUMBER_CEILING",
    "Finding",
    "GroundingCheck",
    "GroundingReport",
    "ModelIdentity",
    "Narrative",
    "NarrativeComposer",
    "NarrativeProvider",
    "NarrativeService",
    "Particular",
    "Publication",
]
