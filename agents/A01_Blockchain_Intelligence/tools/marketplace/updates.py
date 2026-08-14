"""
Tools :: Marketplace :: Updates
===============================

Update discovery: version comparison (semver-ish), update notifications,
security advisories, auto-update policies and changelogs.

Integrates with the Lifecycle Manager.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .catalog import PackageEntry

__all__ = ["UpdateInfo", "UpdateManager", "compare_versions"]

_UPGRADE_POLICIES = ("never", "patch", "minor", "major", "always")


def _parts(version: str) -> tuple[int, int, int]:
    cleaned = version.split("-", 1)[0].split("+", 1)[0]
    numbers = cleaned.split(".")
    try:
        major = int(numbers[0]) if len(numbers) > 0 else 0
        minor = int(numbers[1]) if len(numbers) > 1 else 0
        patch = int(numbers[2]) if len(numbers) > 2 else 0
    except ValueError:
        return (0, 0, 0)
    return (major, minor, patch)


def compare_versions(left: str, right: str) -> int:
    """-1 / 0 / +1 comparing left against right."""
    a, b = _parts(left), _parts(right)
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


@dataclass
class UpdateInfo:
    """An available update for one package."""

    package_id: str
    current_version: str
    latest_version: str
    severity: str = "patch"
    changelog: str = ""
    advisory: str = ""

    @property
    def upgradable(self) -> bool:
        return compare_versions(self.current_version, self.latest_version) < 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "package_id": self.package_id,
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "severity": self.severity,
            "changelog": self.changelog,
            "advisory": self.advisory,
            "upgradable": self.upgradable,
        }


class UpdateManager:
    """Finds and filters package updates."""

    def __init__(self, *, upgrade_policy: str = "minor") -> None:
        if upgrade_policy not in _UPGRADE_POLICIES:
            raise ValueError(f"unknown upgrade policy {upgrade_policy!r}")
        self.upgrade_policy = upgrade_policy
        self._installed: Dict[str, str] = {}
        self._latest: Dict[str, str] = {}
        self._changelogs: Dict[str, str] = {}
        self._advisories: Dict[str, str] = {}

    # -- state ------------------------------------------------------------------- #

    def track(self, package_id: str, current_version: str, latest_version: str, *, changelog: str = "", advisory: str = "") -> None:
        self._installed[package_id] = current_version
        self._latest[package_id] = latest_version
        if changelog:
            self._changelogs[package_id] = changelog
        if advisory:
            self._advisories[package_id] = advisory

    def set_policy(self, policy: str) -> None:
        if policy not in _UPGRADE_POLICIES:
            raise ValueError(f"unknown upgrade policy {policy!r}")
        self.upgrade_policy = policy

    # -- queries ------------------------------------------------------------------- #

    def _within_policy(self, current: str, latest: str) -> bool:
        if self.upgrade_policy == "never":
            return False
        if self.upgrade_policy == "always":
            return compare_versions(current, latest) < 0
        major, minor, _ = _parts(current)
        l_major, l_minor, _ = _parts(latest)
        if self.upgrade_policy == "major":
            return compare_versions(current, latest) < 0
        if self.upgrade_policy == "minor":
            return l_major == major and compare_versions(current, latest) < 0
        if self.upgrade_policy == "patch":
            return l_major == major and l_minor == minor and compare_versions(current, latest) < 0
        return False

    def check(self, package_id: str) -> Optional[UpdateInfo]:
        current = self._installed.get(package_id)
        latest = self._latest.get(package_id)
        if not current or not latest:
            return None
        info = UpdateInfo(
            package_id=package_id,
            current_version=current,
            latest_version=latest,
            changelog=self._changelogs.get(package_id, ""),
            advisory=self._advisories.get(package_id, ""),
        )
        if not info.upgradable:
            return info
        return info

    def available_updates(self) -> List[UpdateInfo]:
        return [info for info in (self.check(pid) for pid in self._installed) if info and info.upgradable and self._within_policy(info.current_version, info.latest_version)]

    def security_advisories(self) -> List[UpdateInfo]:
        return [info for info in (self.check(pid) for pid in self._installed) if info and info.advisory]