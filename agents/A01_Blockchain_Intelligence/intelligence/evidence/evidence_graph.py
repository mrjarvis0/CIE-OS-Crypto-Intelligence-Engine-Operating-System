"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.evidence.evidence_graph

Purpose:
    Model relationships between evidence artifacts as a directed acyclic
    graph, and enforce the invariants that make an evidence chain defensible.

Invariants
----------
1. Acyclicity
    A cycle means a claim ultimately supports itself. Rejected on insert.
2. Leaf grounding
    Every path terminates in a direct observation or an external assertion.
    A chain that bottoms out in another inference proves nothing.
3. Correlation
    Artifacts sharing a common ancestor are not independent. Callers must
    collapse them before combining confidence, or five restatements of one
    provider's opinion become five confirmations.

See docs/intelligence/evidence-standard.md section 5.
"""

from __future__ import annotations

from ..schemas.evidence import EvidenceArtifact, EvidenceSource


class EvidenceCycleError(ValueError):
    """Raised when adding a link would make the evidence graph cyclic."""


#: Source categories that can legitimately terminate a chain. Protocol facts
#: and external assertions are where evidence bottoms out; INFERRED and AI are
#: derivations and must have parents of their own.
GROUNDING_SOURCES: frozenset[EvidenceSource] = frozenset(
    {
        EvidenceSource.ON_CHAIN,
        EvidenceSource.EXPLORER,
        EvidenceSource.MARKET,
        EvidenceSource.NEWS,
        EvidenceSource.SOCIAL,
        EvidenceSource.GITHUB,
        EvidenceSource.DOCUMENTATION,
        EvidenceSource.GOVERNMENT,
        EvidenceSource.ANALYST,
    }
)


def _key(artifact: EvidenceArtifact) -> str:
    """Stable identity for an artifact: its content hash, else its claim."""
    return artifact.content_hash or artifact.claim


class EvidenceGraph:
    """
    A directed acyclic graph of evidence artifacts.

    Edges point from a supporting artifact to the artifact it supports, so
    following edges backwards yields the ancestry of a conclusion.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, EvidenceArtifact] = {}
        self._edges: list[tuple[str, str, str]] = []
        #: target -> set of direct parents (sources supporting it)
        self._parents: dict[str, set[str]] = {}

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def add(self, artifact: EvidenceArtifact) -> str:
        """
        Register an artifact node. Returns its key.

        Any ``derivation`` recorded on the artifact is materialised as parent
        edges, so an artifact built with parents is wired into the graph
        without a separate ``link`` call.
        """
        key = _key(artifact)
        self._nodes[key] = artifact
        self._parents.setdefault(key, set())

        for parent in artifact.derivation:
            if parent == key:
                raise EvidenceCycleError(f"artifact {key!r} derives from itself")
            if self._creates_cycle(parent, key):
                raise EvidenceCycleError(
                    f"linking {parent!r} -> {key!r} would create a cycle"
                )
            self._parents[key].add(parent)
            self._edges.append((parent, key, "supports"))

        return key

    def link(
        self,
        source: EvidenceArtifact,
        target: EvidenceArtifact,
        relation: str = "supports",
    ) -> None:
        """
        Add a directed relation from ``source`` to ``target``.

        Raises
        ------
        EvidenceCycleError
            If the edge would make the graph cyclic.
        """
        src = _key(source)
        tgt = _key(target)

        if src == tgt:
            raise EvidenceCycleError(f"artifact {src!r} cannot support itself")
        if self._creates_cycle(src, tgt):
            raise EvidenceCycleError(
                f"linking {src!r} -> {tgt!r} would create a cycle"
            )

        self.add(source)
        self.add(target)
        self._edges.append((src, tgt, relation))
        if relation == "supports":
            self._parents.setdefault(tgt, set()).add(src)

    def _creates_cycle(self, source: str, target: str) -> bool:
        """
        True if adding source -> target would close a loop.

        The edge makes ``source`` an ancestor of ``target``. That closes a
        loop precisely when ``target`` is *already* an ancestor of ``source``,
        giving target -> ... -> source -> target.
        """
        return source == target or target in self.ancestors(source)

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    def ancestors(self, key: str) -> set[str]:
        """
        Every artifact key transitively supporting ``key``.

        Iterative rather than recursive so a deep chain cannot exhaust the
        stack, and ``seen`` makes it safe against pre-existing cycles.
        """
        seen: set[str] = set()
        stack = list(self._parents.get(key, ()))

        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(self._parents.get(current, ()))

        return seen

    def roots(self, key: str) -> set[str]:
        """
        The leaf artifacts a conclusion ultimately rests on.

        A node with no parents is a root. If ``key`` itself has no parents it
        is its own root.
        """
        ancestry = self.ancestors(key)
        if not ancestry:
            return {key}
        return {a for a in ancestry if not self._parents.get(a)}

    def parents(self, key: str) -> set[str]:
        """Direct parents of ``key``."""
        return set(self._parents.get(key, ()))

    # ------------------------------------------------------------------
    # Invariants
    # ------------------------------------------------------------------

    def is_grounded(self, key: str) -> bool:
        """
        True when every path from ``key`` terminates in a grounding source.

        An inference whose chain bottoms out in another inference has no
        factual foundation and must not be published.
        """
        return not self.ungrounded_roots(key)

    def ungrounded_roots(self, key: str) -> set[str]:
        """
        Root artifacts that are not acceptable terminators.

        Returned rather than a bare boolean so the caller can report *which*
        part of the chain is unfounded.
        """
        bad: set[str] = set()

        for root in self.roots(key):
            artifact = self._nodes.get(root)
            if artifact is None:
                bad.add(root)
                continue
            try:
                source = EvidenceSource(artifact.source_type)
            except ValueError:
                bad.add(root)
                continue
            if source not in GROUNDING_SOURCES:
                bad.add(root)

        return bad

    def correlation_groups(self, keys: list[str]) -> list[set[str]]:
        """
        Partition ``keys`` into groups that share a common ancestor.

        Artifacts in the same group are not independent evidence. Combining
        them as if they were is how a single 0.5-confidence guess becomes a
        0.99-confidence "fact".

        Independent artifacts each come back as their own single-member group.
        """
        remaining = list(dict.fromkeys(keys))
        lineage = {k: self.ancestors(k) | {k} for k in remaining}
        groups: list[set[str]] = []

        while remaining:
            current = remaining.pop(0)
            group = {current}
            shared = set(lineage[current])

            merged = True
            while merged:
                merged = False
                for other in list(remaining):
                    if lineage[other] & shared:
                        group.add(other)
                        shared |= lineage[other]
                        remaining.remove(other)
                        merged = True

            groups.append(group)

        return groups

    def validate(self) -> list[str]:
        """
        Check every registered conclusion for grounding.

        Acyclicity is enforced on insert, so it needs no check here.
        """
        errors: list[str] = []
        for key, artifact in self._nodes.items():
            if artifact.is_leaf():
                continue
            for bad in sorted(self.ungrounded_roots(key)):
                errors.append(f"{key!r} rests on ungrounded root {bad!r}")
        return errors

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def get(self, key: str) -> EvidenceArtifact | None:
        """Return the artifact registered under ``key``, if any."""
        return self._nodes.get(key)

    def nodes(self) -> list[EvidenceArtifact]:
        """Return all registered artifacts."""
        return list(self._nodes.values())

    def edges(self) -> list[tuple[str, str, str]]:
        """Return all registered relations."""
        return list(self._edges)

    def __len__(self) -> int:
        return len(self._nodes)
