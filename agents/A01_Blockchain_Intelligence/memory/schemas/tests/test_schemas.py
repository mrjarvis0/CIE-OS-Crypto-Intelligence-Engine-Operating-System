"""
Self-contained tests for memory.schemas.

Runs without pytest:
    python memory/schemas/tests/test_schemas.py

Exits 0 on success, non-zero with a diagnostic on failure.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from memory.schemas import (  # noqa: E402
    ConversationSchema,
    DecisionSchema,
    DistanceMetric,
    EntityKind,
    EntityRelationSchema,
    EntitySchema,
    EventSchema,
    FusionMode,
    HealthSchema,
    HealthState,
    KnowledgeItemSchema,
    KnowledgeKind,
    KnowledgeReportSchema,
    MemoryKind,
    MemorySchema,
    MessageRole,
    MessageSchema,
    MetricsSchema,
    PriorityLevel,
    RetrievalMode,
    RetrievalQuerySchema,
    RetrievalResultSchema,
    SchemaValidationError,
    SessionSchema,
    SnapshotSchema,
    SummarySchema,
    SummaryType,
    TaskSchema,
    TaskState,
    VectorSchema,
)

PASS = 0
FAIL = 0


def check(name: str, condition: bool) -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}")


def roundtrip(obj, cls):
    return cls.from_dict(obj.to_dict())


def test_memory_schema() -> None:
    print("memory schema")
    schema = MemorySchema(
        "k1",
        "value",
        kind=MemoryKind.FACT,
        tags=["a"],
        priority=PriorityLevel.HIGH,
    )
    schema.validate()
    restored = roundtrip(schema, MemorySchema)
    check("key", restored.key == "k1")
    check("kind", restored.kind == MemoryKind.FACT)
    check("priority", restored.priority == PriorityLevel.HIGH)
    check("tags", restored.tags == ["a"])
    try:
        MemorySchema("", "x").validate()
        check("empty key rejected", False)
    except SchemaValidationError:
        check("empty key rejected", True)


def test_message_schema() -> None:
    print("message schema")
    message = MessageSchema(
        role=MessageRole.USER,
        content="hello",
        session_id="s1",
        order=1,
    )
    restored = roundtrip(message, MessageSchema)
    check("role", restored.role == MessageRole.USER)
    check("order", restored.order == 1)
    try:
        MessageSchema(MessageRole.USER, "").validate()
        check("empty content rejected", False)
    except SchemaValidationError:
        check("empty content rejected", True)


def test_session_schema() -> None:
    print("session schema")
    now = datetime.now(UTC)
    future = SessionSchema("s1", "alice", expires_at=now + timedelta(hours=1))
    check("future not expired", not future.is_expired())
    restored = roundtrip(future, SessionSchema)
    check("owner", restored.owner == "alice")
    past = SessionSchema("s2", "bob", expires_at=now - timedelta(hours=1))
    check("past expired", past.is_expired())
    try:
        past.validate()
        check("past expiry rejected", False)
    except SchemaValidationError:
        check("past expiry rejected", True)


def test_conversation_schema() -> None:
    print("conversation schema")
    message = MessageSchema(MessageRole.ASSISTANT, "response", session_id="s1")
    conversation = ConversationSchema("c1", title="T", messages=[message])
    conversation.validate()
    restored = roundtrip(conversation, ConversationSchema)
    check("conversation id", restored.conversation_id == "c1")
    check("message count", restored.message_count == 1)


def test_retrieval_schema() -> None:
    print("retrieval schema")
    query = RetrievalQuerySchema(
        "gas settlement",
        mode=RetrievalMode.HYBRID,
        fusion=FusionMode.RRF,
    )
    restored = roundtrip(query, RetrievalQuerySchema)
    check("query text", restored.text == "gas settlement")
    check("query mode", restored.mode == RetrievalMode.HYBRID)
    result = RetrievalResultSchema(
        "k1",
        "val",
        score=0.9,
        relevance=0.8,
        recency=0.5,
        importance=0.7,
    )
    restored_result = roundtrip(result, RetrievalResultSchema)
    check("result score", restored_result.score == 0.9)


def test_vector_schema() -> None:
    print("vector schema")
    vector = VectorSchema("vec1", [0.1, 0.2, 0.3], metric=DistanceMetric.COSINE)
    vector.validate()
    restored = roundtrip(vector, VectorSchema)
    check("vector dim", restored.dim == 3)
    check("vector metric", restored.metric == DistanceMetric.COSINE)
    try:
        VectorSchema("v", []).validate()
        check("empty vector rejected", False)
    except SchemaValidationError:
        check("empty vector rejected", True)


def test_summary_schema() -> None:
    print("summary schema")
    summary = SummarySchema(
        "sum1",
        "concise summary",
        summary_type=SummaryType.KNOWLEDGE,
        input_tokens=240,
        output_tokens=58,
    )
    restored = roundtrip(summary, SummarySchema)
    check("summary id", restored.summary_id == "sum1")
    check("summary type", restored.summary_type == SummaryType.KNOWLEDGE)


def test_entity_schema() -> None:
    print("entity schema")
    entity = EntitySchema("Arbitrum", kind=EntityKind.TOKEN, mention_count=3)
    restored = roundtrip(entity, EntitySchema)
    check("entity name", restored.name == "Arbitrum")
    check("entity kind", restored.kind == EntityKind.TOKEN)
    relation = EntityRelationSchema("Alice", "deployed", "Arbitrum")
    restored_rel = roundtrip(relation, EntityRelationSchema)
    check("relation target", restored_rel.target == "Arbitrum")


def test_knowledge_schema() -> None:
    print("knowledge schema")
    now = datetime.now(UTC)
    report = KnowledgeReportSchema(
        items=[KnowledgeItemSchema(KnowledgeKind.FACT, "L2 is gas free")],
        decisions=[DecisionSchema("use L2", rationale="cheaper", options=["L1", "L2"], chosen="L2")],
        tasks=[TaskSchema("deploy", state=TaskState.OPEN, priority=10)],
        events=[EventSchema("launch", now + timedelta(days=2), participants=["alice"])],
    )
    restored = roundtrip(report, KnowledgeReportSchema)
    check("item count", restored.item_count == 4)
    check("decisions", len(restored.decisions) == 1)
    check("tasks", len(restored.tasks) == 1)
    check("events", len(restored.events) == 1)


def test_metrics_schema() -> None:
    print("metrics schema")
    metrics = MetricsSchema(entries=5, reads=10, writes=3, cache_hits=8, cache_misses=2)
    check("hit rate", abs(metrics.cache_hit_rate - 0.8) < 1e-9)
    restored = roundtrip(metrics, MetricsSchema)
    check("metrics restored", abs(restored.cache_hit_rate - 0.8) < 1e-9)
    health = HealthSchema("long_term", state=HealthState.HEALTHY, entries=5, initialized=True)
    restored_health = roundtrip(health, HealthSchema)
    check("health state", restored_health.state == HealthState.HEALTHY)
    snapshot = SnapshotSchema(health=health, metrics=metrics, keys=["a", "b"])
    restored_snap = roundtrip(snapshot, SnapshotSchema)
    check("snapshot keys", len(restored_snap.keys) == 2)


def main() -> None:
    test_memory_schema()
    test_message_schema()
    test_session_schema()
    test_conversation_schema()
    test_retrieval_schema()
    test_vector_schema()
    test_summary_schema()
    test_entity_schema()
    test_knowledge_schema()
    test_metrics_schema()
    print(f"\n{PASS} passed, {FAIL} failed")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
