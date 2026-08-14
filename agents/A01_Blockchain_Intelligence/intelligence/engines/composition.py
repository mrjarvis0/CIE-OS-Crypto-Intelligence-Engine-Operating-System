"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.engines.composition

Purpose:
    Build an analyzer subject by running skills against stored history, so an
    investigation reads from A01's record instead of from a hand-written dict.

Design goals:
    - Skills combined here; a skill still never calls a skill
    - Coverage merged and carried into the subject, not discarded
    - A conflicting field reported, never silently overwritten
    - One skill failing degrades the subject rather than the investigation
    - The composer issues no query of its own; skills do the reading

Notes:
    This is the component the read side was missing. The detectors were already
    correct and already registered, but their subject arrived from the caller --
    so A01 could analyse only what a human had already described to it, and the
    stored history it had spent five phases capturing went unread.

    Merging is where the honesty of the layer below either survives or is lost.
    Each skill states what its window can support; the composed subject has to
    carry the *weakest* of those statements, because a subject assembled from one
    deep window and one shallow one is only as trustworthy as the shallow one. So
    :attr:`Composition.coverage` reduces by minimum, and any skill that could not
    license an absence claim disables it for the whole subject.

    Conflicts are recorded rather than resolved. Two skills disagreeing about a
    field is a fact about the skills, and last-write-wins would hide it behind a
    plausible value. In practice the only shared field is ``address``, which
    every skill takes from the same request -- so a conflict here means something
    is genuinely wrong.

    A skill that raises is contained. The pipeline already isolates stages; this
    isolates within a stage, so a broken flow skill does not cost the wallet
    profile and the whale population that were gathered successfully.

    The composer holds the repository but never queries it. Passing it through
    to the skills keeps the layer rule intact -- ``intelligence/`` decides what
    data means and does not fetch it -- and it keeps every SQL statement inside
    a repository, called from the one layer that is allowed to read.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any

from database.analytics import SqliteAnalyticsRepository
from schemas.address import Address, AddressError
from skills.base import Coverage, SkillRequest, SkillResult
from skills.registry import SkillRegistry, default_registry

logger = logging.getLogger("a01.intelligence.engines")


@dataclass(frozen=True, slots=True)
class Composition:
    """
    A subject assembled from skill results, with the caveats intact.

    ``subject`` is what the analyzers consume. Everything else exists so a
    consumer can tell how much the subject is worth: which skills contributed,
    which declined, what the combined window supports, and what must not be
    inferred from it.
    """

    subject: dict[str, Any]
    results: tuple[SkillResult, ...] = ()
    coverage: Coverage | None = None
    contributed: tuple[str, ...] = ()
    declined: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @property
    def supports_absence(self) -> bool:
        """
        Whether any negative conclusion is licensed by the composed window.

        False means the investigation may report what it found and must not
        report what it did not find.
        """
        return self.coverage is not None and self.coverage.supports_absence

    @property
    def usable(self) -> bool:
        return bool(self.contributed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "contributed": list(self.contributed),
            "declined": list(self.declined),
            "failed": list(self.failed),
            "conflicts": list(self.conflicts),
            "supports_absence": self.supports_absence,
            "coverage": self.coverage.as_dict() if self.coverage else None,
            "limitations": list(self.limitations),
        }


class SubjectComposer:
    """
    Runs the skills layer and merges its output into one analyzer subject.

    Holds the registry and nothing else. The repository arrives per call so one
    composer can serve several databases -- a live file and a fixture -- without
    reconstruction.
    """

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self._registry = registry if registry is not None else default_registry()

    @property
    def registry(self) -> SkillRegistry:
        return self._registry

    def compose(
        self,
        analytics: SqliteAnalyticsRepository,
        *,
        chain: str,
        address: str | None = None,
        from_height: int | None = None,
        to_height: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> Composition:
        """
        Build a subject for one investigation.

        A malformed address is refused here rather than passed through. Handing
        the skills layer an unparseable address would have every one of them
        return "not found", which reads as an address with no history instead of
        as a typo.
        """
        parsed: Address | None = None
        if address:
            try:
                parsed = Address.parse(address, chain)
            except AddressError as exc:
                return Composition(
                    subject={"chain": chain, "address": address},
                    limitations=(f"address rejected: {exc}",),
                )

        request = SkillRequest(
            chain=chain,
            address=parsed,
            from_height=from_height,
            to_height=to_height,
            options=options or {},
        )

        subject: dict[str, Any] = {"chain": chain}
        if parsed is not None:
            subject["address"] = parsed.value

        results: list[SkillResult] = []
        contributed: list[str] = []
        declined: list[str] = []
        failed: list[str] = []
        conflicts: list[str] = []
        limitations: list[str] = []
        coverages: list[Coverage] = []

        for entry in self._registry:
            skill = entry.skill
            try:
                result = skill.run(request, analytics)
            except Exception as exc:  # noqa: BLE001 - skill boundary
                logger.warning("skill %s failed: %s", skill.name, exc)
                failed.append(skill.name)
                continue

            results.append(result)
            coverages.append(result.coverage)

            if result.coverage.limitation:
                limitations.append(f"{skill.name}: {result.coverage.limitation}")
            if entry.bounded_by:
                limitations.append(f"{skill.name}: {entry.bounded_by}")

            if not result.usable:
                declined.append(skill.name)
                continue

            for key, value in result.subject.items():
                existing = subject.get(key)
                if key in subject and existing != value:
                    # Recorded, not resolved. Overwriting would hide a genuine
                    # disagreement behind a plausible value.
                    conflicts.append(
                        f"{skill.name} set {key}={value!r}, already {existing!r}"
                    )
                    continue
                subject[key] = value

            contributed.append(skill.name)

        coverage = self._weakest(coverages)
        if coverage is not None:
            # Carried in the subject so the analyzers and the report stage can
            # see it. Without this the detectors would apply their own
            # "determinable" logic to fields whose thinness they cannot detect.
            subject["coverage"] = coverage.as_dict()
            subject["absence_meaningful"] = coverage.supports_absence

        return Composition(
            subject=subject,
            results=tuple(results),
            coverage=coverage,
            contributed=tuple(contributed),
            declined=tuple(declined),
            failed=tuple(failed),
            conflicts=tuple(conflicts),
            limitations=tuple(dict.fromkeys(limitations)),
        )

    @staticmethod
    def _weakest(coverages: list[Coverage]) -> Coverage | None:
        """
        The least capable coverage among the contributors.

        Reduced by minimum because a subject is only as trustworthy as its
        weakest input. Taking the best would let one deep window license
        absence claims about a field that came from a shallow one.
        """
        if not coverages:
            return None
        return min(coverages, key=lambda c: (c.supports_absence, c.blocks))

    def __repr__(self) -> str:
        return f"SubjectComposer(skills={len(self._registry)})"


__all__ = ["Composition", "SubjectComposer"]
