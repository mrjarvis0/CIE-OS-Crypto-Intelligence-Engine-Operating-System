"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.graph.cluster_graph

Purpose:
    Cluster relationship graph.

    Members of the same cluster are connected through the cluster node
    with bidirectional edges, so any two members of a cluster are
    mutually reachable through graph traversal.
"""

from __future__ import annotations

from typing import Any

from ..schemas.graph import EdgeType, GraphNode
from .graph_builder import GraphBuilder


class ClusterGraphBuilder:
    """
    Builds a graph linking members within clusters.
    """

    def build(self, clusters: list[dict[str, Any]]) -> GraphBuilder:
        """
        Construct a graph where cluster members share an edge.

        Each member is connected to its cluster node in both
        directions, making the cluster a hub: traversal from any
        member reaches every other member of the same cluster.
        """
        builder = GraphBuilder()
        for cluster in clusters:
            cluster_id = str(cluster.get("cluster_id"))
            members = cluster.get("members", [])
            for member in members:
                if member is None:
                    continue
                node_id = str(member)
                builder.add_node(GraphNode(node_id=node_id, label=node_id, kind="member"))
                if not cluster_id:
                    continue
                builder.add_node(
                    GraphNode(node_id=cluster_id, label=cluster_id, kind="cluster")
                )
                builder.connect(node_id, cluster_id, EdgeType.INTERACTS_WITH)
                builder.connect(cluster_id, node_id, EdgeType.INTERACTS_WITH)
        return builder
