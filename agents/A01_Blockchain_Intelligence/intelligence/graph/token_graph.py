"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.graph.token_graph

Purpose:
    Token flow graph.
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


class TokenGraphBuilder:
    """
    Builds a graph of token transfers between addresses.
    """

    def build(self, transfers: list[dict[str, Any]]) -> GraphBuilder:
        """
        Construct a graph from a list of transfer dicts.

        Transfers missing a sender or recipient are skipped rather
        than materialized as phantom ``"None"`` nodes.
        """
        builder = GraphBuilder()
        for transfer in transfers:
            src_raw = transfer.get("from")
            tgt_raw = transfer.get("to")
            if not src_raw or not tgt_raw:
                continue
            src = str(src_raw)
            tgt = str(tgt_raw)
            builder.add_node(GraphNode(node_id=src, label=src, kind="address"))
            builder.add_node(GraphNode(node_id=tgt, label=tgt, kind="address"))
            builder.connect(
                src,
                tgt,
                EdgeType.TRANSFER,
                weight=_to_float(transfer.get("amount"), 1),
            )
        return builder
