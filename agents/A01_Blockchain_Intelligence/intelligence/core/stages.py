"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.core.stages

Purpose:
    Default pipeline stage functions, and the wiring that turns
    :class:`~intelligence.core.engine.IntelligenceEngine` from an empty
    orchestrator into a working investigation.

Background
----------
The engine, pipeline, and context were all implemented, but no stage
functions were ever registered. ``engine.run(subject)`` therefore executed
zero stages and returned a package with no evidence, no scores, and no
findings -- structurally valid and completely empty.

This module supplies the stages. Each is a plain ``(context) -> None``
callable, so the pipeline's existing timeout, isolation, and timing
machinery applies unchanged.

Stage contract
--------------
A stage mutates the context and returns nothing. It must not raise for
ordinary "no data" conditions -- absence of a signal is a result, not an
error. The pipeline isolates genuine failures per stage, so a broken
analyzer degrades one stage rather than the investigation.
"""

from __future__ import annotations

import logging
from typing import Any

from ..analysis.base import Analyzer, AnalyzerResult
from ..analysis.anomaly import AnomalyAnalyzer
from ..analysis.dormant import DormantAnalyzer
from ..analysis.exchange import ExchangeFlowAnalyzer
from ..analysis.whale import WhaleAnalyzer
from ..evidence.confidence import ConfidenceEngine
from ..evidence.evidence_graph import EvidenceGraph
from ..evidence.validator import EvidenceValidator
from ..schemas.evidence import ClaimTier
from ..schemas.intelligence import PipelineStage
from ..schemas.score import Score, ScoreBand, ScoreComponent
from .context import IntelligenceContext

logger = logging.getLogger("a01.intelligence.core")


#: Analyzers run during the analysis stage, in order.
#:
#: Only analyzers that have been rebuilt against the detection catalog are
#: registered. The remaining ``intelligence/analysis`` modules are scaffolds;
#: wiring them in would emit unverified output that looks authoritative, so
#: they stay out until they meet the spec.
DEFAULT_ANALYZERS: tuple[Analyzer, ...] = (
    WhaleAnalyzer(),
    DormantAnalyzer(),
    AnomalyAnalyzer(),
    ExchangeFlowAnalyzer(),
)


def _band(value: float) -> ScoreBand:
    """Map a 0..100 score onto its qualitative band."""
    if value >= 80:
        return ScoreBand.CRITICAL
    if value >= 60:
        return ScoreBand.HIGH
    if value >= 35:
        return ScoreBand.MEDIUM
    if value > 0:
        return ScoreBand.LOW
    return ScoreBand.NONE


# =============================================================================
# Stages
# =============================================================================


def make_analysis_stage(
    analyzers: tuple[Analyzer, ...] = DEFAULT_ANALYZERS,
):
    """
    Build the stage that runs every registered analyzer over the subject.

    Analyzer results land in ``context.findings`` keyed by analyzer name, and
    their evidence is appended to the context. A single analyzer raising is
    contained here rather than at the pipeline boundary, so one broken
    detector does not cost the results of the others that share this stage.
    """

    def analyze(context: IntelligenceContext) -> None:
        for analyzer in analyzers:
            try:
                result: AnalyzerResult = analyzer.analyze(context.subject)
            except Exception as exc:  # noqa: BLE001 - analyzer boundary
                logger.warning("analyzer %s failed: %s", analyzer.name, exc)
                context.set_finding(
                    analyzer.name, {"error": str(exc), "ok": False}
                )
                continue

            context.set_finding(analyzer.name, result.to_dict())
            for artifact in result.evidence:
                context.add_evidence(artifact)

    return analyze


def verify(context: IntelligenceContext) -> None:
    """
    Validate every collected artifact and check chain grounding.

    Invalid evidence is recorded rather than silently dropped: a consumer
    needs to know that something was rejected, and why. An artifact that
    fails validation must not reach scoring.
    """
    validator = EvidenceValidator()
    graph = EvidenceGraph()

    valid: list[str] = []
    rejected: list[dict[str, Any]] = []

    for artifact in context.evidence:
        errors = validator.validate(artifact)
        if errors:
            rejected.append({"claim": artifact.claim, "errors": errors})
            continue
        graph.add(artifact)
        valid.append(artifact.content_hash or artifact.claim)

    ungrounded = graph.validate()

    context.set_finding(
        "verification",
        {
            "artifacts_total": len(context.evidence),
            "artifacts_valid": len(valid),
            "artifacts_rejected": len(rejected),
            "rejected": rejected,
            "ungrounded": ungrounded,
        },
    )


def score(context: IntelligenceContext) -> None:
    """
    Derive scores from validated evidence.

    Confidence comes from :class:`ConfidenceEngine`, so tier ceilings,
    correlation collapse, and expiry all apply. A score's confidence is
    therefore bounded by the evidence behind it rather than asserted.
    """
    engine = ConfidenceEngine()
    evidence = list(context.evidence)

    if not evidence:
        context.add_score(
            Score(
                name="signal",
                value=0.0,
                confidence=0.0,
                band=ScoreBand.NONE,
                metadata={"reason": "no evidence collected"},
            )
        )
        return

    structural = engine.tier_score(evidence, ClaimTier.STRUCTURAL)
    attribution = engine.tier_score(evidence, ClaimTier.ATTRIBUTION)
    detail = engine.explain(evidence)

    components: list[ScoreComponent] = []
    value = 0.0

    whale = context.findings.get("whale", {}).get("data", {})
    if whale.get("is_whale"):
        weight = 40.0
        components.append(
            ScoreComponent(name="whale_activity", value=weight, weight=1.0)
        )
        value += weight
        if whale.get("flow", {}).get("exchange_signal") == "deposit_to_exchange":
            components.append(
                ScoreComponent(name="exchange_deposit", value=25.0, weight=1.0)
            )
            value += 25.0

    dormant = context.findings.get("dormant", {}).get("data", {})
    if dormant.get("reactivated"):
        severity = dormant.get("signal", {}).get("severity", "low")
        weight = {"high": 35.0, "medium": 20.0, "low": 10.0}.get(severity, 10.0)
        components.append(
            ScoreComponent(name="dormant_reactivation", value=weight, weight=1.0)
        )
        value += weight

    anomaly = context.findings.get("anomaly", {}).get("data", {})
    if anomaly.get("is_anomalous"):
        # Weighted below whale and dormant on purpose. A statistical outlier is
        # the weakest of the three claims: it says a value is far from its
        # population and nothing about why, so it should raise the signal
        # without being able to carry an investigation on its own.
        weight = {
            "HIGH_RISK_PATTERN": 30.0,
            "SUSPICIOUS": 20.0,
            "UNUSUAL": 10.0,
        }.get(anomaly.get("grade", ""), 10.0)
        components.append(
            ScoreComponent(name="statistical_anomaly", value=weight, weight=1.0)
        )
        value += weight

    exchange = context.findings.get("exchange_flow", {}).get("data", {})
    if exchange.get("is_directional"):
        # Below whale and below a high-severity dormant reactivation. The
        # direction is measured, but the attribution under it comes from a list
        # A01 did not verify, and a window one-sided by 21% is barely over the
        # line -- so the weight follows the imbalance rather than being flat.
        # Concentration adds to it: a window carried by one operator is a fact
        # about that operator, and a diffuse one is a fact about the hour.
        weight = 15.0 + 10.0 * min(1.0, float(exchange.get("imbalance", 0.0)))
        if exchange.get("concentrated"):
            weight += 5.0
        components.append(
            ScoreComponent(name="exchange_flow_direction", value=round(weight, 2), weight=1.0)
        )
        value += weight

    value = min(100.0, value)

    context.add_score(
        Score(
            name="signal",
            value=round(value, 2),
            confidence=detail["confidence"],
            band=_band(value),
            components=tuple(components),
            metadata={
                "structural_confidence": structural,
                "attribution_confidence": attribution,
                "ceiling": detail["ceiling"],
                "ceiling_binding": detail["ceiling_binding"],
                "correlated_collapsed": detail["correlated_collapsed"],
                "unmeasured_sources": detail["unmeasured_sources"],
            },
        )
    )


def report(context: IntelligenceContext) -> None:
    """
    Assemble a human-readable summary of the investigation.

    Verb choice is bound to confidence: the evidence standard forbids
    asserting an inference as a fact, and a renderer that says "is" for a
    0.55-confidence claim launders one into the other.
    """
    signal = next((s for s in context.scores if s.name == "signal"), None)
    confidence = signal.confidence if signal else 0.0

    if confidence >= 0.70:
        verb = "strongly indicates"
    elif confidence >= 0.50:
        verb = "likely"
    elif confidence >= 0.30:
        verb = "possibly"
    else:
        verb = "cannot be determined from"

    # Every analyzer that said something, in registration order.
    #
    # Derived rather than listed. This was a hardcoded ("whale", "dormant")
    # tuple, so registering a third analyzer wired it into the score and the
    # decision gate while silently leaving it out of the findings a reader
    # actually sees -- a detector that fires but never appears is worse than
    # one that was never added. Only analyzer results carry a summary; the
    # verification finding has none, and the report itself is set below.
    lines = [
        finding["summary"]
        for finding in context.findings.values()
        if isinstance(finding, dict) and finding.get("summary")
    ]

    # Coverage arrives from the skills layer when the subject was composed from
    # storage. Absent for a hand-supplied subject, where the caller is the one
    # asserting the facts and A01 cannot say how complete they are.
    coverage = context.subject.get("coverage")
    absence_meaningful = bool(context.subject.get("absence_meaningful"))

    context.set_finding(
        "report",
        {
            "subject": context.subject.get("address"),
            "signal_score": signal.value if signal else 0.0,
            "band": str(signal.band) if signal else "none",
            "confidence": confidence,
            "qualifier": verb,
            "findings": lines,
            "evidence_count": len(context.evidence),
            "coverage": coverage,
            # The report's own statement of what it may not be read as saying.
            # A null signal over a thin window means "nothing was looked at",
            # not "nothing is there", and only this flag separates the two.
            "absence_meaningful": absence_meaningful,
            "negative_claims_licensed": absence_meaningful,
        },
    )


# =============================================================================
# Wiring
# =============================================================================


def register_default_stages(
    pipeline: Any,
    analyzers: tuple[Analyzer, ...] = DEFAULT_ANALYZERS,
) -> Any:
    """
    Register the default stage set on a pipeline and return it.

    Stage names reuse :class:`PipelineStage` where one fits, so timings line
    up with the stage vocabulary the rest of the system already reports.
    """
    pipeline.add(PipelineStage.CORRELATE, make_analysis_stage(analyzers))
    pipeline.add(PipelineStage.VERIFY, verify)
    pipeline.add(PipelineStage.SCORE, score)
    pipeline.add(PipelineStage.REPORT, report)
    return pipeline
