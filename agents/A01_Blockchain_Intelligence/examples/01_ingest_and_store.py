"""
CIE-OS / A01 — Example 1: capture a chain into the system of record.

Runs offline against recorded mainnet blocks, so it works with no network, no
API key, and no live chain. The pipeline it drives is the real one:

    sensor -> ingestion -> normalization -> database

Run:
    python examples/01_ingest_and_store.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import Database, RecordWriter, SqliteBlockRepository  # noqa: E402
from fixtures.replay import Recording, ReplaySensor  # noqa: E402
from ingestion import BlockPoller, InMemoryCheckpointStore, RecordQueue  # noqa: E402


def main() -> int:
    logging.disable(logging.CRITICAL)

    # A recording of real Ethereum blocks, captured once and committed.
    recording = Recording.named("ethereum_mainnet")
    sensor = ReplaySensor(recording)

    print("Example 1 — capture into the system of record")
    print(f"  fixture   : {len(recording.blocks)} recorded blocks from {recording.chain}")
    print(f"  heights   : {recording.heights[0]}–{recording.heights[-1]}")

    queue: RecordQueue = RecordQueue(capacity=32)
    poller = BlockPoller(
        sensor,
        queue=queue,
        checkpoints=InMemoryCheckpointStore(),
        start_height=recording.heights[0],
        include_transactions=True,
        # Zero because the recording is already settled history. Against a live
        # chain this stays at the chain's configured depth, so the poller never
        # ingests a block that can still be reorged away.
        confirmations=0,
    )

    with Database() as db:  # in-memory; a real run passes a file path
        repository = SqliteBlockRepository(db)
        writer = RecordWriter(repository)

        results = poller.run(max_steps=4)
        report = writer.consume(results, queue)

        print(f"\n  polled    : {len(results)} step(s)")
        print(f"  stored    : {report.written} block(s)")
        print(f"  txs       : {writer.stats.transactions_written}")
        print(f"  rejected  : {len(report.rejections)}")

        highest = repository.highest("ethereum")
        print(f"\n  highest stored block: #{highest.number}")
        print(f"    hash      : {highest.block_hash[:22]}…")
        print(f"    txs        : {highest.transaction_count}")
        print(f"    provider   : {highest.source_provider}")

        # Replaying the same range writes nothing new. The in-memory dedup
        # window empties on restart, so the durable guarantee is the primary
        # key -- which is what makes a resumed ingest safe.
        again = RecordQueue(capacity=32)
        replay = BlockPoller(
            sensor,
            queue=again,
            checkpoints=InMemoryCheckpointStore(),
            start_height=recording.heights[0],
            include_transactions=True,
            confirmations=0,
        )
        second = writer.consume(replay.run(max_steps=4), again)
        print(f"\n  replaying the same range: {second.written} written, "
              f"{second.duplicates} duplicate(s)")
        print("    a replay is free — idempotency lives in the primary key")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
