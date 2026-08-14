"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.graph.graph_builder

Purpose:
    Generic graph construction over nodes and edges.
"""

from __future__ import annotations

from typing import Any

from ..schemas.graph import EdgeType, GraphEdge, GraphNode

class GraphBuilder:
    """
    Accumulates nodes and edges into a graph.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []

    def add_node(self, node: GraphNode) -> "GraphBuilder":
        """
        Register a node by id.
        """
        self._nodes[node.node_id] = node
        return self

    def add_edge(self, edge: GraphEdge) -> "GraphBuilder":
        """
        Register a directed edge.
        """
        self._edges.append(edge)
        return self

    def connect(
        self,
        source: str,
        target: str,
        edge_type: EdgeType | str = EdgeType.OTHER,
        weight: float = 1.0,
        attributes: dict[str, Any] | None = None,
    ) -> "GraphBuilder":
        """
        Add an edge between two existing nodes.

        Attributes (e.g. transaction hash, timestamp) are stored on the
        edge for later audit.
        """
        self._edges.append(
            GraphEdge(
                source=source,
                target=target,
                edge_type=edge_type,
                weight=weight,
                attributes=dict(attributes or {}),
            )
        )
        return self

    def aggregate_edges(self) -> "GraphBuilder":
        """
        Collapse parallel edges into single edges with summed weights.

        Mirrors on-chain aggregation: rather than many tiny transfer
        edges, retain aggregate flow between a pair so large-velocity
        channels stand out. Edge attributes are dropped in favour of an
        edge-count field.
        """
        agg: dict[tuple[str, str, str], dict[str, Any]] = {}
        for edge in self._edges:
            key = (edge.source, edge.target, str(edge.edge_type))
            entry = agg.setdefault(
                key,
                {"source": edge.source, "target": edge.target, "edge_type": edge.edge_type, "weight": 0.0, "count": 0},
            )
            entry["weight"] += edge.weight
            entry["count"] += 1

        self._edges = [
            GraphEdge(
                source=e["source"],
                target=e["target"],
                edge_type=e["edge_type"],
                weight=e["weight"],
                attributes={"edge_count": e["count"]},
            )
            for e in agg.values()
        ]
        return self

    def prune(self, min_weight: float = 0.0) -> "GraphBuilder":
        """
        Remove edges below a weight threshold and orphaned nodes.

        Enables cheap graph reduction before expensive multi-hop
        traversal (research recommends pruning before expanding beyond a
        few hops).
        """
        self._edges = [e for e in self._edges if e.weight >= min_weight]
        referenced = {e.source for e in self._edges} | {e.target for e in self._edges}
        self._nodes = {k: v for k, v in self._nodes.items() if k in referenced}
        return self

    def nodes(self) -> list[GraphNode]:
        """All nodes."""
        return list(self._nodes.values())

    def edges(self) -> list[GraphEdge]:
        """All edges."""
        return list(self._edges)

    def adjacency(self) -> dict[str, list[tuple[str, float]]]:
        """
        Return an adjacency map: node_id -> [(neighbor, weight)].
        """
        adj: dict[str, list[tuple[str, float]]] = {n: [] for n in self._nodes}
        for edge in self._edges:
            adj.setdefault(edge.source, []).append((edge.target, edge.weight))
        return adj
