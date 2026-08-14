"""
Integration tests for the memory conversation package.

Each test drives a real ``ConversationMemory`` (in-memory SQLite) through
the conversation facades: session, history, messages, window, context,
timeline, replay, analytics, and exporter.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from memory.base.conversation import ConversationConfig, ConversationMemory, MessageRole
from memory.conversation import (
    ConversationAnalytics,
    ConversationContext,
    ConversationExporter,
    ConversationHistory,
    ConversationSession,
    ConversationWindow,
    MessageStore,
    ReplayEngine,
    TimelineBuilder,
)

PASS = 0
FAIL = 0


def check(name: str, condition: bool) -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}")


async def scenario() -> None:
    mem = ConversationMemory(config=ConversationConfig(db_path=":memory:"))
    await mem.initialize()

    session = ConversationSession(mem)
    conversation = await session.create("L2 research", user_id="alice")
    conv_id = conversation.id
    check("session.create returns conversation", conversation.id != "")
    session.activate(conv_id)
    check("session.activate", session.get(conv_id).active)
    check("session.active_sessions", any(s.conversation_id == conv_id for s in session.active_sessions()))

    store = MessageStore(mem)
    await store.add(conv_id, MessageRole.USER, "what about L2 gas?", tags=["l2"])
    await store.add(conv_id, MessageRole.ASSISTANT, "L2 settlement is gas-free", tags=["l2"])
    await store.add(conv_id, MessageRole.SYSTEM, "session context", tags=["meta"])
    check("store.count == 3", await store.count(conv_id) == 3)

    history = ConversationHistory(mem)
    read = await history.read(conv_id)
    check("history.read returns 3", len(read) == 3)
    page, total = await history.paginate(conv_id, page=0, page_size=2)
    check("history.paginate page size", len(page) == 2 and total == 3)
    first_message = read[0]
    check("history.get returns message", (await history.get(first_message.id)).content == first_message.content)
    check("history.append returns message", (await history.append(conv_id, MessageRole.ASSISTANT, "one more")).content == "one more")

    window = ConversationWindow(mem, max_tokens=100)
    result = await window.budget(conv_id)
    check("window.budget keeps all", result.kept == 4 and result.dropped == 0)
    check("window.budget token bound", result.total_tokens <= 100)
    check("window.window returns list", len(await window.window(conv_id)) == 4)
    check("window.latest returns 2", len(await window.latest(conv_id, count=2)) == 2)

    context = ConversationContext(mem, max_tokens=500)
    built = await context.build(conv_id)
    check("context.build blocks", built.block_count == 4)
    check("context.to_text has content", len(built.to_text()) > 0)

    timeline = TimelineBuilder(mem)
    entries = await timeline.build(conv_id)
    check("timeline.build count", entries.count == 4)
    buckets = await timeline.bucket_by_day(conv_id)
    check("timeline.bucket_by_day non-empty", len(buckets) >= 1)
    rollup = await timeline.participant_rollup(conv_id)
    check("timeline.rollup has roles", set(rollup) == {"system", "assistant", "user"})

    replay = ReplayEngine(mem)
    seen: list[str] = []
    stats = await replay.run(conv_id, on_message=lambda m: seen.append(m.role.value))
    check("replay.run count", stats.replayed == 4 and len(seen) == 4)
    transcript = await replay.transcript(conv_id)
    check("replay.transcript 4 lines", len(transcript.splitlines()) == 4)

    analytics = ConversationAnalytics(mem)
    result = await analytics.analyze(conv_id)
    check("analytics.message_count", result.message_count == 4)
    check("analytics.roles", result.roles == {"system": 1, "assistant": 2, "user": 1})
    check("analytics.list_summary non-empty", len(await analytics.list_summary()) >= 1)

    exporter = ConversationExporter(mem)
    payload = await exporter.to_dict(conv_id)
    check("exporter.to_dict messages", len(payload["messages"]) == 4)
    check("exporter.to_json parses", len(await exporter.to_json(conv_id)) > 0)
    check("exporter.to_jsonl 4 lines", len((await exporter.to_jsonl(conv_id)).splitlines()) == 4)
    check("exporter.to_text 4 lines", len((await exporter.to_text(conv_id)).splitlines()) == 4)

    check("exporter.load round-trip", len((await exporter.load(conv_id))[1]) == 4)
    try:
        await exporter.to_dict("does-not-exist")
        check("exporter raises on missing", False)
    except KeyError:
        check("exporter raises on missing", True)

    await mem.close()
    check("memory.close", True)


def main() -> int:
    print("conversation tests")
    asyncio.run(scenario())
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
