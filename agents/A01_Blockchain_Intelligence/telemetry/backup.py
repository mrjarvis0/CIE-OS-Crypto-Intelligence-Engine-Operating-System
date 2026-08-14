"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    telemetry.backup

Purpose:
    Copy the chain system of record safely while it is in use, verify the copy,
    and restore from it.

Design goals:
    - Consistent snapshot of a live database; no torn copies
    - Verified on write; an unverified backup is a guess
    - Restore refuses to clobber silently
    - Integrity checked before a restore is trusted
    - Standard library only

Notes:
    Copying a SQLite file with the filesystem is the standard way to produce a
    corrupt backup. Under WAL the committed state is split between the database
    file and the write-ahead log, so a plain copy taken mid-transaction captures
    one without the matching other. The file that results usually opens, often
    reads, and is wrong in a way that appears months later. SQLite's own
    :meth:`sqlite3.Connection.backup` takes a consistent snapshot of a live
    database, so that is what this uses.

    Every backup is verified immediately by opening it and running
    ``PRAGMA integrity_check``. Verifying at restore time is too late: the point
    of a backup is the moment the original is gone, and discovering then that it
    was never readable leaves nothing to fall back to.

    Restore refuses to overwrite an existing database unless told to, and moves
    the incumbent aside rather than deleting it. Disaster recovery is performed
    by people under pressure, and the recovery procedure should not itself be
    the thing that destroys the last good copy.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3

from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from database.connection import Database, DatabaseError

logger = logging.getLogger(__name__)

#: Pages copied per step. Small enough that a writer is not locked out for
#: long, large enough that a big database does not take all day.
BACKUP_PAGES_PER_STEP = 256


@dataclass(frozen=True, slots=True)
class BackupResult:
    """What a backup produced, and whether it can be trusted."""

    path: Path
    size_bytes: int
    blocks: int
    transactions: int
    verified: bool
    integrity: str = ""
    taken_at: datetime = None  # type: ignore[assignment]

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "size_bytes": self.size_bytes,
            "blocks": self.blocks,
            "transactions": self.transactions,
            "verified": self.verified,
            "integrity": self.integrity,
            "taken_at": self.taken_at.isoformat() if self.taken_at else None,
        }


class BackupError(DatabaseError):
    """Raised when a backup cannot be taken, verified, or restored."""


def backup(source: str | Path, destination: str | Path) -> BackupResult:
    """
    Take a consistent snapshot of a live database and verify it.

    Uses SQLite's online backup API rather than copying the file. Under WAL the
    committed state spans the database and its log, so a filesystem copy taken
    while a writer is active captures a torn state that usually opens and is
    quietly wrong.
    """
    source_path = Path(source)
    target = Path(destination)

    if not source_path.is_file():
        raise BackupError(f"nothing to back up at {source_path}")

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise BackupError(
            f"{target} already exists; backups are never overwritten in place"
        )

    try:
        # `closing`, not the bare context manager: sqlite3's own `with` commits
        # the transaction and leaves the connection open. On Windows the
        # lingering handle blocks the file replace a restore performs, and the
        # failure surfaces as a permission error during recovery.
        with closing(sqlite3.connect(source_path)) as live, closing(
            sqlite3.connect(target)
        ) as copy:
            live.backup(copy, pages=BACKUP_PAGES_PER_STEP)
    except sqlite3.Error as exc:
        target.unlink(missing_ok=True)
        raise BackupError(f"backup of {source_path} failed: {exc}") from exc

    result = verify(target)
    if not result.verified:
        # A backup that cannot be read is worse than none: it is a false
        # assurance, and the moment it is needed is the moment nothing else
        # remains.
        logger.error("backup at %s failed verification: %s", target, result.integrity)

    logger.info(
        "backed up %s -> %s (%d block(s), %.1f KiB)",
        source_path,
        target,
        result.blocks,
        result.size_bytes / 1024,
    )
    return result


def verify(path: str | Path) -> BackupResult:
    """
    Open a backup and check that it is a readable, intact A01 database.

    Runs SQLite's integrity check *and* counts rows. Integrity alone passes on
    a structurally valid database with no A01 schema in it, which is what a
    misdirected path produces.
    """
    target = Path(path)
    if not target.is_file():
        raise BackupError(f"no backup at {target}")

    integrity = "unreadable"
    blocks = transactions = 0
    verified = False

    try:
        with closing(
            sqlite3.connect(f"file:{target}?mode=ro", uri=True)
        ) as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
            integrity = str(row[0]) if row else "no result"

            blocks = int(
                connection.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
            )
            transactions = int(
                connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            )
            verified = integrity == "ok"
    except sqlite3.Error as exc:
        integrity = f"unreadable: {exc}"

    return BackupResult(
        path=target,
        size_bytes=target.stat().st_size,
        blocks=blocks,
        transactions=transactions,
        verified=verified,
        integrity=integrity,
        taken_at=datetime.now(UTC),
    )


def restore(
    backup_path: str | Path,
    destination: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """
    Restore a verified backup into place.

    Refuses an unverified backup, and moves any incumbent database aside rather
    than deleting it. Recovery is performed by people under pressure, and the
    procedure must not be the thing that destroys the last good copy.
    """
    source = Path(backup_path)
    target = Path(destination)

    result = verify(source)
    if not result.verified:
        raise BackupError(
            f"refusing to restore from {source}: integrity check said "
            f"{result.integrity!r}"
        )

    if target.exists():
        if not overwrite:
            raise BackupError(
                f"{target} exists; pass overwrite=True to replace it "
                "(the existing file will be moved aside, not deleted)"
            )
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%f")[:-3] + "Z"
        displaced = target.parent / f"{target.name}.superseded-{stamp}"
        target.replace(displaced)
        logger.warning("existing database moved to %s", displaced)

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

    # WAL and shm from the previous database describe a file that is gone.
    # Leaving them would have SQLite try to recover a log against the wrong
    # database, which is how a good restore becomes a corrupt one.
    for suffix in ("-wal", "-shm"):
        stale = Path(str(target) + suffix)
        stale.unlink(missing_ok=True)

    logger.info(
        "restored %s -> %s (%d block(s))", source, target, result.blocks
    )
    return target


def snapshot_name(chain: str = "ethereum", *, at: datetime | None = None) -> str:
    """A sortable, collision-resistant backup filename."""
    moment = at or datetime.now(UTC)
    return f"a01-{chain}-{moment.strftime('%Y%m%dT%H%M%SZ')}.db"


def health(database: Database) -> dict[str, Any]:
    """Backup-relevant facts about a live database, for doctor."""
    return {
        "path": database.path,
        "backup_api": "sqlite online backup",
        "note": (
            "A filesystem copy of a WAL database can be torn; use "
            "telemetry.backup.backup()"
        ),
    }


__all__ = [
    "BACKUP_PAGES_PER_STEP",
    "BackupError",
    "BackupResult",
    "backup",
    "health",
    "restore",
    "snapshot_name",
    "verify",
]
