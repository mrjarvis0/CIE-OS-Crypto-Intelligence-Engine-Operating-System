"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.graph.pathfinding

Purpose:
    Path and connectivity analysis over a graph.
"""

from __future__ import annotations

from collections import deque

from .graph_builder import GraphBuilder


class Pathfinder:
    """
    Finds paths between nodes in a graph.

    Multi-hop traversal is bounded by a hop limit to control cost
    (on-chain research prunes exploration past a few hops where
    attribution confidence collapses).
    """

    def __init__(self, max_hops: int = 4) -> None:
        self._max_hops = max_hops

    def shortest_path(
        self,
        builder: GraphBuilder,
        source: str,
        target: str,
    ) -> list[str] | None:
        """
        Return the shortest path (BFS) from source to target, or None.
        """
        if source == target:
            return [source]
        adj = builder.adjacency()
        queue: deque[tuple[str, int]] = deque([(source, 0)])
        visited = {source}
        prev: dict[str, str] = {}
        while queue:
            current, depth = queue.popleft()
            if depth >= self._max_hops:
                continue
            for neighbor, _ in adj.get(current, []):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                prev[neighbor] = current
                if neighbor == target:
                    return self._reconstruct(prev, source, target)
                queue.append((neighbor, depth + 1))
        return None

    def reachable_within_hops(self, builder: GraphBuilder, source: str, max_hops: int | None = None) -> dict[str, int]:
        """
        Return every node reachable from source within the hop budget,
        mapped to its shortest distance. Useful for flow tracing from a
        seed address (deposit-chain / withdrawal-chain analysis).
        """
        limit = max_hops if max_hops is not None else self._max_hops
        adj = builder.adjacency()
        distances: dict[str, int] = {source: 0}
        queue: deque[str] = deque([source])
        while queue:
            current = queue.popleft()
            depth = distances[current]
            if depth >= limit:
                continue
            for neighbor, _ in adj.get(current, []):
                if neighbor in distances:
                    continue
                distances[neighbor] = depth + 1
                queue.append(neighbor)
        return distances

    def _reconstruct(self, prev: dict[str, str], source: str, target: str) -> list[str]:
        path: list[str] = []
        node = target
        while node != source:
            path.append(node)
            node = prev[node]
        path.append(source)
        path.reverse()
        return path
