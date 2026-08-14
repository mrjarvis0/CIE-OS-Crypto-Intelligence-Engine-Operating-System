"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.attribution.identity

Purpose:
    Identity resolution for subjects.
"""

from __future__ import annotations

from typing import Any

from ..schemas.entity import Entity


class IdentityResolver:
    """
    Resolves a subject's raw identifiers into a canonical Entity.
    """

    def resolve(self, subject: dict[str, Any]) -> Entity:
        """
        Build an Entity from a subject dict.
        """
        identifiers = dict(subject.get("identifiers", {}))
        raw_labels = subject.get("labels", [])
        if isinstance(raw_labels, str):
            raw_labels = [raw_labels]
        elif not isinstance(raw_labels, (list, tuple, set)):
            raw_labels = []
        return Entity(
            entity_id=subject.get("entity_id", "entity-unknown"),
            primary_identifier=str(subject.get("address") or subject.get("name") or "unknown"),
            entity_type=subject.get("entity_type", "unknown"),
            identifiers=identifiers,
            labels=tuple(str(l) for l in raw_labels),
        )
