"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.dotenv

Purpose:
    Load a ``.env`` file into the process environment, so provider credentials
    reach the code that reads them.

Design goals:
    - Real environment always wins; a file never overrides an export
    - Search order explicit and reported, never guessed at by the caller
    - Values never logged, only variable names
    - Dependency-free; no parsing library on the credential path
    - Idempotent, and safe to call from every entry point

Notes:
    This module exists because of a gap that made every keyed provider
    unreachable without anything appearing to be wrong.

    ``blockchain/rpc/providers/keys.py`` resolves credentials from
    ``os.environ``, re-read on every call so a key activates a provider without
    a restart. ``config/settings.py`` separately reads a ``.env`` file through
    pydantic-settings. Those two never met: pydantic loads the file into a
    *settings object*, not into the process environment, so a correctly written
    ``.env`` full of API keys activated nothing. ``configured_providers()``
    returned empty, A01 ran on free endpoints, and no error was raised anywhere
    — the system simply behaved as though no keys existed.

    **Precedence is real environment first.** A variable already exported wins
    over the file, always. The alternative — file overrides environment — makes
    a stale checked-out ``.env`` silently defeat a deliberately exported
    credential, and the operator has no way to see which value is in play.

    **Values are never logged.** Only variable names appear in output, because
    A01 writes logs to disk and renders diagnostics into reports, and a key that
    reaches either is a key that has to be rotated.
"""

from __future__ import annotations

import logging
import os

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Iterable

logger = logging.getLogger(__name__)

#: Filenames tried in each candidate directory, most specific first.
ENV_FILENAMES: Final[tuple[str, ...]] = (".env.local", ".env")

#: How far up from the agent directory to look. Three levels covers the agent
#: itself, an ``agents/`` parent, and the repository root above it -- which is
#: the layout CIE-OS uses and the layout a standalone checkout uses.
SEARCH_DEPTH: Final[int] = 3


@dataclass(frozen=True, slots=True)
class DotenvResult:
    """
    What loading found and applied.

    ``names`` carries variable names and never values, so this is safe to log,
    return over an interface, and render into a diagnostic.
    """

    path: Path | None = None
    names: tuple[str, ...] = ()
    #: Present in the file but already set in the environment, so left alone.
    skipped: tuple[str, ...] = field(default_factory=tuple)
    searched: tuple[Path, ...] = field(default_factory=tuple)

    @property
    def loaded(self) -> bool:
        return self.path is not None

    @property
    def applied(self) -> int:
        return len(self.names)

    def as_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path) if self.path else None,
            "applied": self.applied,
            "names": list(self.names),
            "skipped": list(self.skipped),
            "searched": [str(p) for p in self.searched],
        }


def candidate_paths(start: Path | None = None) -> tuple[Path, ...]:
    """
    Where a ``.env`` might live, nearest first.

    Walking upward rather than hardcoding a root because the agent is checked
    out at different depths in different layouts, and a fixed
    ``parents[3]`` silently resolves to a drive root when the tree is one level
    shallower than expected -- which is exactly how this went unnoticed.
    """
    base = (start or Path(__file__).resolve().parent.parent).resolve()

    # Bounded by the tree's actual depth, not by the assumed one. A checkout
    # sitting nearer the drive root has fewer parents than the CIE-OS layout,
    # and walking a fixed number of levels off the end is how a path helper
    # ends up either raising or silently resolving to `F:\`.
    directories = [base, *base.parents[:SEARCH_DEPTH]]

    return tuple(
        directory / name for directory in directories for name in ENV_FILENAMES
    )


def parse(text: str) -> dict[str, str]:
    """
    Read ``KEY=value`` pairs.

    Deliberately small. Quotes are stripped and ``export`` prefixes tolerated
    because both appear in files people actually write; interpolation and
    multi-line values are not supported, and a line that is not a simple
    assignment is skipped rather than guessed at.
    """
    values: dict[str, str] = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()

        name, _, value = line.partition("=")
        name = name.strip()
        if not name or not name.replace("_", "").isalnum():
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]

        values[name] = value

    return values


#: What the first load in this process did. Cached because loading twice
#: reports "0 applied, N already set" the second time -- technically true and
#: actively misleading, since the caller reading it wants to know what the
#: process is running with, not what the redundant call found.
_LOADED: DotenvResult | None = None


def load(
    start: Path | None = None,
    *,
    override: bool = False,
    environ: dict[str, str] | None = None,
    force: bool = False,
) -> DotenvResult:
    """
    Load the nearest ``.env`` into the environment, once per process.

    Repeat calls return the first result rather than re-reading. Every entry
    point calls this, and a second pass would report nothing applied because
    the first pass had already set everything -- which reads as "your key file
    did nothing".

    Returns without applying anything when no file is found -- an absent
    ``.env`` is the normal state for a deployment that exports its variables,
    not an error.

    ``override`` exists for tests and is false everywhere else. A file that
    could overwrite an exported credential would let a stale checked-out
    ``.env`` defeat a deliberate export, invisibly.
    """
    global _LOADED

    if _LOADED is not None and not force and environ is None:
        return _LOADED

    target = environ if environ is not None else os.environ
    searched = candidate_paths(start)

    for path in searched:
        if not path.is_file():
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("cannot read %s: %s", path, exc)
            continue

        applied: list[str] = []
        skipped: list[str] = []
        for name, value in parse(text).items():
            if not override and name in target:
                skipped.append(name)
                continue
            target[name] = value
            applied.append(name)

        if applied or skipped:
            # Names only. A value here would reach the log file and the
            # diagnostics, and a logged key is a rotated key.
            logger.info(
                "loaded %d variable(s) from %s (%d already set)",
                len(applied),
                path,
                len(skipped),
            )

        result = DotenvResult(
            path=path,
            names=tuple(applied),
            skipped=tuple(skipped),
            searched=searched,
        )
        if environ is None:
            _LOADED = result
        return result

    logger.debug("no .env found in %d candidate location(s)", len(searched))
    result = DotenvResult(searched=searched)
    if environ is None:
        _LOADED = result
    return result


def reset() -> None:
    """Forget the cached load. For tests; a running agent never calls it."""
    global _LOADED
    _LOADED = None


def describe(result: DotenvResult) -> str:
    """One operator-facing line about what was loaded."""
    if not result.loaded:
        return (
            "no .env found; provider keys must be exported in the environment "
            f"(looked in {len(result.searched)} location(s))"
        )
    return (
        f"{result.applied} variable(s) from {result.path}"
        + (f", {len(result.skipped)} already set" if result.skipped else "")
    )


__all__ = [
    "ENV_FILENAMES",
    "SEARCH_DEPTH",
    "DotenvResult",
    "candidate_paths",
    "describe",
    "load",
    "parse",
    "reset",
]
