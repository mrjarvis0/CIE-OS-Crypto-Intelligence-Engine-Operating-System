"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    cli.render

Purpose:
    Render an ``IntelligencePackage`` for a human reader.

Confidence vocabulary
---------------------
The verb used to present a finding is bound to its confidence. A renderer
that says "is" for a 0.55-confidence claim launders an inference into a fact,
which is exactly what the evidence standard prohibits. The mapping here is
the one enforcement point between the engine and a human eye.

See docs/intelligence/evidence-standard.md section 7.
"""

from __future__ import annotations

from typing import Any

#: Confidence band -> (label, permitted qualifier). Ordered high to low.
CONFIDENCE_VOCABULARY: tuple[tuple[float, str, str], ...] = (
    (0.90, "very high", "is"),
    (0.70, "high", "strongly indicates"),
    (0.50, "moderate", "likely"),
    (0.30, "low", "possibly"),
    (0.00, "insufficient", "cannot be determined from"),
)

_BAND_MARK = {
    "critical": "!!",
    "high": "!",
    "medium": "~",
    "low": ".",
    "none": " ",
}


def qualify(confidence: float) -> tuple[str, str]:
    """Return the (label, qualifier) permitted at this confidence."""
    for floor, label, verb in CONFIDENCE_VOCABULARY:
        if confidence >= floor:
            return label, verb
    return "insufficient", "cannot be determined from"


def _rule(char: str = "-", width: int = 68) -> str:
    return char * width


def render_text(package: dict[str, Any]) -> str:
    """
    Render a package as plain text.

    Deliberately dependency-free: an intelligence tool that cannot print its
    findings without a rendering library is fragile in exactly the situations
    where it matters.
    """
    out: list[str] = []
    findings = package.get("metadata", {}).get("findings", {})
    report = findings.get("report", {}) or {}
    scores = package.get("scores", []) or []
    signal = next((s for s in scores if s.get("name") == "signal"), {})

    confidence = float(report.get("confidence", 0.0) or 0.0)
    label, verb = qualify(confidence)
    band = str(signal.get("band", "none"))

    out.append(_rule("="))
    out.append("A01 BLOCKCHAIN INTELLIGENCE")
    out.append(_rule("="))
    out.append(f"Subject     : {report.get('subject') or package.get('subject')}")
    out.append(f"Package     : {package.get('package_id')}")
    out.append("")

    out.append(f"Signal      : {signal.get('value', 0.0)}/100  "
               f"[{_BAND_MARK.get(band, ' ')}{band}]")
    out.append(f"Confidence  : {confidence:.2f} ({label})")
    out.append("")

    # -- findings -------------------------------------------------------
    out.append("FINDINGS")
    out.append(_rule())
    lines = report.get("findings") or []
    if not lines:
        out.append("  No findings. Evidence was insufficient to support any claim.")
    for line in lines:
        out.append(f"  - {line}")
    out.append("")

    # -- score components ----------------------------------------------
    components = signal.get("components") or []
    if components:
        out.append("SCORE COMPONENTS")
        out.append(_rule())
        for component in components:
            out.append(
                f"  {component.get('name', '?'):<24} "
                f"+{component.get('value', 0.0):>6}"
            )
        out.append("")

    # -- confidence basis ----------------------------------------------
    meta = signal.get("metadata", {}) or {}
    if meta:
        out.append("CONFIDENCE BASIS")
        out.append(_rule())
        out.append(f"  structural evidence   : {meta.get('structural_confidence', 0.0)}")
        out.append(f"  attribution evidence  : {meta.get('attribution_confidence', 0.0)}")
        out.append(f"  ceiling               : {meta.get('ceiling', 0.0)}"
                   f"{'  (binding)' if meta.get('ceiling_binding') else ''}")
        collapsed = meta.get("correlated_collapsed", 0)
        if collapsed:
            out.append(f"  correlated collapsed  : {collapsed} "
                       "(shared ancestry, counted once)")
        unmeasured = meta.get("unmeasured_sources", 0)
        if unmeasured:
            out.append(f"  unmeasured detectors  : {unmeasured} "
                       "(confidence capped at 0.60)")
        out.append("")

    # -- evidence -------------------------------------------------------
    chains = package.get("evidence_chains") or []
    out.append(f"EVIDENCE ({len(chains)} chain(s))")
    out.append(_rule())
    for chain in chains:
        out.append(f"  {chain.get('conclusion')}")
        for artifact in chain.get("artifacts", []):
            out.append(
                f"      tier={artifact.get('tier')} "
                f"source={artifact.get('source_type')} "
                f"conf={artifact.get('confidence')} "
                f"method={artifact.get('method')}"
            )
    if not chains:
        out.append("  (none)")
    out.append("")

    # -- verification ----------------------------------------------------
    verification = findings.get("verification") or {}
    if verification:
        out.append("VERIFICATION")
        out.append(_rule())
        out.append(f"  artifacts valid    : {verification.get('artifacts_valid', 0)}"
                   f"/{verification.get('artifacts_total', 0)}")
        for rejected in verification.get("rejected", []):
            out.append(f"  REJECTED {rejected.get('claim')}: "
                       f"{'; '.join(rejected.get('errors', []))}")
        for ungrounded in verification.get("ungrounded", []):
            out.append(f"  UNGROUNDED {ungrounded}")
        out.append("")

    # -- pipeline --------------------------------------------------------
    pipeline = package.get("pipeline") or {}
    results = (pipeline.get("metadata") or {}).get("stage_results", [])
    failures = (pipeline.get("metadata") or {}).get("failure_count", 0)
    out.append("PIPELINE")
    out.append(_rule())
    out.append("  " + " -> ".join(r.get("stage", "?") for r in results))
    if failures:
        out.append(f"  {failures} stage failure(s):")
        for result in results:
            if not result.get("ok"):
                out.append(f"    {result.get('stage')}: {result.get('error')}")
    out.append("")

    out.append(_rule("="))
    if confidence >= 0.30:
        out.append(f"Evidence {verb} the conclusions above ({label} confidence).")
    else:
        out.append(
            "These conclusions cannot be determined from the available "
            "evidence."
        )
    out.append(
        "A01 provides evidence, not decisions; final judgement remains with "
        "the operator."
    )
    out.append(_rule("="))

    return "\n".join(out)


def render_decision(decision: dict[str, Any]) -> str:
    """
    Render the decision layer's output: conclusions, alerting, next steps.

    Verbs come from the decision, never from here. The evidence standard's
    vocabulary rule is enforced where a conclusion is *formed*
    (``decision.vocabulary``) precisely so a renderer cannot upgrade it — this
    function prints ``conclusion["qualifier"]`` and never picks its own.
    """
    out: list[str] = ["", _rule("="), "DECISION", _rule("=")]

    conclusions = decision.get("conclusions") or []
    if not conclusions:
        out.append("  no conclusions were reached")
    for item in conclusions:
        stance = item.get("stance", "?")
        out.append(
            f"  [{stance:<12}] {item.get('qualifier', '?')}: {item.get('claim', '')}"
        )
        out.append(
            f"{'':<17}confidence {item.get('confidence', 0.0):.2f}"
            f"   priority {item.get('priority', 0.0)}"
        )
        if item.get("falsified_by"):
            out.append(f"{'':<17}retracted by: {item['falsified_by']}")
        for caveat in item.get("caveats") or []:
            out.append(f"{'':<17}caveat: {caveat}")

    constraint = decision.get("constraint")
    if constraint:
        out.append("")
        out.append("BINDING CONSTRAINT")
        out.append(_rule())
        # The weakest link, not an average. An averaged confidence hides which
        # step the whole conclusion actually rests on.
        out.append(
            f"  {constraint.get('confidence', 0.0):.2f} "
            f"({constraint.get('band', '?')}) — {constraint.get('source', '?')}"
        )

    alerts = decision.get("alerts") or {}
    out.append("")
    out.append("ALERTS")
    out.append(_rule())
    raised = alerts.get("raised") or []
    if raised:
        for alert in raised:
            out.append(
                f"  {alert.get('detector')}: {alert.get('claim')} "
                f"-> {alert.get('subscription')}"
            )
    else:
        out.append("  none raised")
        if decision.get("silence_explained"):
            out.append(f"  reason: {decision['silence_explained']}")

    recommendations = decision.get("recommendations") or []
    if recommendations:
        out.append("")
        out.append("NEXT STEPS")
        out.append(_rule())
        for rec in recommendations[:5]:
            out.append(f"  [{rec.get('action')}] {rec.get('detail')}")

    out.append(_rule("="))
    return "\n".join(out)


def render_narrative(publication: dict[str, Any]) -> str:
    """
    Render the composed explanation and how it was produced.

    The provenance line is printed even when no model is involved. A reader
    comparing two reports needs to be able to tell deterministic prose from
    model-authored prose, and "no line means no model" is the kind of implicit
    convention that stops holding the moment a model is added.
    """
    narrative = publication.get("narrative") or {}
    out: list[str] = ["", _rule("="), "NARRATIVE", _rule("=")]

    text = narrative.get("text", "").strip()
    out.append(text if text else "  (no narrative was produced)")

    out.append("")
    out.append(_rule())
    method = narrative.get("method", "unknown")
    reproducibility = narrative.get("reproducibility", "unknown")
    out.append(f"  method: {method}  ({reproducibility})")

    if publication.get("fell_back"):
        # Distinguishes "the model wrote this" from "the model's text was
        # rejected and the composer's was used".
        out.append(f"  model output rejected: {publication.get('fallback_reason', '')}")

    grounding = publication.get("grounding")
    if grounding:
        out.append(
            f"  grounding: {grounding.get('checked', 0)} particular(s) checked, "
            f"{grounding.get('ungrounded_count', 0)} ungrounded"
        )

    out.append(_rule("="))
    return "\n".join(out)
