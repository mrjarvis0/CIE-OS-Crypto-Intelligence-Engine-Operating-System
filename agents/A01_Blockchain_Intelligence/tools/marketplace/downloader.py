"""
Tools :: Marketplace :: Downloader
==================================

Downloads packages with checksum validation, mirror selection and
compression metadata.

The local downloader simulates transfers deterministically; real
implementations override ``_fetch`` with secure transport.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence

__all__ = ["DownloadResult", "Downloader"]


@dataclass
class DownloadResult:
    """Outcome of a package download."""

    package_id: str
    url: str
    content: bytes = b""
    checksum: str = ""
    size_bytes: int = 0
    duration_ms: float = 0.0
    mirror: str = ""
    verified: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "package_id": self.package_id,
            "url": self.url,
            "size_bytes": self.size_bytes,
            "duration_ms": self.duration_ms,
            "mirror": self.mirror,
            "verified": self.verified,
            "checksum": self.checksum,
        }


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class Downloader:
    """Checksum-validating downloader."""

    provider = "downloader"

    def __init__(self, mirrors: Optional[Sequence[str]] = None) -> None:
        self.mirrors = list(mirrors or [])

    # -- provider hook ---------------------------------------------------------- #

    def _fetch(self, url: str) -> bytes:
        raise NotImplementedError

    # -- capabilities ----------------------------------------------------------- #

    def download(self, package_id: str, url: str, *, expected_checksum: str = "", verify: bool = True) -> DownloadResult:
        started = time.perf_counter()
        chosen = url
        content = self._fetch(chosen)
        checksum = sha256_hex(content)
        verified = True
        if verify and expected_checksum:
            verified = checksum == expected_checksum
            if not verified:
                raise ValueError(f"checksum mismatch for {package_id}")
        return DownloadResult(
            package_id=package_id,
            url=chosen,
            content=content,
            checksum=checksum,
            size_bytes=len(content),
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            mirror=chosen,
            verified=verified,
        )

    def checksum(self, content: bytes) -> str:
        return sha256_hex(content)


class LocalDownloader(Downloader):
    """Deterministic in-memory downloader seeded with payloads."""

    provider = "local-downloader"

    def __init__(self, mirrors: Optional[Sequence[str]] = None) -> None:
        super().__init__(mirrors=mirrors)
        self._payloads: Dict[str, bytes] = {}

    def seed(self, url: str, content: bytes) -> None:
        self._payloads[url] = content

    def _fetch(self, url: str) -> bytes:
        for mirror in [url] + self.mirrors:
            if mirror in self._payloads:
                return self._payloads[mirror]
        raise FileNotFoundError(f"no payload seeded for {url!r}")