"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.correlation.cluster

Purpose:
    Cluster related subjects into groups.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .correlator import Correlation


@dataclass(slots=True)
class Cluster:
    """
    A group of related subjects.
    """

    cluster_id: str
    members: list[str] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "members": list(self.members),
            "relations": list(self.relations),
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
        }


class Clusterer:
    """
    Builds connected components from a set of correlations.

    Confidence for a cluster is the minimum of the edge confidences that
    hold it together -- a conservative bound that reflects the weakest
    link in the connected component.
    """

    def cluster(self, correlations: list[Correlation]) -> list[Cluster]:
        """
        Group subjects by shared correlations (union-find).

        Returns clusters ordered by descending confidence so the
        strongest groupings appear first.
        """
        parent: dict[str, str] = {}

        def find(node: str) -> str:
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        def union(a: str, b: str) -> None:
            parent.setdefault(a, a)
            parent.setdefault(b, b)
            root_a, root_b = find(a), find(b)
            if root_a != root_b:
                parent[root_a] = root_b

        for corr in correlations:
            union(corr.left, corr.right)

        groups: dict[str, set[str]] = {}
        for node in parent:
            root = find(node)
            groups.setdefault(root, set()).add(node)

        clusters: list[Cluster] = []
        for idx, (root, members) in enumerate(groups.items()):
            internal = [
                c
                for c in correlations
                if c.left in members and c.right in members
            ]
            rels = [c.relation for c in internal]
            evidence = [r for c in internal for r in c.evidence_refs]
            # Conservative: weakest supporting edge bounds cluster confidence.
            conf = min((c.confidence for c in internal), default=0.0)
            clusters.append(
                Cluster(
                    cluster_id=f"cluster-{idx}",
                    members=sorted(members),
                    relations=rels,
                    confidence=conf,
                    evidence_refs=evidence,
                )
            )

        clusters.sort(key=lambda c: c.confidence, reverse=True)
        return clusters
