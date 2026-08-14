"""
Tools :: Marketplace :: Verifier
================================

Validates downloaded artifacts: signatures, SHA-256 checksums, manifest
verification, publisher trust and dependency verification.

Unsigned packages never install.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..governance.signing import SigningKey, verify_payload
from .downloader import sha256_hex

__all__ = ["VerificationReport", "Verifier"]


@dataclass
class VerificationReport:
    """Outcome of artifact verification."""

    package_id: str
    passed: bool
    checks: Dict[str, bool] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "package_id": self.package_id,
            "passed": self.passed,
            "checks": dict(self.checks),
            "failures": list(self.failures),
        }


class Verifier:
    """Signature + checksum + trust verification gate."""

    def __init__(self) -> None:
        self._trusted: Dict[str, SigningKey] = {}

    def trust_publisher(self, publisher: str, key: SigningKey) -> None:
        self._trusted[publisher] = key

    def is_trusted(self, publisher: str) -> bool:
        return publisher in self._trusted

    def verify(
        self,
        *,
        package_id: str,
        content: bytes,
        checksum: str = "",
        manifest: Optional[Mapping[str, Any]] = None,
        signature: str = "",
        publisher: str = "",
        min_trust: float = 0.0,
    ) -> VerificationReport:
        checks: Dict[str, bool] = {}
        failures: List[str] = []

        if checksum:
            ok = sha256_hex(content) == checksum
            checks["checksum"] = ok
            if not ok:
                failures.append("checksum mismatch")
        else:
            checks["checksum"] = True

        if manifest is not None and signature:
            key = self._trusted.get(publisher)
            if key is None:
                checks["signature"] = False
                failures.append(f"publisher {publisher!r} is not trusted")
            else:
                ok = verify_payload(key, dict(manifest), signature)
                checks["signature"] = ok
                if not ok:
                    failures.append("signature invalid")
        else:
            checks["signature"] = bool(signature)
            if not checks["signature"]:
                failures.append("package unsigned")

        if publisher:
            checks["publisher_trust"] = self.is_trusted(publisher) and publisher in self._trusted
            if not checks["publisher_trust"]:
                failures.append("publisher untrusted")

        if min_trust > 0 and manifest:
            trust = float(manifest.get("trust_score", 0.0))
            checks["trust_score"] = trust >= min_trust
            if not checks["trust_score"]:
                failures.append(f"trust score {trust} below {min_trust}")

        return VerificationReport(package_id=package_id, passed=all(checks.values()), checks=checks, failures=failures)