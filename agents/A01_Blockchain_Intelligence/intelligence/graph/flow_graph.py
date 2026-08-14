"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.graph.flow_graph

Purpose:
    Generic money/value flow graph.
"""

from __future__ import annotations

from typing import Any

from ..schemas.graph import EdgeType, GraphNode
from .graph_builder import GraphBuilder


def _to_float(value: Any, default: float = 1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class FlowGraphBuilder:
    """
    Builds a directed flow graph from (source, target, value) flows.
    """

    def build(self, flows: list[dict[str, Any]]) -> GraphBuilder:
        """
        Construct a graph from flow dicts.

        Flows missing a source or target are skipped rather than
        materialized as phantom ``"None"`` nodes.
        """
        builder = GraphBuilder()
        for flow in flows:
            src_raw = flow.get("source")
            tgt_raw = flow.get("target")
            if not src_raw or not tgt_raw:
                continue
            src = str(src_raw)
            tgt = str(tgt_raw)
            builder.add_node(GraphNode(node_id=src, label=src, kind="flow_node"))
            builder.add_node(GraphNode(node_id=tgt, label=tgt, kind="flow_node"))
            builder.connect(
                src,
                tgt,
                EdgeType.TRANSFER,
                weight=_to_float(flow.get("value"), 1),
            )
        return builder
