"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.graph.visualization

Purpose:
    Graph export and visualization helpers.
"""

from __future__ import annotations

from typing import Any

from .graph_builder import GraphBuilder


class GraphVisualizer:
    """
    Exports a graph to portable formats.
    """

    def to_adjacency(self, builder: GraphBuilder) -> dict[str, list[dict[str, Any]]]:
        """
        Return an adjacency list representation.
        """
        result: dict[str, list[dict[str, Any]]] = {}
        for node in builder.nodes():
            result[node.node_id] = []
        for edge in builder.edges():
            result.setdefault(edge.source, []).append(
                {"target": edge.target, "edge_type": str(edge.edge_type), "weight": edge.weight}
            )
        return result

    def to_edges_list(self, builder: GraphBuilder) -> list[dict[str, Any]]:
        """
        Return a flat list of edge dicts.
        """
        return [
            {
                "source": e.source,
                "target": e.target,
                "edge_type": str(e.edge_type),
                "weight": e.weight,
            }
            for e in builder.edges()
        ]
