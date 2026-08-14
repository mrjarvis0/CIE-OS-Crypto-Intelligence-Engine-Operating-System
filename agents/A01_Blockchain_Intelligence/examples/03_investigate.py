"""
CIE-OS / A01 — Example 3: storage to a decided, explained conclusion.

The whole read side, offline:

    database -> skills -> intelligence -> decision -> narrative

The output worth reading is not the finding. It is what A01 refuses to say: an
absence it cannot support, a confidence it caps, and an alert it will not raise.

Run:
    python examples/03_investigate.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import (  # noqa: E402
    Database,
    RecordWriter,
    SqliteAnalyticsRepository,
    SqliteBlockRepository,
    SqliteTokenRepository,
)
from decision import DecisionEngine, Subscription  # noqa: E402
from fixtures.replay import Recording, ReplaySensor  # noqa: E402
from ingestion import BlockPoller, InMemoryCheckpointStore, RecordQueue  # noqa: E402
from intelligence.core.engine import IntelligenceEngine  # noqa: E402
from intelligence.engines import SubjectComposer  # noqa: E402
from intelligence.narrative import NarrativeService  # noqa: E402


def main() -> int:
    logging.disable(logging.CRITICAL)
    print("Example 3 — storage to a decided conclusion\n")

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
        blocks = SqliteBlockRepository(db)
        tokens = SqliteTokenRepository(db)
        writer = RecordWriter(blocks, tokens=tokens)
        writer.consume(poller.run(max_steps=3), queue)

        print(f"  stored : {writer.stats.written} blocks, "
              f"{writer.stats.transactions_written} txs, "
              f"{writer.stats.token_transfers_written} token transfers")

        # A real address out of the stored data, rather than a made-up one.
        biggest = blocks.largest_transfers("ethereum", limit=1)
        if not biggest:
            print("  no native transfers in this window")
            return 0
        target = biggest[0].from_address.value
        print(f"  subject: {biggest[0].from_address.short()}\n")

        # skills -> subject
        composition = SubjectComposer().compose(
            SqliteAnalyticsRepository(db), chain="ethereum", address=target
        )
        print(f"  skills contributed : {', '.join(composition.contributed)}")
        print(f"  coverage           : {composition.coverage.blocks} blocks stored")
        print(f"  supports absence   : {composition.supports_absence}")
        print(f"    -> {composition.coverage.limitation}\n")

        # intelligence -> decision
        package = IntelligenceEngine().run(composition.subject)
        decision = DecisionEngine(subscriptions=[Subscription("desk")]).decide(package)

        print("  conclusions:")
        for c in decision.conclusions:
            print(f"    [{c.stance.value:<12}] {c.qualifier}: {c.claim[:52]}")
            print(f"    {'':<15}confidence {c.confidence:.2f}")

        print(f"\n  alerts raised : {len(decision.alerts.raised)}")
        if decision.silence_explained:
            print(f"    why silent  : {decision.silence_explained[:66]}")

        if decision.constraint:
            print(f"\n  binding constraint: {decision.constraint.confidence:.2f} "
                  f"({decision.constraint.band.label})")
            print("    the weakest link, not an average of the parts")

        # narrative
        evidence = [
            a for chain in getattr(package, "evidence_chains", ())
            for a in getattr(chain, "artifacts", ())
        ]
        publication = NarrativeService().publish(decision, evidence=evidence)
        print(f"\n  narrative ({publication.narrative.method}):")
        for line in publication.narrative.text.split("\n\n")[:2]:
            print(f"    {line[:74]}")

        print("\n  next steps A01 recommends:")
        for rec in decision.recommendations[:3]:
            print(f"    [{rec.action.value}] {rec.detail[:58]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
