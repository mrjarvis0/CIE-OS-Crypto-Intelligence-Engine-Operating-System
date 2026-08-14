"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.schemas.graph

Purpose:
    Canonical graph data models.

    GraphNode and GraphEdge describe nodes and directed edges used by
    wallet, token, flow, and cluster graph builders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class EdgeType(StrEnum):
    """
    Semantic type of a graph edge.
    """

    TRANSFER = "transfer"
    CREATED_BY = "created_by"
    OWNS = "owns"
    FUNDED_BY = "funded_by"
    INTERACTS_WITH = "interacts_with"
    CONTROLS = "controls"
    SAME_ENTITY = "same_entity"
    BRIDGE = "bridge"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class GraphNode:
    """
    A node in an intelligence graph.
    """

    node_id: str
    label: str
    kind: str = "unknown"
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "kind": self.kind,
            "attributes": self.attributes,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """
    A directed edge between two graph nodes.
    """

    source: str
    target: str
    edge_type: EdgeType | str = EdgeType.OTHER
    weight: float = 1.0
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "edge_type": str(self.edge_type),
            "weight": self.weight,
            "attributes": self.attributes,
            "created_at": self.created_at.isoformat(),
        }
