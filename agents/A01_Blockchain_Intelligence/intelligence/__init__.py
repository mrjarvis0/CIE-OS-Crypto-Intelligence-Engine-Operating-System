"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    intelligence

Purpose:
    Cognitive intelligence layer for the A01 Blockchain Intelligence Agent.

    Converts raw, tool-collected evidence into explainable,
    evidence-backed, and decision-ready intelligence through a
    structured intelligence cycle:

        Observe -> Collect -> Normalize -> Correlate -> Reason
        -> Hypothesize -> Verify -> Score -> Predict -> Explain
        -> Report -> Remember

Subpackages
-----------
core           Intelligence engine, pipeline, manager, context, state,
               runtime, configuration, session.
reasoning      Structured multi-step reasoning engines.
evidence       Evidence building, provenance, source ranking, chains.
analysis       Domain analyzers (wallet, token, contract, whale...).
correlation    Cross-source entity and wallet linking.
attribution    Identity, label, and ownership attribution.
graph          Graph intelligence and flow/path analysis.
timeline       Chronological event reconstruction.
scoring        Risk, trust, fraud, reputation, whale, anomaly scores.
prediction     Trend, wallet, market, scenario forecasting.
hypothesis     Hypothesis generation, testing, elimination, ranking.
verification   Cross-checking claims against external sources.
reporting      Final intelligence report rendering.
alerts         Intelligence triggers and notifications.
monitoring     Metrics, profiling, diagnostics, tracing, health.
schemas        Canonical intelligence data models.
utils          Normalization, hashing, formatting, ranking, converters.
"""

from __future__ import annotations

from . import (
    alerts,
    analysis,
    attribution,
    core,
    correlation,
    evidence,
    graph,
    hypothesis,
    monitoring,
    prediction,
    reasoning,
    reporting,
    schemas,
    scoring,
    timeline,
    utils,
    verification,
)

__version__ = "0.1.0"

__all__ = [
    "alerts",
    "analysis",
    "attribution",
    "core",
    "correlation",
    "evidence",
    "graph",
    "hypothesis",
    "monitoring",
    "prediction",
    "reasoning",
    "reporting",
    "schemas",
    "scoring",
    "timeline",
    "utils",
    "verification",
]
