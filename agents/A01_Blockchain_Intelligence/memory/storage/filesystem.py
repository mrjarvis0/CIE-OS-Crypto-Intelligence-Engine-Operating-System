"""
File System Storage

File-based storage backend for portable, human-readable memory
entries. Each entry is persisted as an atomic JSON file on disk.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Sequence

from memory.base.memory import MemoryEntry
from memory.storage.repository import (
    StorageConnectionError,
    StorageError,
    dumps_entry,
    entry_payload_matches,
    loads_entry,
)

DEFAULT_DIRECTORY = "memory_data"
EXTENSION = ".json"


class FileSystemStorage:
    """
    File system persistence backend for memory.

    Responsibilities:
        * Snapshot serialization
        * Directory layout management
        * Atomic file writes
    """

    def __init__(
        self,
        *,
        directory: str | Path = DEFAULT_DIRECTORY,
    ) -> None:
        self._directory = Path(directory)
        self._connected = False

    @property
    def directory(self) -> Path:
        return self._directory

    def _path_for(self, key: str) -> Path:
        return self._directory / f"{key}{EXTENSION}"

    async def connect(self) -> None:
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            self._connected = True
        except OSError as exc:
            raise StorageConnectionError(
                f"File system connect failed: {exc}"
            ) from exc

    async def disconnect(self) -> None:
        self._connected = False

    async def save(self, entry: MemoryEntry[Any]) -> None:
        target = self._path_for(entry.key)
        payload = dumps_entry(entry)
        try:
            fd, temp_path = tempfile.mkstemp(
                suffix=".tmp",
                dir=str(self._directory),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                os.replace(temp_path, target)
            except BaseException:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
                raise
        except OSError as exc:
            raise StorageError(f"File save failed: {exc}") from exc

    async def delete(self, key: str) -> None:
        target = self._path_for(key)
        try:
            if target.exists():
                target.unlink()
        except OSError as exc:
            raise StorageError(f"File delete failed: {exc}") from exc

    async def load(self, key: str) -> MemoryEntry[Any] | None:
        target = self._path_for(key)
        if not target.exists():
            return None
        try:
            payload = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"File load failed: {exc}") from exc
        return loads_entry(payload)

    async def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> Sequence[MemoryEntry[Any]]:
        results: list[MemoryEntry[Any]] = []
        for path in sorted(self._directory.glob(f"*{EXTENSION}")):
            try:
                payload = path.read_text(encoding="utf-8")
            except OSError:
                continue
            entry = loads_entry(payload)
            if entry_payload_matches(entry, query):
                results.append(entry)
                if len(results) >= limit:
                    break
        return results

    async def keys(self) -> Sequence[str]:
        return [
            path.name[: -len(EXTENSION)]
            for path in sorted(self._directory.glob(f"*{EXTENSION}"))
            if path.is_file()
        ]

    async def clear(self) -> None:
        for path in self._directory.glob(f"*{EXTENSION}"):
            try:
                path.unlink()
            except OSError:
                pass

    def health(self) -> dict[str, Any]:
        return {
            "directory": str(self._directory),
            "connected": self._connected,
        }

    def to_json(self) -> str:
        """
        Export all entries as a single JSON document.
        """
        payloads = {}
        for path in self._directory.glob(f"*{EXTENSION}"):
            payloads[path.name[: -len(EXTENSION)]] = json.loads(
                path.read_text(encoding="utf-8")
            )
        return json.dumps(payloads, indent=2, sort_keys=True)
