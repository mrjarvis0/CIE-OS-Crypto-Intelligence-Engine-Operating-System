"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for approval storage and the read path that feeds exposure screening.

Two properties carry this file. The first is that a stored grant round-trips
back into the exact :class:`DecodedApproval` the replay expects, so wiring the
schema in changed nothing about what the exposure screen concludes -- the
decoder and the replay were proven before storage existed, and storage must
not quietly reinterpret them. The second is that a grant on a withdrawn block
disappears from the screen: an approval on an abandoned branch was never made
on the chain A01 believes in, and reporting it would tell an owner to revoke
something that does not exist.
"""

from __future__ import annotations

import pytest

from blockchain.security.approval_risk import (
    ApprovalKind,
    UNLIMITED_THRESHOLD,
    exposure_for_owner,
)
from database import (
    Database,
    RecordWriter,
    SqliteApprovalRepository,
    SqliteBlockRepository,
)
from database.migrations import CURRENT_VERSION
from normalization.approvals import normalize_approvals
from schemas import Address
from sensors.envelope import Provenance, RawRecord, RecordKind
from contracts.signatures import APPROVAL_FOR_ALL_TOPIC, APPROVAL_TOPIC

CHAIN = "ethereum"
OWNER = "0x" + "11" * 20
SPENDER = "0x" + "22" * 20
OTHER_SPENDER = "0x" + "33" * 20
TOKEN = "0x" + "44" * 20
ZERO = "0x" + "00" * 20


def block_hash(number: int, tag: str = "a") -> str:
    return f"0x{tag}{number:06d}"


def block_record(number: int, tag: str = "a") -> RawRecord:
    return RawRecord(
        chain=CHAIN,
        kind=RecordKind.BLOCK,
        height=number,
        provenance=Provenance("fixture", CHAIN, "eth_getBlockByNumber", "ok"),
        payload={
            "number": hex(number),
            "hash": block_hash(number, tag),
            "parentHash": block_hash(number - 1, tag),
            "timestamp": hex(1_700_000_000 + number * 12),
            "transactions": [],
        },
    )


def word(address: str) -> str:
    return "0x" + address[2:].rjust(64, "0")


def data_word(value: int) -> str:
    return "0x" + format(value, "064x")


def erc20_log(
    *, spender=SPENDER, value=1000, block=100, index=0, tag="a", tx="0xtx0"
) -> dict:
    return {
        "address": TOKEN,
        "topics": [APPROVAL_TOPIC, word(OWNER), word(spender)],
        "data": data_word(value),
        "blockNumber": block,
        "logIndex": index,
        "blockHash": block_hash(block, tag),
        "transactionHash": tx,
    }


def for_all_log(
    *, operator=SPENDER, approved=True, block=100, index=1, tag="a", tx="0xtx1"
) -> dict:
    return {
        "address": TOKEN,
        "topics": [APPROVAL_FOR_ALL_TOPIC, word(OWNER), word(operator)],
        "data": data_word(1 if approved else 0),
        "blockNumber": block,
        "logIndex": index,
        "blockHash": block_hash(block, tag),
        "transactionHash": tx,
    }


@pytest.fixture
def stored():
    """A database with block 100 stored, ready to receive its approvals."""
    with Database() as db:
        RecordWriter(SqliteBlockRepository(db)).write(block_record(100))
        yield db, SqliteApprovalRepository(db), SqliteBlockRepository(db)


# ==============================================================================
# SCHEMA
# ==============================================================================

def test_a_fresh_database_has_the_approvals_table():
    with Database() as db:
        assert db.schema_version() == CURRENT_VERSION
        names = {
            row[0]
            for row in db.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "approvals" in names


# ==============================================================================
# NORMALIZATION
# ==============================================================================

def test_normalize_binds_each_approval_to_its_block_hash():
    activity, issues = normalize_approvals(
        [erc20_log(), for_all_log()], chain=CHAIN, source_record_id="rec-1"
    )
    assert issues == ()
    assert activity is not None
    assert len(activity.approvals) == 2
    assert {record.block_hash for record in activity.approvals} == {block_hash(100)}


def test_an_approval_without_block_linkage_is_refused_not_stored():
    log = erc20_log()
    del log["blockHash"]
    activity, issues = normalize_approvals([log], chain=CHAIN)
    assert activity is not None
    assert activity.approvals == ()
    assert len(issues) == 1
    assert "block linkage" in issues[0].message


def test_a_transfer_log_is_not_counted_as_an_undecoded_approval():
    """A batch is transfers and approvals side by side; only approval-shaped
    logs that fail to decode count against this path."""
    transfer = {
        "address": TOKEN,
        "topics": [
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
            word(OWNER),
            word(SPENDER),
        ],
        "data": data_word(5),
        "blockNumber": 100,
        "logIndex": 9,
        "blockHash": block_hash(100),
        "transactionHash": "0xtx9",
    }
    activity, _ = normalize_approvals([transfer, erc20_log()], chain=CHAIN)
    assert len(activity.approvals) == 1
    assert activity.undecoded == 0


# ==============================================================================
# STORAGE ROUND-TRIP
# ==============================================================================

def _capture(db, *logs, source="rec"):
    activity, _ = normalize_approvals(list(logs), chain=CHAIN, source_record_id=source)
    return SqliteApprovalRepository(db).save(activity)


def test_stored_grants_round_trip_into_the_exposure_screen(stored):
    db, approvals, _ = stored
    outcome = _capture(
        db,
        erc20_log(value=UNLIMITED_THRESHOLD, index=0),
        for_all_log(index=1),
    )
    assert outcome.written == 2
    assert outcome.orphaned == 0

    grants = approvals.approvals_for_owner(Address.parse(OWNER, CHAIN))
    report = exposure_for_owner(grants, owner=OWNER, chain=CHAIN)

    assert report.total == 2
    # The unlimited ERC-20 allowance and the collection-wide grant both survive
    # the round trip through padded text and the kind column.
    assert len(report.unlimited) == 2
    assert len(report.collection_wide) == 1
    assert {g.kind for g in report.live} == {
        ApprovalKind.ERC20,
        ApprovalKind.ERC721_ALL,
    }


def test_a_revocation_replays_over_the_grant_it_withdraws(stored):
    db, approvals, _ = stored
    _capture(db, erc20_log(value=1000, index=0))
    # Same spender, allowance zeroed at a later log: a revocation.
    _capture(db, erc20_log(value=0, index=1, tx="0xtx2"))

    grants = approvals.approvals_for_owner(Address.parse(OWNER, CHAIN))
    report = exposure_for_owner(grants, owner=OWNER, chain=CHAIN)

    assert report.total == 0
    assert report.revoked == 1


def test_writes_are_idempotent_on_log_position(stored):
    db, approvals, _ = stored
    _capture(db, erc20_log(index=0))
    second = _capture(db, erc20_log(index=0))
    # The write is reported as attempted, but the row is not duplicated.
    assert approvals.count(CHAIN) == 1


def test_a_second_spender_does_not_displace_the_first(stored):
    db, approvals, _ = stored
    _capture(
        db,
        erc20_log(spender=SPENDER, index=0, tx="0xa"),
        erc20_log(spender=OTHER_SPENDER, index=1, tx="0xb"),
    )
    grants = approvals.approvals_for_owner(Address.parse(OWNER, CHAIN))
    report = exposure_for_owner(grants, owner=OWNER, chain=CHAIN)
    assert {g.spender for g in report.live} == {SPENDER.lower(), OTHER_SPENDER.lower()}


# ==============================================================================
# REORG SAFETY
# ==============================================================================

def test_a_grant_on_a_withdrawn_block_leaves_the_screen(stored):
    db, approvals, blocks = stored
    _capture(db, erc20_log(index=0))
    assert approvals.count(CHAIN) == 1

    blocks.withdraw(CHAIN, [100])

    grants = approvals.approvals_for_owner(Address.parse(OWNER, CHAIN))
    assert grants == ()
    assert approvals.count(CHAIN) == 0
    assert approvals.count(CHAIN, include_withdrawn=True) == 1


def test_an_approval_for_an_unstored_block_is_counted_not_inserted(stored):
    db, approvals, _ = stored
    outcome = _capture(db, erc20_log(block=999, index=0, tag="z"))
    assert outcome.written == 0
    assert outcome.orphaned == 1
    assert approvals.count(CHAIN) == 0


# ==============================================================================
# INGESTION WIRING
# ==============================================================================

def logs_record(*logs) -> RawRecord:
    return RawRecord(
        chain=CHAIN,
        kind=RecordKind.LOGS,
        height=100,
        provenance=Provenance("fixture", CHAIN, "eth_getLogs", "ok"),
        payload=list(logs),
    )


def test_a_writer_with_an_approval_repository_captures_from_the_log_batch():
    with Database() as db:
        approvals = SqliteApprovalRepository(db)
        writer = RecordWriter(SqliteBlockRepository(db), approvals=approvals)
        writer.write(block_record(100))
        writer.write(logs_record(erc20_log(index=0), for_all_log(index=1)))

        assert writer.stats.approvals_written == 2
        grants = approvals.approvals_for_owner(Address.parse(OWNER, CHAIN))
        report = exposure_for_owner(grants, owner=OWNER, chain=CHAIN)
        assert report.total == 2


def test_a_writer_without_an_approval_repository_stores_no_approvals():
    """The capture is opt-in: a writer that predates the schema is unchanged."""
    with Database() as db:
        writer = RecordWriter(SqliteBlockRepository(db))
        writer.write(block_record(100))
        writer.write(logs_record(erc20_log(index=0)))

        assert writer.stats.approvals_written == 0
        assert SqliteApprovalRepository(db).count(CHAIN) == 0
