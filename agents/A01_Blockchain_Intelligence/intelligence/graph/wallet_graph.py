"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.graph.wallet_graph

Purpose:
    Wallet relationship graph.
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


class WalletGraphBuilder:
    """
    Builds a graph of wallet relationships from transaction data.
    """

    def build(self, transactions: list[dict[str, Any]]) -> GraphBuilder:
        """
        Construct a graph from a list of transaction dicts.

        Transactions missing a sender or recipient are skipped rather
        than materialized as phantom ``"None"`` nodes. Each transfer
        edge carries audit metadata (transaction hash, timestamp,
        token, method) when present.
        """
        builder = GraphBuilder()
        for tx in transactions:
            src_raw = tx.get("from")
            tgt_raw = tx.get("to")
            if not src_raw or not tgt_raw:
                continue
            src = str(src_raw)
            tgt = str(tgt_raw)
            attributes = {
                k: tx[k]
                for k in ("hash", "timestamp", "block_number", "token", "method")
                if k in tx
            }
            builder.add_node(GraphNode(node_id=src, label=src, kind="wallet"))
            builder.add_node(GraphNode(node_id=tgt, label=tgt, kind="wallet"))
            builder.connect(
                src,
                tgt,
                EdgeType.TRANSFER,
                weight=_to_float(tx.get("value"), 1),
                attributes=attributes,
            )
        return builder
