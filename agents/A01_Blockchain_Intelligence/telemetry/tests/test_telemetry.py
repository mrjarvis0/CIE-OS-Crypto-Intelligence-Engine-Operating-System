"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for telemetry -- the metrics that show A01 is lying, and the backups that
survive being needed.

The backup tests matter more than they look. A backup is exercised exactly once,
under pressure, when the original is gone; every property it needs has to be
verified now, because there is no second chance to check later.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from database import Database, RecordWriter, SqliteBlockRepository
from decision import DecisionEngine, Subscription
from intelligence.core.engine import IntelligenceEngine
from schemas import Address
from sensors.envelope import Provenance, RawRecord, RecordKind
from skills.base import Coverage
from telemetry import (
    ALLOWED_LABELS,
    MAX_SERIES,
    BackupError,
    MetricsRegistry,
    backup,
    restore,
    snapshot_name,
    verify,
)


def block_record(number: int) -> RawRecord:
    return RawRecord(
        chain="ethereum",
        kind=RecordKind.BLOCK,
        height=number,
        provenance=Provenance("fixture", "ethereum", "eth_getBlockByNumber", "ok"),
        payload={
            "number": hex(number),
            "hash": f"0xa{number:06d}",
            "parentHash": f"0xa{number - 1:06d}",
            "timestamp": hex(1_700_000_000 + number * 12),
            "transactions": [
                {
                    "hash": f"0xtx{number:05d}",
                    "from": "0x" + "a1" * 20,
                    "to": "0x" + "b2" * 20,
                    "value": hex(10**24),
                    "transactionIndex": "0x0",
                    "input": "0x",
                }
            ],
        },
    )


@pytest.fixture
def live_db(tmp_path):
    """A populated on-disk database, WAL and all."""
    path = tmp_path / "a01.db"
    with Database(path) as db:
        writer = RecordWriter(SqliteBlockRepository(db))
        for number in (100, 101, 102):
            writer.write(block_record(number))
    return path


# ==============================================================================
# METRICS
# ==============================================================================

def test_counters_accumulate():
    registry = MetricsRegistry()
    registry.counter("blocks_seen", labels={"chain": "ethereum"})
    registry.counter("blocks_seen", labels={"chain": "ethereum"})

    assert 'a01_blocks_seen{chain="ethereum"} 2' in registry.render()


def test_gauges_replace():
    registry = MetricsRegistry()
    registry.gauge("queue_depth", 10)
    registry.gauge("queue_depth", 3)

    assert "a01_queue_depth 3" in registry.render()


def test_an_unbounded_label_is_dropped():
    """
    A metric labelled by address grows one series per address observed, which
    on a chain is unbounded — the classic way a monitoring backend is taken
    down by the thing it monitors.
    """
    registry = MetricsRegistry()
    registry.counter("transfers", labels={"address": "0x" + "a1" * 20, "chain": "ethereum"})

    rendered = registry.render()
    assert "a1a1a1" not in rendered
    assert 'chain="ethereum"' in rendered


def test_series_growth_is_capped():
    registry = MetricsRegistry()
    for i in range(MAX_SERIES + 20):
        registry.counter("wide", labels={"outcome": f"o{i}"})

    assert len(registry.as_dict()["metrics"]["wide"]["series"]) == MAX_SERIES


def test_allowed_labels_exclude_anything_chain_scaled():
    for unbounded in ("address", "tx_hash", "block", "height"):
        assert unbounded not in ALLOWED_LABELS


def test_observing_a_writer_records_throughput(live_db):
    registry = MetricsRegistry()
    with Database(live_db) as db:
        writer = RecordWriter(SqliteBlockRepository(db))
        writer.write(block_record(103))
        registry.observe_writer(writer)

    rendered = registry.render()
    assert "a01_blocks_written" in rendered
    assert "a01_transactions_written" in rendered


def test_the_honesty_metrics_are_recorded():
    """
    The series a conventional health check does not have. Without them an
    operator sees green over a system that has concluded nothing.
    """
    registry = MetricsRegistry()
    subject = {"address": "0x" + "a1" * 20, "chain": "ethereum"}
    package = IntelligenceEngine().run(subject)
    decision = DecisionEngine(subscriptions=[Subscription("desk")]).decide(package)

    registry.observe_decision(decision)
    rendered = registry.render()

    assert "a01_conclusions_undetermined" in rendered
    assert "a01_alerts_suppressed" in rendered


def test_coverage_is_exported_as_a_boolean_gauge(live_db):
    from database import SqliteAnalyticsRepository

    registry = MetricsRegistry()
    with Database(live_db) as db:
        window = SqliteAnalyticsRepository(db).window("ethereum")
        registry.observe_coverage(Coverage(window=window))

    assert "a01_coverage_supports_absence" in registry.render()
    assert 'a01_coverage_supports_absence{chain="ethereum"} 0' in registry.render()


def test_a_broken_observation_does_not_raise():
    """Telemetry must never take down the thing it measures."""
    registry = MetricsRegistry()

    registry.observe_writer(object())
    registry.observe_decision(object())
    registry.observe_coverage(object())

    assert "a01_uptime_seconds" in registry.render()


# ==============================================================================
# BACKUP
# ==============================================================================

def test_a_backup_is_taken_and_verified(live_db, tmp_path):
    result = backup(live_db, tmp_path / "backup.db")

    assert result.verified
    assert result.integrity == "ok"
    assert result.blocks == 3


def test_a_backup_of_a_live_wal_database_is_consistent(live_db, tmp_path):
    """
    A filesystem copy of a WAL database taken mid-write is torn: the committed
    state spans the file and the log. The online backup API is why this passes.
    """
    with Database(live_db) as db:
        writer = RecordWriter(SqliteBlockRepository(db))
        writer.write(block_record(103))

        # Backup while the connection is open, as a scheduled backup would.
        result = backup(live_db, tmp_path / "hot.db")

    assert result.verified
    assert result.blocks == 4


def test_a_backup_never_overwrites(live_db, tmp_path):
    target = tmp_path / "backup.db"
    backup(live_db, target)

    with pytest.raises(BackupError):
        backup(live_db, target)


def test_backing_up_a_missing_database_fails_loudly(tmp_path):
    with pytest.raises(BackupError):
        backup(tmp_path / "nothing.db", tmp_path / "out.db")


def test_verification_rejects_a_file_that_is_not_an_a01_database(tmp_path):
    """
    Integrity alone passes on any valid SQLite file. A misdirected path
    produces exactly that, and it must not be mistaken for a backup.
    """
    stray = tmp_path / "stray.db"
    # `closing`, because sqlite3's own context manager commits without closing.
    with closing(sqlite3.connect(stray)) as connection:
        connection.execute("CREATE TABLE unrelated (x INTEGER)")

    assert not verify(stray).verified


def test_verification_rejects_a_corrupt_file(tmp_path):
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"this is not a database")

    assert not verify(corrupt).verified


# ==============================================================================
# RESTORE
# ==============================================================================

def test_a_verified_backup_restores(live_db, tmp_path):
    source = backup(live_db, tmp_path / "backup.db")
    target = tmp_path / "restored.db"

    restore(source.path, target)

    with Database(target) as db:
        assert SqliteBlockRepository(db).count("ethereum") == 3


def test_restore_refuses_an_unverified_backup(tmp_path):
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"not a database")

    with pytest.raises(BackupError):
        restore(corrupt, tmp_path / "target.db")


def test_restore_will_not_clobber_without_being_told(live_db, tmp_path):
    source = backup(live_db, tmp_path / "backup.db")

    with pytest.raises(BackupError):
        restore(source.path, live_db)


def test_a_displaced_database_is_moved_aside_not_deleted(live_db, tmp_path):
    """
    Recovery happens under pressure. The procedure must not be the thing that
    destroys the last good copy.
    """
    source = backup(live_db, tmp_path / "backup.db")

    restore(source.path, live_db, overwrite=True)

    displaced = list(live_db.parent.glob("*.superseded-*"))
    assert displaced, "the incumbent database must survive somewhere"


def test_restore_clears_a_stale_write_ahead_log(live_db, tmp_path):
    """
    A leftover WAL describes a database that is gone. SQLite would try to
    recover it against the restored file, turning a good restore into a corrupt
    one.
    """
    source = backup(live_db, tmp_path / "backup.db")
    target = tmp_path / "restored.db"
    stale = tmp_path / "restored.db-wal"
    stale.write_bytes(b"stale log")

    restore(source.path, target)

    assert not stale.exists()


def test_a_snapshot_name_sorts_chronologically():
    from datetime import UTC, datetime

    earlier = snapshot_name(at=datetime(2026, 1, 1, tzinfo=UTC))
    later = snapshot_name(at=datetime(2026, 6, 1, tzinfo=UTC))

    assert earlier < later
