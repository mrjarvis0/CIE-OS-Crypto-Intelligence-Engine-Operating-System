"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    decision

Purpose:
    Decides what to conclude and what to alert on. Does not interpret data.

Layer contract
--------------
`intelligence/` decides what the data *means*. This layer decides what may be
*said* about it and who should be interrupted. It reads findings that were
already interpreted and applies policy — ceilings, vocabulary, falsifiability,
coverage, alert budgets — without re-reading a transfer or re-deciding whether
it was large.

Four rules carry the layer
--------------------------
* **Maturity gates privileges.** `Implemented` caps confidence at 0.60;
  only `Validated` may alert. Both A01 detectors are `Implemented`, so
  :class:`MaturityGate` currently blocks every alert — which is the correct
  behaviour, not a bug to route around.
* **Confidence sets the verb.** :mod:`decision.vocabulary` holds the
  evidence-standard table, so "likely" cannot become "is" on the way to a
  reader. It lives here rather than in a renderer because a rule enforced in
  each of several renderers is enforced in none.
* **The binding constraint, never the average.** A conclusion resting on a 0.95
  observation and a 0.30 inference is bounded by the inference; 0.62 would hide
  which link is load-bearing.
* **A negative claim needs a window.** "No whale activity" over six blocks is a
  statement about the six blocks. Without coverage the stance degrades to
  `undetermined`, which is a different claim and the true one.

Usage
-----
::

    engine = DecisionEngine(subscriptions=[Subscription("desk")])
    decision = engine.decide(package)

    decision.silence_explained
    # 'no detector has a measured error rate, so none may alert …'

:attr:`Decision.silence_explained` answers the likeliest operational question
about A01 today — why nothing fired — from the output rather than from doctrine.
"""

from __future__ import annotations

from .alerts import (
    DEFAULT_DAILY_BUDGET,
    MIN_ALERT_CONFIDENCE,
    Alert,
    AlertDecision,
    AlertPolicy,
    Digest,
    Subscription,
    SuppressedAlert,
    Suppression,
)
from .conclusions import Conclusion, ConclusionBuilder, Stance
from .engine import Decision, DecisionEngine
from .maturity import (
    ALERT_MATURITY,
    CEILINGS,
    REGISTRY,
    DetectorMaturity,
    GateDecision,
    Maturity,
    MaturityGate,
)
from .recommendations import Action, Recommendation, RecommendationEngine
from .vocabulary import (
    BANDS,
    BindingConstraint,
    ConfidenceBand,
    VocabularyError,
    band_for,
    binding_constraint,
    enforce,
    permitted_verbs,
    qualifier,
    violations,
)

__all__ = [
    "ALERT_MATURITY",
    "BANDS",
    "CEILINGS",
    "DEFAULT_DAILY_BUDGET",
    "MIN_ALERT_CONFIDENCE",
    "REGISTRY",
    "Action",
    "Alert",
    "AlertDecision",
    "AlertPolicy",
    "BindingConstraint",
    "Conclusion",
    "ConclusionBuilder",
    "ConfidenceBand",
    "Decision",
    "DecisionEngine",
    "DetectorMaturity",
    "Digest",
    "GateDecision",
    "Maturity",
    "MaturityGate",
    "Recommendation",
    "RecommendationEngine",
    "Stance",
    "Subscription",
    "SuppressedAlert",
    "Suppression",
    "VocabularyError",
    "band_for",
    "binding_constraint",
    "enforce",
    "permitted_verbs",
    "qualifier",
    "violations",
]
