"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    database.connection

Purpose:
    Open the system-of-record database with the settings correctness depends on,
    and hand out transactions.

Design goals:
    - Durability pragmas set explicitly, never left to the driver default
    - Foreign keys enforced, because SQLite disables them by default
    - One transaction boundary primitive, used by every repository
    - Synchronous, matching the capture path above it
    - In-memory mode for tests, identical schema

Notes:
    Three pragmas are set because SQLite's defaults are wrong for this use.
    ``foreign_keys`` is **off** unless asked for, so the reference from a
    transaction to its block would be decorative -- a cascade that never fires
    leaves orphan rows after a block is removed. ``journal_mode=WAL`` lets a
    reader run while the writer works, which matters because doctor and any
    query path read the same file the ingestion writer is appending to.
    ``synchronous=NORMAL`` under WAL keeps the durability that matters (a crash
    cannot corrupt the file) while dropping the per-commit fsync that would
    otherwise pace ingestion at disk-flush speed.

    The layer is synchronous. ``memory/`` uses ``aiosqlite`` and this does not,
    which is a deliberate difference rather than an oversight: everything above
    here -- dispatcher, sensor, poller -- is synchronous, and ``aiosqlite`` is a
    thread-pool wrapper that adds no concurrency for a single writer. Putting an
    async boundary in the middle of the write path would buy nothing and put a
    scheduler between the two operations whose ordering decides whether a crash
    loses a block.

    Datetimes are converted to ISO strings by the repositories rather than
    passed as objects. Python 3.12 deprecated the implicit datetime adapters,
    and an explicit conversion also makes the stored format something this
    codebase chose rather than something the driver chose for it.
"""

from __future__ import annotations

import logging
import sqlite3

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final, Iterator

from core.exceptions import PipelineError

from .migrations import CURRENT_VERSION, applied_version, migrate

logger = logging.getLogger(__name__)

#: Path that opens a private in-memory database, for tests.
MEMORY: Final[str] = ":memory:"

#: Seconds a write waits for a competing writer before giving up. Generous:
#: under WAL the only contention is writer-versus-writer, and failing a block
#: write to save five seconds trades durability for nothing.
BUSY_TIMEOUT: Final[float] = 30.0


class DatabaseError(PipelineError):
    """Raised when the system of record cannot be opened or written."""


class Database:
    """
    An open connection to the system of record, migrated and configured.

    Owns exactly one connection. SQLite allows one writer at a time regardless,
    so a pool would add contention handling for concurrency the engine does not
    provide; a single connection makes the serialisation explicit.
    """

    def __init__(self, path: str | Path = MEMORY, *, migrate_on_open: bool = True) -> None:
        self._path = str(path)
        self._connection: sqlite3.Connection | None = None
        self._migrate_on_open = migrate_on_open

    # -- lifecycle --------------------------------------------------------

    @property
    def path(self) -> str:
        return self._path

    @property
    def is_open(self) -> bool:
        return self._connection is not None

    def open(self) -> Database:
        """Connect, apply pragmas, and migrate to the current schema version."""
        if self._connection is not None:
            return self

        if self._path != MEMORY:
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)

        try:
            connection = sqlite3.connect(
                self._path,
                timeout=BUSY_TIMEOUT,
                # Transactions are managed explicitly through `transaction()`,
                # so the driver's implicit BEGIN is disabled. Left on, it would
                # open a transaction on the first write and hold it until
                # something happened to commit -- which is how a multi-statement
                # write ends up half-applied.
                isolation_level=None,
            )
        except sqlite3.Error as exc:
            raise DatabaseError(
                f"cannot open database at {self._path}: {exc}",
                details={"path": self._path},
            ) from exc

        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        # An in-memory database has no file to journal; WAL is meaningless and
        # setting it wastes a round trip.
        if self._path != MEMORY:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")

        self._connection = connection

        if self._migrate_on_open:
            version = migrate(connection)
            logger.debug("database at %s ready, schema v%d", self._path, version)

        return self

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> Database:
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- access -----------------------------------------------------------

    @property
    def connection(self) -> sqlite3.Connection:
        """The live connection, or an error naming what the caller forgot."""
        if self._connection is None:
            raise DatabaseError(
                f"database at {self._path} is not open; call open() first",
                details={"path": self._path},
            )
        return self._connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """
        One atomic unit of work.

        Every multi-row write goes through this. A block and its transactions
        must land together or not at all: a committed block with missing
        transactions is indistinguishable from a block that genuinely had none,
        and the next run will not retry it because the block is already there.
        """
        connection = self.connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except Exception:
            connection.execute("ROLLBACK")
            raise
        connection.execute("COMMIT")

    # -- reporting --------------------------------------------------------

    def schema_version(self) -> int:
        return applied_version(self.connection)

    def health(self) -> dict[str, Any]:
        """Operator-facing status, for doctor."""
        if self._connection is None:
            return {"path": self._path, "open": False}

        counts: dict[str, int] = {}
        for table in ("blocks", "transactions"):
            row = self._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = int(row[0]) if row else 0

        withdrawn = self._connection.execute(
            "SELECT COUNT(*) FROM blocks WHERE canonical = 0"
        ).fetchone()

        return {
            "path": self._path,
            "open": True,
            "schema_version": self.schema_version(),
            "expected_version": CURRENT_VERSION,
            "rows": counts,
            "withdrawn_blocks": int(withdrawn[0]) if withdrawn else 0,
        }

    def __repr__(self) -> str:
        return f"Database(path={self._path!r}, open={self.is_open})"


__all__ = ["BUSY_TIMEOUT", "MEMORY", "Database", "DatabaseError"]
