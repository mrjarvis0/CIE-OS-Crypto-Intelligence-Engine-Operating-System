"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the database layer -- atomicity, idempotency, and the reorg
invariants that decide whether stored history is trustworthy.

The two properties worth most here cannot be checked by reading the code: that
a value larger than a 64-bit column comes back unchanged, and that a query
written the obvious way cannot see abandoned blocks. Both are asserted against
a real SQLite database rather than a mock, because both are properties of the
engine and the schema rather than of the Python.
"""

from __future__ import annotations

import sqlite3

import pytest

from database import (
    CURRENT_VERSION,
    Database,
    DatabaseError,
    RecordWriter,
    SqliteBlockRepository,
    migrate,
)
from blockchain.reorg import BlockRef, ReorgEvent
from ingestion.events import PollResult, PollStatus
from ingestion.queue import RecordQueue
from schemas import Address, Amount, CanonicalBlock, CanonicalTransaction, from_unix
from sensors.envelope import Provenance, RawRecord, RecordKind

SQLITE_INTEGER_MAX = 2**63 - 1
TIMESTAMP = 1_700_000_000


@pytest.fixture
def db():
    with Database() as database:
        yield database


@pytest.fixture
def repo(db):
    return SqliteBlockRepository(db)


def transaction_at(
    number: int, index: int = 0, value: int = 10**18, tag: str = "a"
) -> CanonicalTransaction:
    return CanonicalTransaction(
        chain="ethereum",
        tx_hash=f"0xtx{tag}{number:04d}{index:02d}",
        block_number=number,
        block_hash=f"0x{tag}{number:06d}",
        index=index,
        from_address=Address.parse("0x" + "1" * 40, "ethereum"),
        to_address=Address.parse("0x" + "2" * 40, "ethereum"),
        value=Amount(value),
        source_record_id=f"rec-{number}",
    )


def block_at(number: int, tag: str = "a", *, transactions=()) -> CanonicalBlock:
    return CanonicalBlock(
        chain="ethereum",
        number=number,
        block_hash=f"0x{tag}{number:06d}",
        parent_hash=f"0x{tag}{number - 1:06d}",
        timestamp=from_unix(TIMESTAMP + number * 12),
        transaction_count=len(transactions),
        transactions=tuple(transactions),
        source_record_id=f"rec-{number}",
        source_provider="publicnode",
    )


# ==============================================================================
# MIGRATIONS
# ==============================================================================

def test_a_fresh_database_reaches_the_current_version(db):
    assert db.schema_version() == CURRENT_VERSION


def test_migrating_twice_is_harmless(db):
    assert migrate(db.connection) == CURRENT_VERSION
    assert migrate(db.connection) == CURRENT_VERSION


def test_a_newer_schema_is_refused_rather_than_downgraded():
    """Running against a schema this build does not know would corrupt it."""
    with Database(migrate_on_open=False) as database:
        database.connection.execute("PRAGMA user_version = 999")
        with pytest.raises(RuntimeError):
            migrate(database.connection)


def test_using_a_closed_database_says_what_was_forgotten():
    database = Database()
    with pytest.raises(DatabaseError):
        _ = database.connection


def test_foreign_keys_are_enforced(db):
    """SQLite disables them by default, which makes the cascade decorative."""
    row = db.connection.execute("PRAGMA foreign_keys").fetchone()
    assert row[0] == 1


# ==============================================================================
# WRITES — atomicity and idempotency
# ==============================================================================

def test_a_block_and_its_transactions_land_together(repo):
    block = block_at(100, transactions=[transaction_at(100, 0), transaction_at(100, 1)])
    outcome = repo.save(block)

    assert outcome.inserted
    assert outcome.transactions_written == 2
    assert len(repo.transactions_of(block)) == 2


def test_replaying_a_block_is_a_no_op_not_an_error(repo):
    """
    The durable half of idempotency. The in-memory dedup window empties on
    restart, so the guarantee has to live in the primary key.
    """
    block = block_at(100, transactions=[transaction_at(100)])
    first = repo.save(block)
    second = repo.save(block)

    assert first.inserted
    assert not second.inserted
    assert repo.count("ethereum") == 1


def test_a_failed_transaction_write_rolls_back_the_block(repo, monkeypatch):
    """
    A committed block with missing transactions is indistinguishable from a
    block that genuinely had none, and because the block row exists nothing
    retries it.
    """
    block = block_at(100, transactions=[transaction_at(100)])

    def explode(*args, **kwargs):
        raise sqlite3.OperationalError("disk failure")

    monkeypatch.setattr(repo, "_insert_transactions", explode)

    with pytest.raises(sqlite3.OperationalError):
        repo.save(block)

    assert repo.count("ethereum") == 0, "the block must not survive its transactions"


def test_two_blocks_at_one_height_can_coexist(repo):
    """
    Keying by hash is what preserves the evidence of a reorg. A height-keyed
    table could hold only one of these.
    """
    repo.save(block_at(100, "a"))
    repo.save(block_at(100, "b"))

    assert len(repo.at_height("ethereum", 100, include_withdrawn=True)) == 2


# ==============================================================================
# PRECISION
# ==============================================================================

def test_a_value_beyond_the_64_bit_ceiling_round_trips(repo):
    """
    The corruption this schema exists to prevent: an INTEGER column truncates
    here, the write succeeds, and the largest transfer on the chain reads small.
    """
    huge = 10**24
    assert huge > SQLITE_INTEGER_MAX

    block = block_at(100, transactions=[transaction_at(100, value=huge)])
    repo.save(block)

    assert repo.transactions_of(block)[0].value.raw == huge


def test_largest_transfers_orders_by_true_magnitude(repo):
    """
    The payoff for zero padding. Unpadded text would order "9…" above "10…" and
    this query would return small transfers labelled as the biggest.
    """
    values = [9 * 10**18, 10 * 10**18, 10**24, 5]
    transactions = [transaction_at(100, i, value=v) for i, v in enumerate(values)]
    repo.save(block_at(100, transactions=transactions))

    largest = repo.largest_transfers("ethereum", limit=4)
    returned = [tx.value.raw for tx in largest]

    assert returned == sorted(values, reverse=True)


# ==============================================================================
# WRITES — why a block is incomplete, not just that it is
# ==============================================================================

def test_the_incompleteness_reason_is_stored_beside_the_flag(repo):
    """
    Not derivable afterwards, which is the whole reason it is a column.

    A block filtered at a floor and a block fetched without expansion both
    arrive at storage with fewer transactions than they count. Only the capture
    knows which happened, so if it does not say, nothing later can.
    """
    repo.save(
        block_at(100),
        complete=False,
        incomplete_reason="selective_capture",
        capture_floor=Amount(13 * 10**18),
    )

    row = repo.database.connection.execute(
        "SELECT complete, incomplete_reason, capture_floor FROM blocks"
    ).fetchone()

    assert row["complete"] == 0
    assert row["incomplete_reason"] == "selective_capture"
    assert Amount.from_stored(row["capture_floor"]).raw == 13 * 10**18


def test_a_block_captured_whole_records_no_reason_and_no_floor(repo):
    """An empty reason must mean "nothing was missing", not "nobody looked"."""
    repo.save(block_at(100))

    row = repo.database.connection.execute(
        "SELECT incomplete_reason, capture_floor FROM blocks"
    ).fetchone()

    assert row["incomplete_reason"] == ""
    assert row["capture_floor"] == ""


def test_the_stored_floor_is_padded_so_the_maximum_is_numeric(repo):
    """
    The window reports the highest floor in force, and takes it with MAX() over
    text. Unpadded, MAX() would return the longest string: a floor of 9 wei
    would outrank one of 10 ether and the window would claim a stronger
    absence than it holds.
    """
    repo.save(block_at(100, "a"), complete=False, capture_floor=Amount(9))
    repo.save(block_at(101, "a"), complete=False, capture_floor=Amount(10 * 10**18))

    row = repo.database.connection.execute(
        "SELECT MAX(capture_floor) AS floor FROM blocks"
    ).fetchone()

    assert Amount.from_stored(row["floor"]).raw == 10 * 10**18


# ==============================================================================
# READS — the canonical default
# ==============================================================================

def test_withdrawal_flags_rather_than_deletes(repo):
    """Deleting would erase the evidence that a reorg happened at all."""
    repo.save(block_at(100))
    assert repo.withdraw("ethereum", [100]) == 1

    assert repo.count("ethereum") == 0
    assert repo.count("ethereum", include_withdrawn=True) == 1

    stored = repo.at_height("ethereum", 100, include_withdrawn=True)[0]
    assert not stored.canonical
    assert stored.withdrawn_at is not None


def test_reads_exclude_withdrawn_blocks_by_default(repo):
    """
    The most consequential default in the package: a forgotten filter must fail
    safe, so abandoned history is invisible unless explicitly requested.
    """
    repo.save(block_at(100))
    repo.withdraw("ethereum", [100])

    assert repo.highest("ethereum") is None
    assert repo.at_height("ethereum", 100) == ()


def test_largest_transfers_ignores_withdrawn_blocks(repo):
    repo.save(block_at(100, transactions=[transaction_at(100, value=10**24)]))
    repo.withdraw("ethereum", [100])

    assert repo.largest_transfers("ethereum") == ()


def test_highest_reports_how_far_storage_got(repo):
    for number in (100, 101, 102):
        repo.save(block_at(number))

    highest = repo.highest("ethereum")
    assert highest is not None
    assert highest.number == 102


def test_address_activity_matches_the_normalized_form(repo):
    """
    A checksummed literal compared against stored lowercase returns nothing,
    which reads as an address with no history.
    """
    repo.save(block_at(100, transactions=[transaction_at(100)]))
    checksummed = Address.parse("0x" + "2" * 40, "ethereum")

    assert len(repo.activity_of(checksummed)) == 1


def test_withdrawing_nothing_is_not_an_error(repo):
    assert repo.withdraw("ethereum", []) == 0


# ==============================================================================
# WRITER
# ==============================================================================

def raw_record(number: int, tag: str = "a", *, txs: int = 0) -> RawRecord:
    payload = {
        "number": hex(number),
        "hash": f"0x{tag}{number:06d}",
        "parentHash": f"0x{tag}{number - 1:06d}",
        "timestamp": hex(TIMESTAMP + number * 12),
        "gasUsed": "0x5208",
        "gasLimit": "0x1c9c380",
        "transactions": [
            {
                "hash": f"0xtx{tag}{number:04d}{i:02d}",
                "from": "0x" + "1" * 40,
                "to": "0x" + "2" * 40,
                "value": hex(10**18),
                "transactionIndex": hex(i),
                "input": "0x",
            }
            for i in range(txs)
        ],
    }
    return RawRecord(
        chain="ethereum",
        kind=RecordKind.BLOCK,
        payload=payload,
        height=number,
        provenance=Provenance("publicnode", "ethereum", "eth_getBlockByNumber", "ok"),
    )


def test_consume_drains_the_whole_queue_not_one_batch(repo):
    """
    The regression for a silent hole in a window that reported itself whole.

    `consume` used to drain once and return, so anything past `batch` stayed in
    a queue that dies with the process. The poller advances the checkpoint when
    a record is *queued*, not when it is written, so those heights were recorded
    as done and never fetched again. In practice: a 100-block run with tokens
    queued 200 records, one 64-record drain stored 32 blocks, and the 68 heights
    between became a permanent gap that `contiguous` still called clean.

    `batch` sizes the commit. It must never size the run.
    """
    queue: RecordQueue = RecordQueue(capacity=256)
    for number in range(100, 200):
        queue.put(raw_record(number, txs=1))

    writer = RecordWriter(repo)
    report = writer.consume([], queue, batch=8)

    assert report.written == 100, "every queued record must reach storage"
    assert len(queue) == 0, "nothing may be left behind for the process to drop"

    stored = [row["number"] for row in repo.database.connection.execute(
        "SELECT number FROM blocks WHERE canonical = 1 ORDER BY number"
    )]
    assert stored == list(range(100, 200)), "the stored range must have no holes"


def test_writer_stores_a_captured_record(repo):
    writer = RecordWriter(repo)
    result = writer.write(raw_record(100, txs=2))

    assert result.storable
    assert writer.stats.written == 1
    assert writer.stats.transactions_written == 2


def test_writer_keeps_rejections_instead_of_dropping_them(repo):
    """
    A rising rejection count is the only thing distinguishing a provider serving
    junk from a chain that went quiet.
    """
    writer = RecordWriter(repo)
    broken = raw_record(100)
    del broken.payload["hash"]

    queue: RecordQueue[RawRecord] = RecordQueue()
    queue.put(broken)
    report = writer.drain(queue)

    assert report.written == 0
    assert len(report.rejections) == 1
    assert report.rejections[0].issues


def test_writer_drains_a_batch(repo):
    writer = RecordWriter(repo)
    queue: RecordQueue[RawRecord] = RecordQueue()
    for number in range(100, 105):
        queue.put(raw_record(number))

    report = writer.drain(queue)

    assert report.drained == 5
    assert report.written == 5
    assert repo.count("ethereum") == 5


def test_quality_labels_reach_the_stored_row(db, repo):
    """A reader must be able to tell a quiet block from an unexpanded one."""
    writer = RecordWriter(repo)
    unexpanded = raw_record(100)
    unexpanded.payload["transactions"] = ["0xaa", "0xbb"]
    writer.write(unexpanded)

    row = db.connection.execute("SELECT complete FROM blocks").fetchone()
    assert row["complete"] == 0


# ==============================================================================
# WRITER — reorg ordering
# ==============================================================================

def ref_of(number: int, tag: str = "a") -> BlockRef:
    return BlockRef(
        number=number,
        hash=f"0x{tag}{number:06d}",
        parent_hash=f"0x{tag}{number - 1:06d}",
    )


def reorg_result(
    *, height: int, withdrawn: tuple[int, ...], tag: str = "a", new_tag: str = "b"
) -> PollResult:
    """A reorg result shaped exactly as BlockPoller emits one."""
    event = ReorgEvent(
        chain="ethereum",
        depth=len(withdrawn),
        new_tip=ref_of(height, new_tag),
        orphaned=tuple(ref_of(n, tag) for n in withdrawn),
        common_ancestor=min(withdrawn) - 1,
    )
    return PollResult(
        PollStatus.REORG,
        "ethereum",
        height=height,
        reorg=event,
        withdrawn=withdrawn,
    )


def test_reorg_withdraws_before_the_replacement_is_stored(repo):
    writer = RecordWriter(repo)
    writer.write(raw_record(100, "a"))

    queue: RecordQueue[RawRecord] = RecordQueue()
    queue.put(raw_record(100, "b"))

    writer.consume([reorg_result(height=100, withdrawn=(100,))], queue)

    canonical = repo.at_height("ethereum", 100)
    assert len(canonical) == 1, "exactly one block may be canonical at a height"
    assert canonical[0].block_hash == "0xb000100"
    assert len(repo.at_height("ethereum", 100, include_withdrawn=True)) == 2


def test_the_replacement_survives_a_purge_at_its_own_height(repo):
    """
    Purging by height rather than hash throws away the replacing block, which
    sits at a withdrawn height too. The checkpoint has already advanced past it,
    so nothing re-fetches it and the height stays permanently empty.
    """
    writer = RecordWriter(repo)
    queue: RecordQueue[RawRecord] = RecordQueue()
    queue.put(raw_record(100, "b"))  # the replacement, at a withdrawn height

    writer.apply(reorg_result(height=100, withdrawn=(100,)), queue=queue)

    assert len(queue) == 1, "the replacement must not be purged"
    assert queue.discarded == 0


def test_a_reorg_purges_records_it_invalidated_while_queued(repo):
    """
    The hazard the queue creates: records captured on the abandoned branch may
    still be buffered when the fork is found. The withdrawal cannot reach them
    because they are not rows yet, so a later drain would insert abandoned
    blocks marked canonical.
    """
    writer = RecordWriter(repo)
    queue: RecordQueue[RawRecord] = RecordQueue()
    queue.put(raw_record(101, "a"))  # captured on the branch about to die
    queue.put(raw_record(102, "a"))

    writer.consume([reorg_result(height=102, withdrawn=(101, 102))], queue)

    assert repo.count("ethereum") == 0, "abandoned captures must not be stored"
    assert queue.discarded == 2


def test_purging_leaves_records_from_other_heights_alone(repo):
    writer = RecordWriter(repo)
    queue: RecordQueue[RawRecord] = RecordQueue()
    queue.put(raw_record(100, "a"))
    queue.put(raw_record(101, "a"))

    writer.consume([reorg_result(height=101, withdrawn=(101,))], queue)

    stored = repo.highest("ethereum")
    assert stored is not None and stored.number == 100


def test_purging_leaves_other_chains_alone(repo):
    writer = RecordWriter(repo)
    queue: RecordQueue[RawRecord] = RecordQueue()
    polygon = raw_record(101, "a")
    object.__setattr__(polygon, "chain", "polygon")
    queue.put(polygon)

    writer.apply(reorg_result(height=101, withdrawn=(101,)), queue=queue)

    assert queue.discarded == 0


def test_a_reorg_result_without_an_event_purges_nothing(repo):
    """
    Refusing to guess leaves a recoverable duplicate rather than an
    unrecoverable gap.
    """
    writer = RecordWriter(repo)
    queue: RecordQueue[RawRecord] = RecordQueue()
    queue.put(raw_record(101, "a"))

    bare = PollResult(PollStatus.REORG, "ethereum", height=101, withdrawn=(101,))
    writer.apply(bare, queue=queue)

    assert queue.discarded == 0


def test_writer_health_reports_both_stages(repo):
    writer = RecordWriter(repo)
    writer.write(raw_record(100))

    health = writer.health()
    assert health["writer"]["written"] == 1
    assert health["normalizer"]["accepted"] == 1
