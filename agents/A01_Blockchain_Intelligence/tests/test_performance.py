"""
CIE-OS
A01 Blockchain Intelligence Agent

Performance budgets over recorded mainnet data.

`identity/non_functional_requirements.md` asks for bounded processing cost, and
a budget nobody measures is a wish. These tests do not chase a benchmark
number — they assert that the shape of the cost has not changed, which is the
regression that actually happens: an accidental O(n²) in an aggregate, or a
query that stops using its index and degrades to a scan.

Budgets are deliberately loose. A tight threshold on shared CI hardware fails
for reasons unrelated to the code, and a flaky performance test gets deleted.
These are set to catch an order-of-magnitude regression, which is the kind that
matters and the kind a loose bound still catches.
"""

from __future__ import annotations

import time

import pytest

from database import Database, RecordWriter, SqliteAnalyticsRepository, SqliteBlockRepository
from decision import DecisionEngine
from fixtures.replay import Recording, ReplaySensor
from ingestion import BlockPoller, InMemoryCheckpointStore, RecordQueue
from intelligence.core.engine import IntelligenceEngine
from intelligence.engines import SubjectComposer
from schemas import Address

#: Seconds allowed to ingest, normalize and store one real mainnet block with
#: its full transaction set. Roughly 500 transactions each.
INGEST_BUDGET_PER_BLOCK = 2.0

#: Seconds allowed for one full read-side investigation over stored history.
INVESTIGATE_BUDGET = 5.0

#: Seconds allowed for one indexed address lookup. Generous, but an index that
#: stopped being used would blow through it on a table of this size.
LOOKUP_BUDGET = 1.0


@pytest.fixture(scope="module")
def loaded():
    """Six recorded blocks in storage, with the ingest time recorded."""
    recording = Recording.named("ethereum_mainnet")
    sensor = ReplaySensor(recording)
    queue: RecordQueue = RecordQueue(capacity=64)
    poller = BlockPoller(
        sensor,
        queue=queue,
        checkpoints=InMemoryCheckpointStore(),
        start_height=recording.heights[0],
        include_transactions=True,
        confirmations=0,
    )

    with Database() as db:
        writer = RecordWriter(SqliteBlockRepository(db))
        started = time.perf_counter()
        writer.consume(poller.run(max_steps=6), queue)
        elapsed = time.perf_counter() - started
        yield db, writer, elapsed


def test_ingesting_a_real_block_stays_within_budget(loaded):
    _, writer, elapsed = loaded
    per_block = elapsed / 6

    assert per_block < INGEST_BUDGET_PER_BLOCK, (
        f"{per_block:.2f}s per block against a {INGEST_BUDGET_PER_BLOCK}s budget; "
        f"{writer.stats.transactions_written} transactions stored"
    )


def test_a_full_investigation_stays_within_budget(loaded):
    db, _, _ = loaded

    started = time.perf_counter()
    composition = SubjectComposer().compose(
        SqliteAnalyticsRepository(db), chain="ethereum"
    )
    package = IntelligenceEngine().run(composition.subject)
    DecisionEngine().decide(package)
    elapsed = time.perf_counter() - started

    assert elapsed < INVESTIGATE_BUDGET, f"{elapsed:.2f}s"


def test_address_lookup_uses_its_index(loaded):
    """
    A scan would still return the right answer, just slowly — which is why this
    is a test rather than something anyone would notice.
    """
    db, _, _ = loaded
    analytics = SqliteAnalyticsRepository(db)
    biggest = SqliteBlockRepository(db).largest_transfers("ethereum", limit=1)[0]

    started = time.perf_counter()
    analytics.address_summary(biggest.from_address)
    elapsed = time.perf_counter() - started

    assert elapsed < LOOKUP_BUDGET, f"{elapsed:.2f}s"


def test_the_directional_indexes_are_actually_planned(loaded):
    """
    Asserts the query plan, not the clock. A timing test on a small fixture
    passes even after an index is dropped; the plan says whether it was used.
    """
    db, _, _ = loaded
    address = "0x" + "1" * 40

    plan = db.connection.execute(
        """
        EXPLAIN QUERY PLAN
        SELECT t.* FROM transactions t
          JOIN blocks b ON b.key = t.block_key
         WHERE t.chain = ? AND b.canonical = 1 AND t.from_address = ?
         ORDER BY t.block_number DESC
        """,
        ("ethereum", address),
    ).fetchall()

    detail = " ".join(str(row["detail"]) for row in plan)
    assert "idx_tx_from" in detail, detail


def test_the_largest_transfer_query_is_planned_on_its_index(loaded):
    db, _, _ = loaded

    plan = db.connection.execute(
        """
        EXPLAIN QUERY PLAN
        SELECT t.* FROM transactions t
          JOIN blocks b ON b.key = t.block_key
         WHERE t.chain = ? AND b.canonical = 1
         ORDER BY t.value DESC LIMIT 10
        """,
        ("ethereum",),
    ).fetchall()

    detail = " ".join(str(row["detail"]) for row in plan)
    assert "idx_tx_value" in detail, detail


def test_the_chain_progress_query_uses_the_partial_index(loaded):
    """The hot path: 'where is this chain up to', excluding withdrawn blocks."""
    db, _, _ = loaded

    plan = db.connection.execute(
        """
        EXPLAIN QUERY PLAN
        SELECT * FROM blocks
         WHERE chain = ? AND canonical = 1
         ORDER BY number DESC LIMIT 1
        """,
        ("ethereum",),
    ).fetchall()

    detail = " ".join(str(row["detail"]) for row in plan)
    assert "idx_blocks_chain_number" in detail, detail


def test_the_value_population_scales_with_its_limit(loaded):
    """
    Bounded by the limit rather than by chain history. Unbounded, this grows
    forever and the whale skill gets slower every day it runs.
    """
    db, _, _ = loaded
    analytics = SqliteAnalyticsRepository(db)

    assert len(analytics.transfer_values("ethereum", limit=50)) <= 50


# ==============================================================================
# SCALING SHAPE
# ==============================================================================

def test_address_totals_are_bounded_not_linear():
    """
    The regression that matters is complexity, not constant factor. Summing an
    address's whole history is linear in its activity — measured at ~4-5
    microseconds per row — so an exchange hot wallet with millions of transfers
    would take seconds and grow forever. The cap bounds it; this proves the cap
    is what actually binds.
    """
    from database.analytics import MAX_SUM_ROWS
    from schemas import Amount

    hot = "0x" + "a1" * 20
    rows = MAX_SUM_ROWS + 5_000

    with Database() as db:
        connection = db.connection
        connection.execute("BEGIN")
        connection.execute(
            "INSERT INTO blocks (key,chain,number,block_hash,parent_hash,timestamp,"
            "tx_count,canonical,observed_at) VALUES "
            "('ethereum:0xb','ethereum',1,'0xb','0xa','2024-01-01T00:00:00+00:00',"
            f"{rows},1,'2024-01-01T00:00:00+00:00')"
        )
        connection.executemany(
            "INSERT INTO transactions (key,chain,tx_hash,block_key,block_number,"
            "tx_index,from_address,to_address,value,value_decimals) "
            "VALUES (?,'ethereum',?,'ethereum:0xb',1,?,?,?,?,18)",
            [
                (f"ethereum:0x{i:x}", f"0x{i:x}", i, hot, "0x" + "b2" * 20,
                 Amount(10**18).stored())
                for i in range(rows)
            ],
        )
        connection.execute("COMMIT")

        started = time.perf_counter()
        summary = SqliteAnalyticsRepository(db).address_summary(
            Address.parse(hot, "ethereum")
        )
        elapsed = time.perf_counter() - started

    assert summary.totals_capped, "the cap must bind at this volume"
    assert int(summary.sent_total.raw) == MAX_SUM_ROWS * 10**18
    assert elapsed < 2.0, f"{elapsed:.2f}s for {rows} rows"


def test_an_uncapped_address_reports_its_total_as_exact():
    """The flag must mean something: below the cap, the figure is the whole sum."""
    from schemas import Amount

    quiet = "0x" + "c3" * 20
    with Database() as db:
        connection = db.connection
        connection.execute("BEGIN")
        connection.execute(
            "INSERT INTO blocks (key,chain,number,block_hash,parent_hash,timestamp,"
            "tx_count,canonical,observed_at) VALUES "
            "('ethereum:0xc','ethereum',1,'0xc','0xb','2024-01-01T00:00:00+00:00',"
            "3,1,'2024-01-01T00:00:00+00:00')"
        )
        connection.executemany(
            "INSERT INTO transactions (key,chain,tx_hash,block_key,block_number,"
            "tx_index,from_address,to_address,value,value_decimals) "
            "VALUES (?,'ethereum',?,'ethereum:0xc',1,?,?,?,?,18)",
            [
                (f"ethereum:0xq{i}", f"0xq{i}", i, quiet, "0x" + "b2" * 20,
                 Amount(10**18).stored())
                for i in range(3)
            ],
        )
        connection.execute("COMMIT")

        summary = SqliteAnalyticsRepository(db).address_summary(
            Address.parse(quiet, "ethereum")
        )

    assert not summary.totals_capped
    assert int(summary.sent_total.raw) == 3 * 10**18
