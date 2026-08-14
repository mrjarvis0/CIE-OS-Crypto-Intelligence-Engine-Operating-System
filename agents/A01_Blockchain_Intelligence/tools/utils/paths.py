"""
Tools :: Utils :: Paths
=======================

Safe path handling helpers: the execution layer expects every path the Tools
subsystem touches to be normalized and confined to allowed roots.

Canonicalization (resolving symlinks and ``..``) happens *before* containment
checks so a path cannot be smuggled below an allowed root via a symlink.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Iterable, List, Union

__all__ = [
    "is_under",
    "is_relative_to",
    "can_inside",
    "safe_join",
    "ensure_dir",
    "atomic_write",
    "list_files",
    "list_dirs",
    "safe_filename",
    "temp_directory",
]

PathLike = Union[str, Path]


def _as(value: PathLike) -> Path:
    return Path(value)


def normalize(path: PathLike) -> Path:
    """Absolute, expanded, symlink-resolved path."""
    return Path(os.path.abspath(os.path.expanduser(str(path)))).resolve()


def is_under(path: PathLike, root: PathLike) -> bool:
    """True when ``path`` resolves to a location at or below ``root``."""
    try:
        normalize(path).relative_to(normalize(root))
        return True
    except ValueError:
        return False


def is_relative_to(base: PathLike, child: PathLike) -> bool:
    """True when ``child`` resolves inside ``base`` (lexically)."""
    try:
        _as(child).resolve().relative_to(_as(base).resolve())
        return True
    except ValueError:
        return False


def can_inside(path: PathLike, roots: Iterable[PathLike]) -> bool:
    """True when ``path`` resolves under any of the allowed ``roots``."""
    candidate = normalize(path)
    return any(candidate.is_relative_to(normalize(root)) for root in roots)


def safe_join(root: PathLike, *parts: str) -> Path:
    """Join ``root`` with ``parts`` while forbidding ``..`` escapes."""
    root_p = normalize(root)
    joined = root_p.joinpath(*parts)
    if not is_relative_to(root_p, joined):
        raise ValueError(f"path escapes allowed root: {joined}")
    return joined


def ensure_dir(path: PathLike, *, create: bool = True) -> Path:
    """Return the resolved directory path, creating it when ``create``."""
    directory = _as(path).resolve()
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def atomic_write(
    target: PathLike, data: Union[str, bytes], *, encoding: str = "utf-8"
) -> Path:
    """
    Write ``data`` atomically (temp file + rename).

    Readers never observe a partially written file, and the original is
    preserved if the write fails.
    """
    target_path = _as(target).resolve()
    parent = target_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.", suffix=".tmp", dir=str(parent)
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            if isinstance(data, str):
                data = data.encode(encoding)
            fh.write(data)
        os.replace(temp_name, target_path)
    except BaseException:
        if os.path.exists(temp_name):
            os.remove(temp_name)
        raise
    return target_path


def list_files(directory: PathLike, pattern: str = "*") -> List[Path]:
    """Sorted list of files under ``directory`` matching ``pattern``."""
    base = _as(directory).resolve()
    return sorted(p for p in base.glob(pattern) if p.is_file())


def list_dirs(directory: PathLike) -> List[Path]:
    """Sorted list of sub-directories under ``directory``."""
    return sorted(p for p in _as(directory).iterdir() if p.is_dir())


def safe_filename(value: str) -> str:
    """Strip characters unsafe in filesystem filenames; empty-safe."""
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value)).strip("-")
    return cleaned or "untitled"


def temp_directory(prefix: str = "tools-") -> Path:
    """Create and return a fresh temporary directory."""
    return Path(tempfile.mkdtemp(prefix=prefix))