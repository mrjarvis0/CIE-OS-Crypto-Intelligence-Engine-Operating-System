"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    intelligence.evidence

Purpose:
    Evidence subsystem for the intelligence layer.

    Every conclusion must be backed by evidence. This package builds,
    validates, chains, ranks, and fingerprints evidence so intelligence
    outputs are explainable and auditable.

Submodules
----------
collector        Gather raw evidence from tools and sources.
builder          Assemble evidence artifacts and chains.
validator        Validate evidence structure and integrity.
provenance       Track source, lineage, and hash provenance.
source_rank      Rank evidence sources by reliability.
evidence_graph   Model relationships between evidence artifacts.
chain            Build ordered evidence chains to a conclusion.
confidence       Derive confidence from evidence strength.
"""

from __future__ import annotations

from .builder import EvidenceBuilder
from .chain import EvidenceChainBuilder
from .collector import EvidenceCollector
from .confidence import ConfidenceEngine
from .provenance import ProvenanceTracker
from .source_rank import SourceRanker
from .validator import EvidenceValidator

__all__ = [
    "EvidenceCollector",
    "EvidenceBuilder",
    "EvidenceValidator",
    "ProvenanceTracker",
    "SourceRanker",
    "EvidenceChainBuilder",
    "ConfidenceEngine",
]
