"""
Tools :: Marketplace :: Publisher
=================================

Publishes packages: manifest validation, metadata generation, version
publishing, publisher verification and release notes.

Supports public and private repositories.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..governance.signing import SigningKey, sign_payload
from .catalog import PackageEntry

__all__ = ["PublishResult", "Publisher"]

_REQUIRED_MANIFEST_FIELDS = ("package_id", "name", "version")


@dataclass
class PublishResult:
    """Outcome of a publish operation."""

    package_id: str
    published: bool
    version: str = ""
    detail: str = ""
    signature: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "package_id": self.package_id,
            "published": self.published,
            "version": self.version,
            "detail": self.detail,
            "signature": self.signature,
        }


class Publisher:
    """Validating publisher with manifest signing."""

    def __init__(self, *, key: Optional[SigningKey] = None, publisher_name: str = "") -> None:
        self.key = key
        self.publisher_name = publisher_name
        self._published: Dict[str, PackageEntry] = {}

    # -- provider hook ---------------------------------------------------------- #

    def _store(self, entry: PackageEntry, signature: str) -> None:
        self._published[entry.package_id] = entry

    # -- capabilities ----------------------------------------------------------- #

    def validate_manifest(self, manifest: Mapping[str, Any]) -> List[str]:
        """Return missing required fields (empty = valid)."""
        return [field for field in _REQUIRED_MANIFEST_FIELDS if field not in manifest]

    def publish(
        self,
        entry: PackageEntry,
        *,
        manifest: Optional[Mapping[str, Any]] = None,
        release_notes: str = "",
    ) -> PublishResult:
        missing = self.validate_manifest(manifest or entry.as_dict())
        if missing:
            return PublishResult(package_id=entry.package_id, published=False, detail=f"manifest missing {missing}")

        signature = ""
        if self.key is not None:
            signature = sign_payload(self.key, dict(manifest or entry.as_dict()))

        entry.signature = signature
        if release_notes:
            entry.metadata_release_notes = release_notes  # type: ignore[attr-defined]

        self._store(entry, signature)
        return PublishResult(
            package_id=entry.package_id,
            published=True,
            version=entry.version,
            detail=f"published {entry.package_id}@{entry.version}",
            signature=signature,
        )

    def published(self) -> List[PackageEntry]:
        return list(self._published.values())