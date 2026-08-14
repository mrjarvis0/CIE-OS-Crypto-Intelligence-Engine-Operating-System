"""
Tools :: Governance :: Provenance
=================================

Evidence and lineage tracking: origin, source, build, deployment,
dependency lineage and artifact traceability.

Supports forensic investigations via immutable, time-stamped records.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["ProvenanceRecord", "ProvenanceTracker"]


@dataclass
class ProvenanceRecord:
    """One lineage fact about an artifact."""

    artifact_id: str
    source: str
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "artifact_id": self.artifact_id,
            "source": self.source,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }


class ProvenanceTracker:
    """Append-only lineage store keyed by artifact."""

    def __init__(self) -> None:
        self._records: List[ProvenanceRecord] = []

    def record(self, artifact_id: str, source: str, **metadata: Any) -> ProvenanceRecord:
        item = ProvenanceRecord(artifact_id=artifact_id, source=source, metadata=dict(metadata))
        self._records.append(item)
        return item

    def record_origin(self, artifact_id: str, *, package: str, version: str, publisher: str) -> ProvenanceRecord:
        return self.record(artifact_id, "origin", package=package, version=version, publisher=publisher)

    def record_build(self, artifact_id: str, *, builder: str, build_id: str, compiler: str = "") -> ProvenanceRecord:
        return self.record(artifact_id, "build", builder=builder, build_id=build_id, compiler=compiler)

    def record_dependency(self, artifact_id: str, dependency_id: str, *, version: str = "") -> ProvenanceRecord:
        return self.record(artifact_id, "dependency", dependency_id=dependency_id, version=version)

    def lineage(self, artifact_id: str) -> List[ProvenanceRecord]:
        return [record for record in self._records if record.artifact_id == artifact_id]

    def sources(self, artifact_id: str) -> List[str]:
        return [record.source for record in self.lineage(artifact_id)]

    def first(self, artifact_id: str) -> Optional[ProvenanceRecord]:
        records = self.lineage(artifact_id)
        return records[0] if records else None

    def all(self) -> List[ProvenanceRecord]:
        return list(self._records)