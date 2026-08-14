"""
CIE-OS / A01 — Example 4: render the dashboard.

Builds a database from recorded blocks and renders one self-contained HTML
page: no server, no CDN, no external font or script. It can be saved, mailed,
and opened offline, and it cannot drift from the database because it is a
photograph of it at one instant.

Run:
    python examples/04_dashboard.py [output.html]
"""

from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import (  # noqa: E402
    Database,
    RecordWriter,
    SqliteAnalyticsRepository,
    SqliteBlockRepository,
    SqliteTokenRepository,
)
from fixtures.replay import Recording, ReplaySensor  # noqa: E402
from ingestion import BlockPoller, InMemoryCheckpointStore, RecordQueue  # noqa: E402
from interfaces.dashboard import collect, render  # noqa: E402


def main() -> int:
    logging.disable(logging.CRITICAL)
    print("Example 4 — render the dashboard\n")

    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path(tempfile.gettempdir()) / "a01-example-dashboard.html"
    )

    recording = Recording.named("ethereum_logs")
    sensor = ReplaySensor(recording)
    queue: RecordQueue = RecordQueue(capacity=64)
    poller = BlockPoller(
        sensor,
        queue=queue,
        checkpoints=InMemoryCheckpointStore(),
        start_height=recording.heights[0],
        include_transactions=True,
        include_logs=True,
        confirmations=0,
    )

    with Database() as db:
        writer = RecordWriter(SqliteBlockRepository(db), tokens=SqliteTokenRepository(db))
        writer.consume(poller.run(max_steps=3), queue)

        snapshot = collect(
            SqliteBlockRepository(db),
            SqliteTokenRepository(db),
            SqliteAnalyticsRepository(db),
            database="example (recorded fixture)",
        )
        html = render(snapshot)

    out.write_text(html, encoding="utf-8")

    print(f"  chains          : {len(snapshot.chains)}")
    print(f"  blocks          : {snapshot.total_blocks:,}")
    print(f"  transactions    : {snapshot.total_transactions:,}")
    print(f"  token transfers : {snapshot.total_token_transfers:,}")
    print(f"  nft transfers   : {snapshot.total_nft_transfers:,}")

    # The properties that make it safe to hand to someone.
    external = html.count("http://") + html.count("https://")
    print(f"\n  written  : {out}  ({len(html):,} bytes)")
    print(f"  external references: {external}  <- zero, so it works offline")

    card = snapshot.chains[0] if snapshot.chains else None
    if card:
        print(f"\n  coverage bar for {card.chain}:")
        print(f"    {card.blocks} blocks stored, absence claims licensed: "
              f"{card.supports_absence}")
        print(f"    {card.coverage_limitation or 'window is deep enough'}")
        print("    the bar is nearly empty on purpose — a reader sees why")
        print("    negative findings are withheld rather than assuming none exist")

    print(f"\n  open it: {out.resolve().as_uri()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
