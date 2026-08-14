"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.schemas.entity

Purpose:
    Canonical entity data models.

    An Entity is a resolved identity (wallet, organization, person,
    exchange, protocol...). Entity identifiers and attributes are used
    by attribution and entity-resolution logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class EntityType(StrEnum):
    """
    High-level category of an entity.
    """

    WALLET = "wallet"
    CONTRACT = "contract"
    EXCHANGE = "exchange"
    ORGANIZATION = "organization"
    PERSON = "person"
    PROTOCOL = "protocol"
    DAO = "dao"
    BRIDGE = "bridge"
    MIXER = "mixer"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Entity:
    """
    A resolved, attributed identity.

    Attribution is treated as a research problem: the entity records
    not just a name but the confidence of the attribution and the
    alternative explanations that were considered and rejected. This
    keeps the deliverable a confidence-scored hypothesis rather than
    a bare identification.

    Fields:
        entity_id            Stable internal identifier.
        primary_identifier   Canonical public identifier (e.g. address).
        entity_type          High-level category.
        identifiers          Alternate identifiers keyed by namespace.
        labels               Assigned labels (exchange, mixer, ...).
        claim_tier           Highest evidence tier satisfied for this
                             attribution (structural/attribution/operator).
        confidence           Stated confidence in the attribution.
        alternatives         Alternative explanations considered.
        attributes           Domain-specific attributes.
    """

    entity_id: str
    primary_identifier: str
    entity_type: EntityType | str = EntityType.UNKNOWN
    identifiers: dict[str, str] = field(default_factory=dict)
    labels: tuple[str, ...] = ()
    claim_tier: str = "attribution"
    confidence: float = 0.0
    alternatives: tuple[str, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)
    resolved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "primary_identifier": self.primary_identifier,
            "entity_type": str(self.entity_type),
            "identifiers": self.identifiers,
            "labels": list(self.labels),
            "claim_tier": self.claim_tier,
            "confidence": self.confidence,
            "alternatives": list(self.alternatives),
            "attributes": self.attributes,
            "resolved_at": self.resolved_at.isoformat(),
            "metadata": self.metadata,
        }
