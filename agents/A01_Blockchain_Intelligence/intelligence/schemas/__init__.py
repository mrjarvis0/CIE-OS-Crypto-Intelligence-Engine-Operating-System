"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.schemas

Purpose:
    Canonical data models for the intelligence layer. These dataclasses
    are the single source of truth shared across all intelligence
    subpackages (evidence, scoring, reporting, prediction, graph...).

Rules:
    - Dataclasses only; no business logic.
    - Fields are typed and defaulted for serialization safety.
    - Safe to import anywhere without side effects.
"""

from __future__ import annotations

from .entity import Entity, EntityType
from .evidence import EvidenceArtifact, EvidenceChain, EvidenceSource
from .graph import EdgeType, GraphEdge, GraphNode
from .intelligence import IntelligencePackage, IntelligencePipeline
from .prediction import Prediction, Scenario, ForecastPoint
from .report import ExecutiveSummary, IntelligenceReport
from .score import Score, ScoreComponent, ScoreBand
from .timeline import EventArtifact, Milestone, Timeline

__all__ = [
    # Evidence
    "EvidenceSource",
    "EvidenceArtifact",
    "EvidenceChain",
    # Entity
    "Entity",
    "EntityType",
    # Graph
    "GraphNode",
    "GraphEdge",
    "EdgeType",
    # Intelligence
    "IntelligencePackage",
    "IntelligencePipeline",
    # Prediction
    "ForecastPoint",
    "Prediction",
    "Scenario",
    # Report
    "ExecutiveSummary",
    "IntelligenceReport",
    # Score
    "ScoreBand",
    "ScoreComponent",
    "Score",
    # Timeline
    "EventArtifact",
    "Milestone",
    "Timeline",
]
