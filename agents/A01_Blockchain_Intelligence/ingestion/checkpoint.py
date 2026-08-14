"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    ingestion.checkpoint

Purpose:
    Remember how far ingestion got on each chain, so a restart resumes rather
    than re-reads or skips.

Design goals:
    - Position recorded as height *and* hash, never height alone
    - Writes atomic; a crash mid-write leaves the previous position intact
    - Corrupt state refused loudly, never silently reset
    - Rewind allowed only when explicitly requested, for reorg recovery
    - Storage backend swappable; ingestion never touches a file directly

Notes:
    A checkpoint that stores only a height is unsafe across a reorg. Resuming
    at "height 500" after the chain reorganised below 500 means continuing on
    top of blocks that are no longer canonical, and nothing in the resumed run
    can detect it -- the parent linkage check compares against a tip that was
    never re-read. Storing the hash makes the mismatch visible on the first
    block after restart.

    Corruption is refused rather than repaired. A checkpoint file that will not
    parse could be reset to zero and re-ingested, which looks like a safe
    default and is not: on a chain with any history the run would silently
    start over, and if it were reset to the configured start height instead,
    everything between that height and the lost position becomes a hole nobody
    knows about. An operator being told the state is unreadable can fix it; a
    hole is found months later, if ever.

    Advancement is monotonic by default for the same reason. Ingestion moving
    backwards without being asked to means something already went wrong, and
    letting it quietly re-process history hides the fault instead of surfacing
    it. :meth:`CheckpointStore.rewind` is the deliberate exception, used by
    reorg recovery.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.exceptions import CheckpointError

logger = logging.getLogger(__name__)

#: Bumped when the on-disk shape changes. An unknown version is refused rather
#: than parsed optimistically.
CHECKPOINT_VERSION = 1


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """
    The last position ingestion is known to have completed on one chain.

    ``height`` is the last block *fully processed*, not the last one fetched.
    The distinction decides what happens after a crash: recording a fetch that
    was never processed turns a restart into a skipped block.
    """

    chain: str
    height: int
    block_hash: str
    updated_at: datetime = field(default_factory=utc_now)
    #: Blocks processed since the checkpoint was created. Diagnostic only.
    processed: int = 0

    def __post_init__(self) -> None:
        if not self.chain.strip():
            raise ValueError("checkpoint chain cannot be empty")
        if self.height < 0:
            raise ValueError("checkpoint height must be >= 0")
        if not self.block_hash.strip():
            raise ValueError("checkpoint must record the block hash, not height alone")
        if self.processed < 0:
            raise ValueError("processed count must be >= 0")

    @property
    def next_height(self) -> int:
        """The first height not yet processed."""
        return self.height + 1

    def advanced_to(self, height: int, block_hash: str) -> Checkpoint:
        """A new checkpoint one step further along the same chain."""
        return Checkpoint(
            chain=self.chain,
            height=height,
            block_hash=block_hash,
            processed=self.processed + 1,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "height": self.height,
            "block_hash": self.block_hash,
            "updated_at": self.updated_at.isoformat(),
            "processed": self.processed,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Checkpoint:
        """Rebuild from stored state, refusing anything unreadable."""
        if not isinstance(data, dict):
            raise CheckpointError(
                f"checkpoint record is {type(data).__name__}, not an object"
            )
        try:
            updated = data.get("updated_at")
            return cls(
                chain=str(data["chain"]),
                height=int(data["height"]),
                block_hash=str(data["block_hash"]),
                updated_at=(
                    datetime.fromisoformat(updated) if isinstance(updated, str) else utc_now()
                ),
                processed=int(data.get("processed", 0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CheckpointError(
                f"checkpoint record is unreadable: {exc}",
                details={"keys": sorted(data)},
            ) from exc


class CheckpointStore(ABC):
    """
    Where checkpoints live.

    Ingestion depends on this interface rather than on a file or a database,
    so the same loop is testable in memory and durable in production without
    a branch anywhere in the loop itself.
    """

    @abstractmethod
    def load(self, chain: str) -> Checkpoint | None:
        """The stored checkpoint for a chain, or None if there is none."""

    @abstractmethod
    def save(self, checkpoint: Checkpoint) -> None:
        """Persist a checkpoint, replacing any earlier one for that chain."""

    @abstractmethod
    def clear(self, chain: str) -> None:
        """Forget a chain's position entirely."""

    def advance(self, checkpoint: Checkpoint) -> Checkpoint:
        """
        Save a checkpoint that must be at or ahead of the stored one.

        Refuses a backwards move. Ingestion regressing without being asked to
        indicates a fault upstream, and silently re-processing history would
        bury it.
        """
        current = self.load(checkpoint.chain)
        if current is not None and checkpoint.height < current.height:
            raise CheckpointError(
                f"{checkpoint.chain}: refusing to move checkpoint backwards "
                f"({current.height} -> {checkpoint.height}); use rewind() for reorgs",
                details={"stored": current.height, "offered": checkpoint.height},
            )
        self.save(checkpoint)
        return checkpoint

    def rewind(self, chain: str, height: int, block_hash: str) -> Checkpoint:
        """
        Move a chain's position backwards after a reorg.

        Separated from :meth:`advance` so that every backwards move is an
        explicit decision with a reason, visible in the log and in the audit
        trail, rather than an ordinary save that happened to be lower.
        """
        rewound = Checkpoint(chain=chain, height=height, block_hash=block_hash)
        logger.warning("%s: checkpoint rewound to %d", chain, height)
        self.save(rewound)
        return rewound


class InMemoryCheckpointStore(CheckpointStore):
    """
    Non-durable store, for tests and for runs that should not resume.

    Losing the position on exit is the point: a test that resumed from a
    previous test's state would pass or fail depending on execution order.
    """

    def __init__(self) -> None:
        self._state: dict[str, Checkpoint] = {}

    def load(self, chain: str) -> Checkpoint | None:
        return self._state.get(chain)

    def save(self, checkpoint: Checkpoint) -> None:
        self._state[checkpoint.chain] = checkpoint

    def clear(self, chain: str) -> None:
        self._state.pop(chain, None)

    def __len__(self) -> int:
        return len(self._state)


class FileCheckpointStore(CheckpointStore):
    """
    Durable store: one JSON file holding every chain's position.

    Writes go to a temporary file in the same directory and are moved into
    place with :func:`os.replace`, which is atomic on the same filesystem. A
    crash therefore leaves either the previous complete file or the new
    complete file, never a half-written one -- and a half-written checkpoint is
    exactly the corrupt state this class refuses to guess at on load.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._cache: dict[str, Checkpoint] | None = None

    @property
    def path(self) -> Path:
        return self._path

    def load(self, chain: str) -> Checkpoint | None:
        return self._read().get(chain)

    def save(self, checkpoint: Checkpoint) -> None:
        state = dict(self._read())
        state[checkpoint.chain] = checkpoint
        self._write(state)

    def clear(self, chain: str) -> None:
        state = dict(self._read())
        if state.pop(chain, None) is not None:
            self._write(state)

    def all(self) -> dict[str, Checkpoint]:
        """Every stored position, for doctor and for operator inspection."""
        return dict(self._read())

    # -- io ---------------------------------------------------------------

    def _read(self) -> dict[str, Checkpoint]:
        if self._cache is not None:
            return self._cache

        if not self._path.is_file():
            self._cache = {}
            return self._cache

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointError(
                f"checkpoint file {self._path} is unreadable: {exc}. "
                "Resuming from zero would silently re-ingest history and "
                "resuming from a default would leave a hole, so neither is "
                "attempted; inspect or delete the file.",
                details={"path": str(self._path)},
            ) from exc

        if not isinstance(raw, dict):
            raise CheckpointError(
                f"checkpoint file {self._path} does not contain an object"
            )

        version = raw.get("version")
        if version != CHECKPOINT_VERSION:
            raise CheckpointError(
                f"checkpoint file {self._path} is version {version!r}, "
                f"this build writes {CHECKPOINT_VERSION}",
                details={"path": str(self._path), "found": version},
            )

        chains = raw.get("chains")
        if not isinstance(chains, dict):
            raise CheckpointError(f"checkpoint file {self._path} has no chains object")

        self._cache = {
            name: Checkpoint.from_dict(record) for name, record in chains.items()
        }
        return self._cache

    def _write(self, state: dict[str, Checkpoint]) -> None:
        payload = {
            "version": CHECKPOINT_VERSION,
            "chains": {name: cp.as_dict() for name, cp in state.items()},
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)

        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            delete=False,
        )
        try:
            with handle as tmp:
                json.dump(payload, tmp, indent=2, sort_keys=True)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(handle.name, self._path)
        except OSError as exc:
            raise CheckpointError(
                f"could not write checkpoint file {self._path}: {exc}",
                details={"path": str(self._path)},
            ) from exc
        finally:
            # The temp file survives only if the replace never happened.
            if os.path.exists(handle.name):  # pragma: no cover - crash path
                os.unlink(handle.name)

        self._cache = dict(state)


__all__ = [
    "CHECKPOINT_VERSION",
    "Checkpoint",
    "CheckpointStore",
    "FileCheckpointStore",
    "InMemoryCheckpointStore",
]
