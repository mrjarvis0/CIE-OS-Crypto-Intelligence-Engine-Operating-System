"""
Migration Runner

Tracks and applies incremental schema migrations for storage backends
that expose a migration-friendly connection. Each migration is a
callable receiving the backend and a migrate function.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

MigrationFn = Callable[[Any, "Migrator"], Awaitable[None]]


@dataclass(slots=True)
class MigrationRecord:
    """
    Result of applying a single migration.
    """

    version: int
    name: str
    applied: bool
    error: str | None = None


class MigrationError(Exception):
    """
    Raised when a migration cannot be applied.
    """


class MigrationRunner:
    """
    Applies registered migrations in version order.

    Responsibilities:
        * Register ordered migrations
        * Track applied versions
        * Apply pending migrations transactionally
    """

    def __init__(
        self,
        *,
        get_version: Callable[[], Awaitable[int]] | None = None,
        set_version: Callable[[int], Awaitable[None]] | None = None,
        table: str = "migrations",
    ) -> None:
        self._migrations: dict[int, MigrationFn] = {}
        self._get_version = get_version
        self._set_version = set_version
        self._table = table
        self._records: list[MigrationRecord] = []

    @property
    def migrations(self) -> dict[int, MigrationFn]:
        return dict(self._migrations)

    @property
    def records(self) -> list[MigrationRecord]:
        return list(self._records)

    def register(self, version: int, name: str | None = None) -> Callable[[MigrationFn], MigrationFn]:
        """
        Decorator registering a migration for a version number.
        """
        if version <= 0:
            raise ValueError("Migration version must be strictly positive.")

        def wrapper(fn: MigrationFn) -> MigrationFn:
            if version in self._migrations:
                raise ValueError(f"Migration version {version} already registered.")
            self._migrations[version] = fn
            setattr(fn, "_migration_name", name or fn.__name__)
            setattr(fn, "_migration_version", version)
            return fn

        return wrapper

    async def current_version(self) -> int:
        if self._get_version is not None:
            return await self._get_version()
        return 0

    async def apply(
        self,
        backend: Any,
        *,
        target_version: int | None = None,
    ) -> list[MigrationRecord]:
        """
        Apply all pending migrations up to ``target_version``.
        """
        current = await self.current_version()
        versions = sorted(version for version in self._migrations if version > current)
        if target_version is not None:
            versions = [version for version in versions if version <= target_version]
        self._records = []
        for version in versions:
            fn = self._migrations[version]
            name = getattr(fn, "_migration_name", fn.__name__)
            migrator = Migrator(
                version=version,
                set_version=self._set_version,
            )
            try:
                await fn(backend, migrator)
                await migrator.commit()
                self._records.append(
                    MigrationRecord(version=version, name=name, applied=True)
                )
            except Exception as exc:
                await migrator.rollback()
                self._records.append(
                    MigrationRecord(
                        version=version,
                        name=name,
                        applied=False,
                        error=str(exc),
                    )
                )
                raise MigrationError(
                    f"Migration {version} ({name}) failed: {exc}"
                ) from exc
        return self._records

    async def pending(self) -> list[int]:
        current = await self.current_version()
        return sorted(version for version in self._migrations if version > current)


class Migrator:
    """
    Per-migration handle providing version tracking and rollback.
    """

    def __init__(
        self,
        *,
        version: int,
        set_version: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        self._version = version
        self._set_version = set_version
        self._committed = False

    @property
    def version(self) -> int:
        return self._version

    async def commit(self) -> None:
        if self._set_version is not None:
            await self._set_version(self._version)
        self._committed = True

    async def rollback(self) -> None:
        self._committed = False

    @property
    def is_committed(self) -> bool:
        return self._committed
