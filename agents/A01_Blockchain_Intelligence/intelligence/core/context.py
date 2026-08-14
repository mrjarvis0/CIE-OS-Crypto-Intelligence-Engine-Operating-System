"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.core.context

Purpose:
    Shared per-investigation context carrying subject, evidence,
    and intermediate results through the intelligence pipeline.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..schemas.evidence import EvidenceArtifact
from ..schemas.graph import GraphEdge, GraphNode
from ..schemas.score import Score
from ..utils.helpers import now_utc

logger = logging.getLogger("a01.intelligence.core")


@dataclass(slots=True)
class IntelligenceContext:
    """
    Mutable shared context for a single investigation.

    Carries the subject, collected evidence, scores, graph, findings,
    and an audit trail through the intelligence pipeline. Mutations are
    append-only for evidence/scores/graph to preserve provenance.
    """

    subject: dict[str, Any]
    context_id: str
    evidence: list[EvidenceArtifact] = field(default_factory=list)
    scores: list[Score] = field(default_factory=list)
    graph_nodes: list[GraphNode] = field(default_factory=list)
    graph_edges: list[GraphEdge] = field(default_factory=list)
    findings: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    audit: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._audit("context_created", {"context_id": self.context_id})

    def _audit(self, action: str, details: dict[str, Any]) -> None:
        self.audit.append(
            {
                "action": action,
                "at": now_utc().isoformat(),
                "details": details,
            }
        )

    def add_evidence(self, artifact: EvidenceArtifact) -> None:
        """Append an evidence artifact and log the mutation."""
        self.evidence.append(artifact)
        self._audit(
            "evidence_added",
            {"claim": artifact.claim, "content_hash": artifact.content_hash},
        )

    def add_score(self, score: Score) -> None:
        """Append a score."""
        self.scores.append(score)
        self._audit("score_added", {"name": score.name, "value": score.value})

    def add_node(self, node: GraphNode) -> None:
        """Append a graph node (skips duplicates by id)."""
        if any(n.node_id == node.node_id for n in self.graph_nodes):
            return
        self.graph_nodes.append(node)
        self._audit("node_added", {"node_id": node.node_id})

    def add_edge(self, edge: GraphEdge) -> None:
        """Append a graph edge (skips exact duplicates)."""
        if any(
            e.source == edge.source and e.target == edge.target for e in self.graph_edges
        ):
            return
        self.graph_edges.append(edge)
        self._audit("edge_added", {"source": edge.source, "target": edge.target})

    def set_finding(self, key: str, value: Any) -> None:
        """Set a named finding."""
        self.findings[key] = value

    def to_dict(self) -> dict[str, Any]:
        """Serialize the context."""
        return {
            "context_id": self.context_id,
            "subject": self.subject,
            "evidence": [e.to_dict() for e in self.evidence],
            "scores": [s.to_dict() for s in self.scores],
            "graph_nodes": [n.to_dict() for n in self.graph_nodes],
            "graph_edges": [e.to_dict() for e in self.graph_edges],
            "findings": self.findings,
            "created_at": self.created_at.isoformat(),
            "audit": self.audit,
        }
