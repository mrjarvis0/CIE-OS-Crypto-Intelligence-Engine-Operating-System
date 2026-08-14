"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.evidence.provenance

Purpose:
    Track source, lineage, and hash provenance of evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..schemas.evidence import EvidenceArtifact, EvidenceSource
from ..utils.helpers import now_utc


class ProvenanceRecord:
    """
    A record of where, when, and by whom evidence originated.

    Maintains a chain-of-custody lineage so each transformation applied
    to the artifact is documented, enabling forensic auditability.
    """

    def __init__(
        self,
        artifact: EvidenceArtifact,
        collector: str = "unknown",
    ) -> None:
        self.artifact = artifact
        self.collector = collector
        self.recorded_at = now_utc()
        self.lineage: list[str] = [
            f"{collector}@{self.recorded_at.isoformat()}"
        ]

    def add_event(self, action: str, by: str = "unknown") -> None:
        """
        Append a chain-of-custody event to the lineage.
        """
        self.lineage.append(f"{action}@{by}@{now_utc().isoformat()}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "collector": self.collector,
            "recorded_at": self.recorded_at.isoformat(),
            "lineage": list(self.lineage),
            "artifact": self.artifact.to_dict(),
        }


class ProvenanceTracker:
    """
    Records the source and lineage of every evidence artifact.
    """

    def __init__(self) -> None:
        self._records: dict[str, ProvenanceRecord] = {}

    def record(
        self,
        artifact: EvidenceArtifact,
        collector: str = "unknown",
    ) -> ProvenanceRecord:
        """
        Record provenance for an artifact keyed by its content hash.
        """
        record = ProvenanceRecord(artifact, collector)
        key = artifact.content_hash or artifact.claim
        self._records[key] = record
        return record

    def get(self, key: str) -> ProvenanceRecord | None:
        """
        Return the provenance record for a key.
        """
        return self._records.get(key)

    def lineage(self, key: str) -> list[str]:
        """
        Return the recorded lineage for a key.
        """
        record = self._records.get(key)
        return list(record.lineage) if record else []

    def __len__(self) -> int:
        return len(self._records)
