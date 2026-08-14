"""
Tools :: Core :: Version
========================

Semantic Versioning (SemVer) helpers for the Tools platform.

Versions follow the ``major.minor.patch[-prerelease][+build]`` grammar.
Comparison follows SemVer ordering: release > prerelease, build metadata is
ignored for ordering. Used by the dependency resolver, lifecycle updater,
marketplace updates and the registry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Union

__all__ = [
    "Version",
    "parse_version",
    "version",
    "is_compatible",
    "best_compatible",
    "version_key",
]

_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)"
    r"\.(?P<minor>0|[1-9]\d*)"
    r"\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.\-]+))?"
    r"(?:\+(?P<build>[0-9A-Za-z.\-]+))?$"
)


@dataclass(frozen=True, order=False)
class Version:
    """A parsed semantic version."""

    major: int
    minor: int = 0
    patch: int = 0
    prerelease: str = ""
    build: str = ""

    @property
    def release(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __str__(self) -> str:
        text = self.release
        if self.prerelease:
            text += f"-{self.prerelease}"
        if self.build:
            text += f"+{self.build}"
        return text

    # -- ordering ---------------------------------------------------------- #

    def _cmp_key(self) -> tuple:
        """Uniform key: release ranks above any prerelease of the same version."""
        if not self.prerelease:
            return (self.major, self.minor, self.patch, (1,))
        return (self.major, self.minor, self.patch, (0, self._prerelease_key()))

    def _prerelease_key(self) -> tuple:
        parts: list = []
        for token in self.prerelease.split("."):
            if token.isdigit():
                parts.append((0, int(token)))
            else:
                parts.append((1, token))
        return tuple(parts)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._cmp_key() < other._cmp_key()

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._cmp_key() <= other._cmp_key()

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._cmp_key() > other._cmp_key()

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._cmp_key() >= other._cmp_key()

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            try:
                other = parse_version(other)
            except ValueError:
                return NotImplemented
        if not isinstance(other, Version):
            return NotImplemented
        return self._cmp_key() == other._cmp_key()

    def __hash__(self) -> int:
        return hash((self.major, self.minor, self.patch, self.prerelease))

    def compatible_with(self, constraint: str) -> bool:
        """True when this version satisfies a SemVer constraint."""
        return _satisfies(self, constraint)


def version_key(v: Union[str, Version]) -> tuple:
    """Ordering key for a version (enables ``sorted(versions, key=version_key)``)."""
    return parse_version(v)._cmp_key()


def parse_version(value: object) -> Version:
    """Parse a version string or Version instance; raises ValueError."""
    if isinstance(value, Version):
        return value
    text = str(value).strip()
    match = _PATTERN.fullmatch(text)
    if not match:
        raise ValueError(f"invalid semantic version: {text!r}")
    return Version(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
        prerelease=match.group("prerelease") or "",
        build=match.group("build") or "",
    )


def version(major: int, minor: int = 0, patch: int = 0, **kwargs: object) -> str:
    """Build a version string from parts (accepts ``prerelease``/``build``)."""
    extra = {k: v for k, v in kwargs.items() if k in ("prerelease", "build")}
    return str(Version(major, minor, patch, **{k: str(v) for k, v in extra.items()}))


def _satisfies(v: Version, constraint: str) -> bool:
    constraint = constraint.strip()
    if constraint in ("*", "", "latest"):
        return True
    if constraint.startswith("^"):
        upper = parse_version(constraint[1:])
        return Version(upper.major, 0, 0) <= v < Version(upper.major + 1, 0, 0)
    if constraint.startswith("~"):
        base = parse_version(constraint[1:])
        return base <= v < Version(base.major, base.minor + 1, 0)
    if constraint.startswith(">="):
        return v >= parse_version(constraint[2:])
    if constraint.startswith("<="):
        return v <= parse_version(constraint[2:])
    if constraint.startswith(">"):
        return v > parse_version(constraint[1:])
    if constraint.startswith("<"):
        return v < parse_version(constraint[1:])
    try:
        target = parse_version(constraint)
        return v == target
    except ValueError:
        raise ValueError(f"unsupported version constraint: {constraint!r}") from None


def is_compatible(current: object, constraint: str) -> bool:
    """Return True when ``current`` satisfies ``constraint``."""
    return parse_version(current).compatible_with(constraint)


def best_compatible(versions: Sequence[object], constraint: str) -> Optional[Version]:
    """Highest version among ``versions`` satisfying ``constraint``."""
    parsed = sorted((parse_version(v) for v in versions), reverse=True)
    for candidate in parsed:
        if candidate.compatible_with(constraint):
            return candidate
    return None