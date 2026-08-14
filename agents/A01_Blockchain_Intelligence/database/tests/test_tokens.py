"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for token and NFT storage.

Two properties carry this file. The first is that a token transfer disappears
from canonical reads when its block is withdrawn — a movement on an abandoned
branch reads exactly like a live one, and nothing about the row says otherwise.
The second is that raw amounts are never ordered across tokens, because until
decimals are resolved that ranking is decided by which contract uses more
digits.
"""

from __future__ import annotations

import pytest

from database import (
    Database,
    RecordWriter,
    SqliteBlockRepository,
    SqliteTokenRepository,
)
from database.migrations import CURRENT_VERSION, migrate
from schemas import Address, Amount
from schemas.token import CanonicalNftTransfer, CanonicalTokenTransfer, TokenActivity
from sensors.envelope import Provenance, RawRecord, RecordKind

CHAIN = "ethereum"
ALICE = "0x" + "a1" * 20
BOB = "0x" + "b2" * 20
USDC = "0x" + "c6" * 20          # 6 decimals in reality
BIGTOKEN = "0x" + "d8" * 20      # 18 decimals in reality
TRANSFER_SIG = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


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


def transfer(
    *, number=100, tag="a", token=USDC, value=1_000_000, index=0, sender=ALICE, to=BOB
) -> CanonicalTokenTransfer:
    return CanonicalTokenTransfer(
        chain=CHAIN,
        tx_hash=f"0xtx{index:04d}",
        log_index=index,
        block_number=number,
        block_hash=block_hash(number, tag),
        token=Address.parse(token, CHAIN),
        from_address=Address.parse(sender, CHAIN),
        to_address=Address.parse(to, CHAIN),
        value=Amount(value, decimals=0),
    )


def activity(*transfers, number=100, tag="a", nfts=()) -> TokenActivity:
    return TokenActivity(
        chain=CHAIN,
        block_number=number,
        block_hash=block_hash(number, tag),
        transfers=tuple(transfers),
        nft_transfers=tuple(nfts),
    )


@pytest.fixture
def stored():
    """A database with block 100 stored, ready to receive its logs."""
    with Database() as db:
        RecordWriter(SqliteBlockRepository(db)).write(block_record(100))
        yield db, SqliteTokenRepository(db), SqliteBlockRepository(db)


# ==============================================================================
# SCHEMA
# ==============================================================================

def test_a_fresh_database_has_the_token_tables():
    with Database() as db:
        assert db.schema_version() == CURRENT_VERSION
        names = {
            row[0]
            for row in db.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"token_transfers", "nft_transfers"} <= names


def test_a_v1_database_upgrades_without_losing_blocks(tmp_path):
    """
    Forward-only migration. An operator with history already stored must not
    have to choose between token support and their data.

    The v1 row is inserted with v1's own column list rather than through the
    repository. The repository writes today's schema -- that is its job -- so
    using it here would be staging the old database with a new build's INSERT,
    and the test would break every time a column is added without anything
    being wrong with the migration it exists to check.
    """
    path = tmp_path / "old.db"
    with Database(path, migrate_on_open=False) as old:
        migrate(old.connection, target=1)
        with old.transaction() as connection:
            connection.execute(
                """
                INSERT INTO blocks (
                    key, chain, number, block_hash, parent_hash, timestamp,
                    tx_count, canonical, observed_at, complete, plausible
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, 1, 1)
                """,
                (
                    f"{CHAIN}:{block_hash(100)}",
                    CHAIN,
                    100,
                    block_hash(100),
                    block_hash(99),
                    "2023-11-14T22:13:20+00:00",
                    0,
                    "2023-11-14T22:13:20+00:00",
                ),
            )

    with Database(path) as upgraded:
        assert upgraded.schema_version() == CURRENT_VERSION
        assert SqliteBlockRepository(upgraded).count(CHAIN) == 1


# ==============================================================================
# WRITING
# ==============================================================================

def test_transfers_are_stored(stored):
    _, tokens, _ = stored
    outcome = tokens.save(activity(transfer(index=0), transfer(index=1)))

    assert outcome.transfers_written == 2
    assert tokens.count(CHAIN) == 2


def test_two_transfers_in_one_transaction_both_survive(stored):
    """
    A swap routed through two pools emits the same transfer twice. Keying on
    the transaction hash alone would drop the second as a duplicate.
    """
    _, tokens, _ = stored
    first = transfer(index=0)
    second = CanonicalTokenTransfer(
        chain=CHAIN,
        tx_hash=first.tx_hash,  # same transaction
        log_index=1,            # different log
        block_number=100,
        block_hash=block_hash(100),
        token=first.token,
        from_address=first.from_address,
        to_address=first.to_address,
        value=first.value,
    )

    tokens.save(activity(first, second))
    assert tokens.count(CHAIN) == 2


def test_replaying_a_block_writes_nothing_new(stored):
    _, tokens, _ = stored
    batch = activity(transfer(index=0))

    tokens.save(batch)
    tokens.save(batch)

    assert tokens.count(CHAIN) == 1


def test_a_transfer_for_an_unstored_block_is_counted_not_inserted(stored):
    """
    Logs can arrive for a block ingestion has not reached. The foreign key
    would reject them anyway; catching it lets the rest of the batch land and
    turns a hard failure into a measurable gap.
    """
    _, tokens, _ = stored
    outcome = tokens.save(
        activity(transfer(index=0), transfer(index=1, number=999), number=100)
    )

    assert outcome.transfers_written == 1
    assert outcome.orphaned == 1


def test_a_huge_token_amount_round_trips(stored):
    """Token amounts hit the same 64-bit ceiling native values do."""
    _, tokens, _ = stored
    huge = 10**30
    tokens.save(activity(transfer(value=huge)))

    assert tokens.largest_transfers(CHAIN, USDC)[0].value.raw == huge


def test_nft_transfers_are_stored_with_their_token_id(stored):
    _, tokens, _ = stored
    nft = CanonicalNftTransfer(
        chain=CHAIN,
        tx_hash="0xnft1",
        log_index=0,
        block_number=100,
        block_hash=block_hash(100),
        collection=Address.parse(BIGTOKEN, CHAIN),
        from_address=Address.parse(ALICE, CHAIN),
        to_address=Address.parse(BOB, CHAIN),
        token_id=2**200,  # far past 64 bits
    )
    tokens.save(activity(nfts=(nft,)))

    found = tokens.nft_activity_of(Address.parse(ALICE, CHAIN))
    assert len(found) == 1
    assert found[0].token_id == 2**200, "a truncated tokenId points at a different NFT"


# ==============================================================================
# THE REORG CASCADE
# ==============================================================================

def test_token_transfers_vanish_from_canonical_reads_when_their_block_is_withdrawn(stored):
    """
    The property that matters most here. A transfer on an abandoned branch is
    indistinguishable from a live one by inspection, so the block linkage has
    to do the work.
    """
    _, tokens, blocks = stored
    tokens.save(activity(transfer(index=0), transfer(index=1)))
    assert tokens.count(CHAIN) == 2

    blocks.withdraw(CHAIN, [100])

    assert tokens.count(CHAIN) == 0
    assert tokens.count(CHAIN, include_withdrawn=True) == 2


def test_a_withdrawn_transfer_is_retained_not_deleted(stored):
    """Deleting would erase the evidence that the movement was ever observed."""
    _, tokens, blocks = stored
    tokens.save(activity(transfer()))
    blocks.withdraw(CHAIN, [100])

    assert tokens.count(CHAIN, include_withdrawn=True) == 1


def test_address_activity_excludes_withdrawn_transfers(stored):
    _, tokens, blocks = stored
    tokens.save(activity(transfer()))
    blocks.withdraw(CHAIN, [100])

    assert tokens.activity_of(Address.parse(ALICE, CHAIN)) == ()


def test_largest_transfers_excludes_withdrawn_by_default(stored):
    _, tokens, blocks = stored
    tokens.save(activity(transfer(value=10**24)))
    blocks.withdraw(CHAIN, [100])

    assert tokens.largest_transfers(CHAIN, USDC) == ()


# ==============================================================================
# THE CROSS-TOKEN TRAP
# ==============================================================================

def test_largest_transfers_requires_a_token(stored):
    """
    Not a convenience filter. 1,000,000 USDC units is one dollar; 1,000,000
    units of an 18-decimal token is a millionth of one. A chain-wide ordering
    of raw amounts ranks by which contract uses more digits.
    """
    _, tokens, _ = stored

    with pytest.raises(TypeError):
        tokens.largest_transfers(CHAIN)  # type: ignore[call-arg]


def test_ordering_within_one_token_is_by_true_magnitude(stored):
    _, tokens, _ = stored
    values = [5, 9 * 10**18, 10 * 10**18, 10**24]
    tokens.save(
        activity(*[transfer(index=i, value=v) for i, v in enumerate(values)])
    )

    ordered = [t.value.raw for t in tokens.largest_transfers(CHAIN, USDC, limit=4)]
    assert ordered == sorted(values, reverse=True)


def test_a_small_usdc_transfer_outranks_a_large_one_only_within_usdc(stored):
    """
    Both tokens present. The 18-decimal token's raw amounts dwarf USDC's, and
    scoping is what stops that being read as importance.
    """
    _, tokens, _ = stored
    tokens.save(
        activity(
            transfer(index=0, token=USDC, value=1_000_000_000),      # 1000 USDC
            transfer(index=1, token=BIGTOKEN, value=10**18),         # 1 token
        )
    )

    assert tokens.largest_transfers(CHAIN, USDC)[0].value.raw == 1_000_000_000
    assert tokens.largest_transfers(CHAIN, BIGTOKEN)[0].value.raw == 10**18


def test_stored_transfers_report_their_scale_as_unknown(stored):
    """The flag is what stops a reader treating a raw integer as a quantity."""
    _, tokens, _ = stored
    tokens.save(activity(transfer()))

    assert tokens.largest_transfers(CHAIN, USDC)[0].decimals_known is False


# ==============================================================================
# READS
# ==============================================================================

def test_tokens_seen_ranks_by_activity(stored):
    _, tokens, _ = stored
    tokens.save(
        activity(
            transfer(index=0, token=USDC),
            transfer(index=1, token=USDC),
            transfer(index=2, token=BIGTOKEN),
        )
    )

    seen = tokens.tokens_seen(CHAIN)
    assert seen[0] == (USDC, 2)


def test_address_activity_matches_the_folded_form(stored):
    """A checksummed literal against stored lowercase returns nothing."""
    _, tokens, _ = stored
    tokens.save(activity(transfer()))

    assert len(tokens.activity_of(Address.parse(ALICE.upper(), CHAIN))) == 1


def test_an_empty_activity_writes_nothing(stored):
    _, tokens, _ = stored
    outcome = tokens.save(activity())

    assert outcome.total == 0


# ==============================================================================
# THROUGH THE WRITER
# ==============================================================================

def test_the_writer_stores_logs_end_to_end():
    """Sensor record → normalization → token repository, as ingestion runs it."""
    def topic(address: str) -> str:
        return "0x" + address[2:].rjust(64, "0")

    with Database() as db:
        tokens = SqliteTokenRepository(db)
        writer = RecordWriter(SqliteBlockRepository(db), tokens=tokens)
        writer.write(block_record(100))

        logs = RawRecord(
            chain=CHAIN,
            kind=RecordKind.LOGS,
            height=100,
            provenance=Provenance("fixture", CHAIN, "eth_getLogs", "ok"),
            payload=[
                {
                    "address": USDC,
                    "topics": [TRANSFER_SIG, topic(ALICE), topic(BOB)],
                    "data": "0x" + f"{1_000_000:064x}",
                    "transactionHash": "0xtx01",
                    "blockHash": block_hash(100),
                    "blockNumber": hex(100),
                    "logIndex": "0x0",
                }
            ],
        )
        writer.write(logs)

        assert writer.stats.token_transfers_written == 1
        assert tokens.count(CHAIN) == 1


def test_the_writer_without_a_token_repository_stores_blocks_only():
    """
    A caller ingesting blocks only must not be forced to carry the token
    schema — but the discarded records are logged rather than assumed away.
    """
    with Database() as db:
        writer = RecordWriter(SqliteBlockRepository(db))  # no tokens
        writer.write(block_record(100))

        assert writer.stats.token_transfers_written == 0
        assert SqliteBlockRepository(db).count(CHAIN) == 1
