"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.correlation.entity_linking

Purpose:
    Link multiple identifiers to a unified entity.
"""

from __future__ import annotations

from typing import Any

from ..schemas.entity import Entity
from .correlator import Correlation


class EntityLinker:
    """
    Links identifiers (address, ENS, domain, email) to one entity.
    """

    def link(self, subjects: list[dict[str, Any]]) -> list[Correlation]:
        correlations: list[Correlation] = []
        for subject in subjects:
            address = subject.get("address")
            identifiers = subject.get("identifiers", {})
            for key, value in identifiers.items():
                if not address or not value:
                    continue
                correlations.append(
                    Correlation(
                        left=str(address),
                        right=str(value),
                        relation=f"entity_{key}",
                        confidence=0.8,
                    )
                )
        return correlations

    def resolve(self, subject: dict[str, Any]) -> Entity:
        """
        Build a unified entity from a subject's identifiers.
        """
        identifiers = dict(subject.get("identifiers", {}))
        return Entity(
            entity_id=subject.get("entity_id", "entity-unknown"),
            primary_identifier=str(subject.get("address") or subject.get("name") or "unknown"),
            entity_type=subject.get("entity_type", "unknown"),
            identifiers=identifiers,
        )
