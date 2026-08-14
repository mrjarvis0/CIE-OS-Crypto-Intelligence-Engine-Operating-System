"""
CIE-OS
A02 News Intelligence Agent

Module:
    core.storage

Purpose:
    SQLite persistence — schema and async repositories (Phase 1).

Design goals:
    - Async-first (aiosqlite)
    - Idempotent writes — UNIQUE(source, source_key) prevents double-insert
    - No business logic in the storage layer
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from .models import Entity, NormalizedItem

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT    NOT NULL,
    source_key    TEXT    NOT NULL,
    url           TEXT,
    title         TEXT    NOT NULL,
    content       TEXT,
    author        TEXT,
    published_at  TEXT,
    fetched_at    TEXT    NOT NULL,
    language      TEXT,
    platform      TEXT,
    title_fp      TEXT    NOT NULL,
    content_fp    TEXT    NOT NULL,
    UNIQUE(source, source_key)
);

CREATE INDEX IF NOT EXISTS idx_items_title_fp ON items(title_fp);
CREATE INDEX IF NOT EXISTS idx_items_content_fp ON items(content_fp);
CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at);

CREATE TABLE IF NOT EXISTS entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    entity_type TEXT    NOT NULL,
    symbol      TEXT    NOT NULL,
    name        TEXT,
    context     TEXT
);

CREATE INDEX IF NOT EXISTS idx_entities_symbol ON entities(symbol);
CREATE INDEX IF NOT EXISTS idx_entities_item ON entities(item_id);

CREATE TABLE IF NOT EXISTS narratives (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_text    TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'emerging',
    first_seen    TEXT    NOT NULL,
    last_seen     TEXT    NOT NULL,
    mention_count INTEGER NOT NULL DEFAULT 1,
    source_count  INTEGER NOT NULL DEFAULT 1,
    platforms     TEXT    NOT NULL DEFAULT '[]',
    stances       TEXT    NOT NULL DEFAULT '{}',
    fomo_score    REAL    NOT NULL DEFAULT 0,
    velocity      REAL    NOT NULL DEFAULT 0,
    entities      TEXT    NOT NULL DEFAULT '[]',
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_narratives_last_seen ON narratives(last_seen);

CREATE TABLE IF NOT EXISTS narrative_items (
    narrative_id INTEGER NOT NULL REFERENCES narratives(id) ON DELETE CASCADE,
    item_id      INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    stance       TEXT    NOT NULL,
    PRIMARY KEY (narrative_id, item_id)
);

CREATE INDEX IF NOT EXISTS idx_narrative_items_item ON narrative_items(item_id);

CREATE TABLE IF NOT EXISTS market_prices (
    symbol    TEXT NOT NULL,
    interval  TEXT NOT NULL,
    open_time TEXT NOT NULL,
    open      REAL,
    high      REAL,
    low       REAL,
    close     REAL,
    volume    REAL,
    PRIMARY KEY (symbol, interval, open_time)
);

CREATE TABLE IF NOT EXISTS impact_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    narrative_id     INTEGER,
    asset            TEXT    NOT NULL,
    category         TEXT,
    first_seen       TEXT,
    horizon_hours    INTEGER NOT NULL,
    measured_return  REAL,
    fomo_score       REAL,
    epistemic_status TEXT,
    confidence       REAL,
    coordination     REAL,
    created_at       TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_impact_events_asset ON impact_events(asset);
CREATE INDEX IF NOT EXISTS idx_impact_events_category ON impact_events(category);

CREATE TABLE IF NOT EXISTS scan_stats (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT    NOT NULL,
    items_fetched INTEGER NOT NULL DEFAULT 0,
    items_stored  INTEGER NOT NULL DEFAULT 0,
    items_dup     INTEGER NOT NULL DEFAULT 0,
    narratives    INTEGER NOT NULL DEFAULT 0,
    verdicts      TEXT    NOT NULL DEFAULT '{}'
);
"""


class Storage:
    """Async SQLite repository for items and entities."""

    _NARRATIVE_MIGRATIONS: tuple[tuple[str, str], ...] = (
        ("epistemic_status", "epistemic_status TEXT NOT NULL DEFAULT 'unconfirmed'"),
        ("confidence", "confidence REAL NOT NULL DEFAULT 0"),
        ("coordination_score", "coordination_score REAL NOT NULL DEFAULT 0"),
        ("manipulation", "manipulation TEXT NOT NULL DEFAULT '{}'"),
        ("evidence", "evidence TEXT NOT NULL DEFAULT '{}'"),
    )

    _IMPACT_MIGRATIONS: tuple[tuple[str, str], ...] = (
        ("predicted_direction", "predicted_direction TEXT"),
        ("predicted_probability", "predicted_probability REAL"),
        ("predicted_mean_pct", "predicted_mean_pct REAL"),
        ("actual_return", "actual_return REAL"),
        ("actual_direction", "actual_direction TEXT"),
        ("truth_outcome", "truth_outcome TEXT"),
        ("resolved_at", "resolved_at TEXT"),
    )

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)

    async def init(self) -> None:
        """Create schema if missing and migrate old tables. Safe to call multiple times."""

        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(_SCHEMA)
            await self._migrate(db)
            await db.commit()

    async def _migrate(self, db: aiosqlite.Connection) -> None:
        """Add columns to tables created before later phases."""

        cursor = await db.execute("PRAGMA table_info(narratives)")
        columns = {row[1] for row in await cursor.fetchall()}
        for name, ddl in self._NARRATIVE_MIGRATIONS:
            if name not in columns:
                await db.execute(f"ALTER TABLE narratives ADD COLUMN {ddl}")
        cursor = await db.execute("PRAGMA table_info(impact_events)")
        impact_columns = {row[1] for row in await cursor.fetchall()}
        for name, ddl in self._IMPACT_MIGRATIONS:
            if name not in impact_columns:
                await db.execute(f"ALTER TABLE impact_events ADD COLUMN {ddl}")

    async def is_duplicate(self, url: str | None, title_fp: str, content_fp: str) -> bool:
        """Check whether an item is already known (url / title fp / content fp)."""

        async with aiosqlite.connect(self.db_path) as db:
            if url:
                cursor = await db.execute("SELECT 1 FROM items WHERE url = ? LIMIT 1", (url,))
                if await cursor.fetchone():
                    return True
            if title_fp:
                cursor = await db.execute("SELECT 1 FROM items WHERE title_fp = ? LIMIT 1", (title_fp,))
                if await cursor.fetchone():
                    return True
            if content_fp:
                cursor = await db.execute("SELECT 1 FROM items WHERE content_fp = ? LIMIT 1", (content_fp,))
                if await cursor.fetchone():
                    return True
        return False

    async def insert_item(self, item: NormalizedItem) -> int:
        """Insert item + entities. Returns new row id (raises on duplicate)."""

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO items
                    (source, source_key, url, title, content, author,
                     published_at, fetched_at, language, platform, title_fp, content_fp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.source,
                    item.source_key,
                    item.url,
                    item.title,
                    item.content,
                    item.author,
                    item.published_at.isoformat() if item.published_at else None,
                    item.fetched_at.isoformat(),
                    item.language,
                    item.platform,
                    item.title_fingerprint,
                    item.content_fingerprint,
                ),
            )
            item_id = int(cursor.lastrowid)
            item.id = item_id
            for entity in item.entities:
                await db.execute(
                    "INSERT INTO entities (item_id, entity_type, symbol, name, context) VALUES (?, ?, ?, ?, ?)",
                    (item_id, entity.type, entity.symbol, entity.name, entity.context),
                )
            await db.commit()
            return item_id

    async def count_items(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM items")
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def count_entities(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM entities")
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def recent_items(self, limit: int = 20) -> list[dict]:
        """Most recent stored items with their entities."""

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM items ORDER BY fetched_at DESC LIMIT ?", (limit,)
            )
            rows = [dict(row) for row in await cursor.fetchall()]
            for row in rows:
                ecursor = await db.execute(
                    "SELECT entity_type, symbol, name FROM entities WHERE item_id = ?",
                    (row["id"],),
                )
                row["entities"] = [dict(e) for e in await ecursor.fetchall()]
            return rows

    # ==========================================================================
    # NARRATIVES (Phase 2)
    # ==========================================================================

    async def insert_narrative(self, data: dict) -> int:
        """Insert a narrative row from a plain dict. Returns new id."""

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO narratives
                    (claim_text, status, first_seen, last_seen, mention_count,
                     source_count, platforms, stances, fomo_score, velocity,
                     entities, epistemic_status, confidence, coordination_score,
                     manipulation, evidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["claim_text"],
                    data["status"],
                    data["first_seen"],
                    data["last_seen"],
                    data["mention_count"],
                    data["source_count"],
                    json.dumps(data["platforms"]),
                    json.dumps(data["stance_counts"]),
                    data["fomo_score"],
                    data["velocity"],
                    json.dumps(data["entities"]),
                    data.get("epistemic_status", "unconfirmed"),
                    data.get("confidence", 0.0),
                    data.get("coordination_score", 0.0),
                    json.dumps(data.get("manipulation_flags", {})),
                    json.dumps(data.get("evidence", {})),
                    data["created_at"],
                    data["updated_at"],
                ),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def update_narrative(self, narrative_id: int, data: dict) -> None:
        """Update a narrative row from a plain dict."""

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE narratives SET
                    claim_text = ?, status = ?, first_seen = ?, last_seen = ?,
                    mention_count = ?, source_count = ?, platforms = ?,
                    stances = ?, fomo_score = ?, velocity = ?, entities = ?,
                    epistemic_status = ?, confidence = ?, coordination_score = ?,
                    manipulation = ?, evidence = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    data["claim_text"],
                    data["status"],
                    data["first_seen"],
                    data["last_seen"],
                    data["mention_count"],
                    data["source_count"],
                    json.dumps(data["platforms"]),
                    json.dumps(data["stance_counts"]),
                    data["fomo_score"],
                    data["velocity"],
                    json.dumps(data["entities"]),
                    data.get("epistemic_status", "unconfirmed"),
                    data.get("confidence", 0.0),
                    data.get("coordination_score", 0.0),
                    json.dumps(data.get("manipulation_flags", {})),
                    json.dumps(data.get("evidence", {})),
                    data["updated_at"],
                    narrative_id,
                ),
            )
            await db.commit()

    async def add_narrative_item(self, narrative_id: int, item: NormalizedItem, stance: str) -> None:
        """Link an item to a narrative with its stance (idempotent)."""

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO narrative_items (narrative_id, item_id, stance) VALUES (?, ?, ?)",
                (narrative_id, item.id, stance),
            )
            await db.commit()

    async def load_active_narratives(self, since: str) -> list[dict]:
        """Load narratives updated since `since` (ISO string) with their items."""

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM narratives WHERE last_seen >= ?", (since,)
            )
            rows = [dict(row) for row in await cursor.fetchall()]
            for row in rows:
                row["platforms"] = json.loads(row["platforms"])
                row["stance_counts"] = json.loads(row["stances"])
                row["entities"] = json.loads(row["entities"])
                row["manipulation_flags"] = json.loads(row.get("manipulation", "{}"))
                row["evidence"] = json.loads(row.get("evidence", "{}"))
                icursor = await db.execute(
                    """
                    SELECT i.id, i.source, i.source_key, i.url, i.title, i.content,
                           i.author, i.published_at, i.fetched_at, i.language,
                           i.platform, i.title_fp, i.content_fp, ni.stance
                    FROM narrative_items ni
                    JOIN items i ON i.id = ni.item_id
                    WHERE ni.narrative_id = ?
                    """,
                    (row["id"],),
                )
                items = [dict(item) for item in await icursor.fetchall()]
                for item in items:
                    ecursor = await db.execute(
                        "SELECT entity_type, symbol, name FROM entities WHERE item_id = ?",
                        (item["id"],),
                    )
                    item["entities"] = [dict(e) for e in await ecursor.fetchall()]
                row["items"] = items
            return rows

    # ==========================================================================
    # IMPACT EVENTS (Phase 4)
    # ==========================================================================

    async def insert_impact_event(self, data: dict) -> int:
        """Insert an impact event row (with Phase-5 prediction snapshot). Returns new id."""

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO impact_events
                    (narrative_id, asset, category, first_seen, horizon_hours,
                     measured_return, fomo_score, epistemic_status, confidence,
                     coordination, predicted_direction, predicted_probability,
                     predicted_mean_pct, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("narrative_id"),
                    data["asset"],
                    data.get("category"),
                    data.get("first_seen"),
                    data["horizon_hours"],
                    data.get("measured_return"),
                    data.get("fomo_score"),
                    data.get("epistemic_status"),
                    data.get("confidence"),
                    data.get("coordination"),
                    data.get("predicted_direction"),
                    data.get("predicted_probability"),
                    data.get("predicted_mean_pct"),
                    data.get("created_at", datetime.now(UTC).isoformat()),
                ),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def resolve_impact_event(
        self,
        event_id: int,
        actual_return: float,
        actual_direction: str,
        truth_outcome: str | None = None,
    ) -> None:
        """Store the realized outcome for a prediction (Phase 5 learning loop)."""

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE impact_events
                SET actual_return = ?, actual_direction = ?, truth_outcome = ?,
                    resolved_at = ?
                WHERE id = ?
                """,
                (
                    actual_return,
                    actual_direction,
                    truth_outcome,
                    datetime.now(UTC).isoformat(),
                    event_id,
                ),
            )
            await db.commit()

    async def load_unresolved_impact_events(self) -> list[dict]:
        """Impact events whose outcome has not been resolved yet."""

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM impact_events WHERE actual_direction IS NULL ORDER BY id"
            )
            return [dict(row) for row in await cursor.fetchall()]

    # SCAN STATS (Phase 5 drift tracking)
    # ==========================================================================

    async def insert_scan_stat(self, data: dict) -> None:
        """Record one scan's volumes + verdict distribution for drift monitoring."""

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO scan_stats
                    (created_at, items_fetched, items_stored, items_dup,
                     narratives, verdicts)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("created_at", datetime.now(UTC).isoformat()),
                    data.get("items_fetched", 0),
                    data.get("items_stored", 0),
                    data.get("items_dup", 0),
                    data.get("narratives", 0),
                    data.get("verdicts", "{}"),
                ),
            )
            await db.commit()

    async def load_scan_stats(self, limit: int = 50) -> list[dict]:
        """Recent scan statistics, oldest first."""

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM scan_stats ORDER BY id ASC LIMIT ?", (limit,)
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def load_impact_events(
        self, asset: str | None = None, category: str | None = None, limit: int = 500
    ) -> list[dict]:
        """Load stored impact events, optionally filtered by asset/category."""

        query = "SELECT * FROM impact_events"
        clauses: list[str] = []
        params: list = []
        if asset:
            clauses.append("asset = ?")
            params.append(asset)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            return [dict(row) for row in await cursor.fetchall()]


__all__ = ["Storage"]
