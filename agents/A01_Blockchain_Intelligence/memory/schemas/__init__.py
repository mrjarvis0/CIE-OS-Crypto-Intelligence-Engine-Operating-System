"""
Memory Schemas Package

Canonical, validated data models for memory entries, messages,
sessions, conversations, retrieval, vectors, summaries, entities,
knowledge, and metrics.
"""

from __future__ import annotations

from memory.schemas.conversation import ConversationSchema, ConversationState
from memory.schemas.entity import (
    EntityKind,
    EntityRelationSchema,
    EntitySchema,
)
from memory.schemas.knowledge import (
    DecisionSchema,
    EventSchema,
    KnowledgeItemSchema,
    KnowledgeKind,
    KnowledgeReportSchema,
    TaskSchema,
    TaskState,
)
from memory.schemas.memory import (
    MemoryKind,
    MemorySchema,
    PriorityLevel,
    SchemaError,
    SchemaValidationError,
)
from memory.schemas.message import MessageRole, MessageSchema
from memory.schemas.metrics import (
    HealthSchema,
    HealthState,
    MetricsSchema,
    SnapshotSchema,
)
from memory.schemas.retrieval import (
    FusionMode,
    RetrievalMode,
    RetrievalQuerySchema,
    RetrievalResultSchema,
)
from memory.schemas.session import SessionSchema, SessionState
from memory.schemas.summary import (
    SummarySchema,
    SummaryState,
    SummaryStyle,
    SummaryType,
)
from memory.schemas.vector import (
    DistanceMetric,
    VectorCollectionSchema,
    VectorSchema,
    VectorStoreKind,
)

__all__ = [
    "ConversationSchema",
    "ConversationState",
    "DecisionSchema",
    "DistanceMetric",
    "EntityKind",
    "EntityRelationSchema",
    "EntitySchema",
    "EventSchema",
    "FusionMode",
    "HealthSchema",
    "HealthState",
    "KnowledgeItemSchema",
    "KnowledgeKind",
    "KnowledgeReportSchema",
    "MemoryKind",
    "MemorySchema",
    "MessageRole",
    "MessageSchema",
    "MetricsSchema",
    "PriorityLevel",
    "RetrievalMode",
    "RetrievalQuerySchema",
    "RetrievalResultSchema",
    "SchemaError",
    "SchemaValidationError",
    "SessionSchema",
    "SessionState",
    "SnapshotSchema",
    "SummarySchema",
    "SummaryState",
    "SummaryStyle",
    "SummaryType",
    "TaskSchema",
    "TaskState",
    "VectorCollectionSchema",
    "VectorSchema",
    "VectorStoreKind",
]
