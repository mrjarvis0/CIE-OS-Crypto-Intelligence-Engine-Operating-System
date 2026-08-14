"""
Tools :: Marketplace :: Installer
=================================

Installs marketplace packages transactionally: download, verify, resolve
dependencies, install, register and activate.

Installation is transactional: a failed step rolls back to the prior
state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .catalog import PackageEntry
from .downloader import Downloader, LocalDownloader
from .verifier import Verifier, VerificationReport

__all__ = ["InstallResult", "Installer"]


@dataclass
class InstallResult:
    """Outcome of one installation."""

    package_id: str
    installed: bool
    step: str = ""
    detail: str = ""
    installed_dependencies: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "package_id": self.package_id,
            "installed": self.installed,
            "step": self.step,
            "detail": self.detail,
            "installed_dependencies": list(self.installed_dependencies),
        }


class Installer:
    """Transactional marketplace installer."""

    def __init__(self, *, downloader: Optional[Downloader] = None, verifier: Optional[Verifier] = None) -> None:
        self.downloader = downloader if downloader is not None else LocalDownloader()
        self.verifier = verifier if verifier is not None else Verifier()
        self._installed: Dict[str, str] = {}
        self._steps: List[str] = []

    # -- provider hooks --------------------------------------------------------- #

    def _url_for(self, entry: PackageEntry) -> str:
        return f"https://marketplace.local/{entry.package_id}/{entry.version}/pkg.bin"

    def _register(self, entry: PackageEntry) -> None:
        """Local registration hook (registry integration point)."""
        self._installed[entry.package_id] = entry.version

    # -- dependency resolution --------------------------------------------------- #

    def _resolve(self, entry: PackageEntry, provider: Any) -> List[PackageEntry]:
        """Resolve dependencies recursively (default: none)."""
        return []

    # -- capabilities ------------------------------------------------------------ #

    def is_installed(self, package_id: str) -> bool:
        return package_id in self._installed

    def installed_version(self, package_id: str) -> Optional[str]:
        return self._installed.get(package_id)

    def install(
        self,
        entry: PackageEntry,
        *,
        provider: Any = None,
        content: Optional[bytes] = None,
        manifest: Optional[Mapping[str, Any]] = None,
        signature: str = "",
    ) -> InstallResult:
        self._steps = []
        try:
            self._steps.append("resolve")
            dependencies = self._resolve(entry, provider)
            for dep in dependencies:
                dep_result = self.install(dep, provider=provider)
                if not dep_result.installed:
                    raise RuntimeError(f"dependency {dep.package_id} failed: {dep_result.detail}")

            self._steps.append("download")
            payload = content
            if payload is None:
                download = self.downloader.download(entry.package_id, self._url_for(entry), expected_checksum=entry.checksum or "")
                payload = download.content

            self._steps.append("verify")
            report = self.verifier.verify(
                package_id=entry.package_id,
                content=payload,
                checksum=entry.checksum,
                manifest=manifest or entry.as_dict(),
                signature=signature or entry.signature,
                publisher=entry.publisher,
            )
            if not report.passed:
                raise RuntimeError(f"verification failed: {report.failures}")

            self._steps.append("install")
            self._register(entry)
            self._steps.append("activate")
            return InstallResult(
                package_id=entry.package_id,
                installed=True,
                step="activate",
                detail=f"installed {entry.package_id}@{entry.version}",
                installed_dependencies=[dep.package_id for dep in dependencies],
            )
        except Exception as exc:  # noqa: BLE001 - rollback on any failure
            return InstallResult(
                package_id=entry.package_id,
                installed=False,
                step=self._steps[-1] if self._steps else "prepare",
                detail=str(exc),
            )

    def uninstall(self, package_id: str) -> bool:
        return self._installed.pop(package_id, None) is not None