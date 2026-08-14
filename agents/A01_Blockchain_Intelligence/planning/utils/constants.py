"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.utils.constants

Purpose:
    Central immutable constants for the planning subsystem.

Rules:
    - No secrets
    - No environment-specific values
    - No business logic
    - Safe to import anywhere
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Final

# ==============================================================================
# PLANNING STATES
# ==============================================================================


class PlanningState(StrEnum):
    """
    High-level lifecycle state of a plan.
    """

    CREATED = "created"

    UNDERSTANDING = "understanding"

    PLANNING = "planning"

    SCHEDULED = "scheduled"

    EXECUTING = "executing"

    VALIDATING = "validating"

    REFLECTING = "reflecting"

    REPLANNING = "replanning"

    COMPLETED = "completed"

    FAILED = "failed"

    CANCELLED = "cancelled"


# ==============================================================================
# GOAL STATUS
# ==============================================================================


class GoalStatus(StrEnum):
    """
    Lifecycle status of a goal.
    """

    NEW = "new"

    UNDERSTOOD = "understood"

    CONSTRAINED = "constrained"

    DECOMPOSED = "decomposed"

    READY = "ready"

    IN_PROGRESS = "in_progress"

    COMPLETED = "completed"

    FAILED = "failed"

    CANCELLED = "cancelled"


# ==============================================================================
# TASK STATUS
# ==============================================================================


class TaskStatus(StrEnum):
    """
    Lifecycle status of a task.
    """

    PENDING = "pending"

    BLOCKED = "blocked"

    READY = "ready"

    RUNNING = "running"

    SUCCEEDED = "succeeded"

    FAILED = "failed"

    RETRYING = "retrying"

    SKIPPED = "skipped"

    CANCELLED = "cancelled"


# ==============================================================================
# WORKFLOW STATUS
# ==============================================================================


class WorkflowStatus(StrEnum):
    """
    Lifecycle status of a workflow.
    """

    DRAFT = "draft"

    DEFINED = "defined"

    VALIDATED = "validated"

    QUEUED = "queued"

    RUNNING = "running"

    PAUSED = "paused"

    SUCCEEDED = "succeeded"

    FAILED = "failed"

    CANCELLED = "cancelled"


# ==============================================================================
# EXECUTION STATUS
# ==============================================================================


class ExecutionStatus(StrEnum):
    """
    Lifecycle status of an execution.
    """

    CREATED = "created"

    SCHEDULED = "scheduled"

    RUNNING = "running"

    SUCCEEDED = "succeeded"

    FAILED = "failed"

    RETRYING = "retrying"

    INTERRUPTED = "interrupted"

    RECOVERED = "recovered"

    CANCELLED = "cancelled"


# ==============================================================================
# PRIORITY
# ==============================================================================


class Priority(IntEnum):
    """
    Scheduling priority.

    Higher values receive execution preference.
    """

    BACKGROUND = 0

    LOW = 25

    NORMAL = 50

    HIGH = 75

    CRITICAL = 100


# ==============================================================================
# EVENT TYPES
# ==============================================================================


class EventType(StrEnum):
    """
    Emittable planning event types.
    """

    PLAN_CREATED = "plan_created"

    PLAN_STARTED = "plan_started"

    PLAN_COMPLETED = "plan_completed"

    PLAN_FAILED = "plan_failed"

    GOAL_UNDERSTOOD = "goal_understood"

    TASK_DECOMPOSED = "task_decomposed"

    TASK_STARTED = "task_started"

    TASK_SUCCEEDED = "task_succeeded"

    TASK_FAILED = "task_failed"

    TASK_RETRYING = "task_retrying"

    TOOL_SELECTED = "tool_selected"

    TOOL_CALLED = "tool_called"

    TOOL_FAILED = "tool_failed"

    VALIDATION_FAILED = "validation_failed"

    VALIDATION_PASSED = "validation_passed"

    REFLECTION_COMPLETED = "reflection_completed"

    REPLAN_REQUESTED = "replan_requested"


# ==============================================================================
# ID NAMESPACES
# ==============================================================================


class IdNamespace(StrEnum):
    """
    Namespace prefixes for planning identifiers.
    """

    GOAL = "goal"

    OBJECTIVE = "obj"

    TASK = "task"

    PLAN = "plan"

    EXECUTION = "exec"

    WORKFLOW = "wf"

    CHECKPOINT = "ckpt"

    ROUTE = "route"

    SESSION = "sess"

    TRACE = "trace"


# ==============================================================================
# VERSION CONSTANTS
# ==============================================================================


PLANNER_VERSION: Final[str] = "0.1.0"

SCHEMA_VERSION: Final[int] = 1

PROTOCOL_VERSION: Final[str] = "1"


# ==============================================================================
# RUNTIME DEFAULTS
# ==============================================================================

MAX_TASKS: Final[int] = 500

MAX_TASKS_PER_PLAN: Final[int] = 200

MAX_DEPTH: Final[int] = 10

MAX_RETRY: Final[int] = 3

DEFAULT_PRIORITY: Final[Priority] = Priority.NORMAL

DEFAULT_TIMEOUT_SECONDS: Final[int] = 300

DEFAULT_EXECUTION_TIMEOUT_SECONDS: Final[int] = 60

DEFAULT_TASK_TIMEOUT_SECONDS: Final[int] = 30

DEFAULT_BACKOFF_BASE_SECONDS: Final[float] = 1.0

DEFAULT_BACKOFF_MAX_SECONDS: Final[float] = 60.0

DEFAULT_BACKOFF_FACTOR: Final[float] = 2.0

DEFAULT_JITTER_RATIO: Final[float] = 0.2

DEFAULT_MAX_CONCURRENT_TASKS: Final[int] = 10

DEFAULT_CHECKPOINT_INTERVAL: Final[int] = 5

DEFAULT_MAX_GRAPH_NODES: Final[int] = 1000

DEFAULT_MAX_GRAPH_DEPTH: Final[int] = 50

DEFAULT_HASH_ALGORITHM: Final[str] = "sha256"

DEFAULT_ID_ALGORITHM: Final[str] = "uuid7"

DEFAULT_ID_LENGTH: Final[int] = 21

DEFAULT_HASH_CHUNK_BYTES: Final[int] = 65536

DEFAULT_RETRY_COUNT: Final[int] = 3

DEFAULT_CACHE_TTL_SECONDS: Final[int] = 300

DEFAULT_MAX_CACHE_ENTRIES: Final[int] = 10_000

DEFAULT_SNOWFLAKE_WORKER_ID: Final[int] = 0

DEFAULT_SNOWFLAKE_SEQUENCE: Final[int] = 0

# ==============================================================================
# EXECUTION MODES
# ==============================================================================


class ExecutionMode(StrEnum):
    """
    How a plan or task should be executed.
    """

    SEQUENTIAL = "sequential"

    PARALLEL = "parallel"

    ASYNC = "async"

    MIXED = "mixed"


# ==============================================================================
# ROUTING POLICIES
# ==============================================================================


class RoutingStrategy(StrEnum):
    """
    Strategy used to route a task to a tool or agent.
    """

    FIRST_MATCH = "first_match"

    BEST_SCORE = "best_score"

    ROUND_ROBIN = "round_robin"

    RANDOM = "random"

    FALLBACK = "fallback"


# ==============================================================================
# RETRY POLICIES
# ==============================================================================


class RetryPolicy(StrEnum):
    """
    Retry behavior on failure.
    """

    NONE = "none"

    FIXED = "fixed"

    EXPONENTIAL = "exponential"

    JITTERED = "jittered"

    ALWAYS = "always"


# ==============================================================================
# SERIALIZATION FORMATS
# ==============================================================================


class SerializationFormat(StrEnum):
    """
    Supported serialization formats.
    """

    JSON = "json"

    MSGPACK = "msgpack"

    YAML = "yaml"

    PICKLE = "pickle"

    DICT = "dict"


# ==============================================================================
# HASH ALGORITHMS
# ==============================================================================


class HashAlgorithm(StrEnum):
    """
    Supported content hash algorithms.

    MD5 and SHA1 are provided for non-security checksums only.
    """

    MD5 = "md5"

    SHA1 = "sha1"

    SHA256 = "sha256"

    SHA512 = "sha512"

    SHA3_256 = "sha3_256"

    BLAKE2B = "blake2b"

    BLAKE2S = "blake2s"

    CRC32 = "crc32"


# ==============================================================================
# PUBLIC EXPORTS
# ==============================================================================

__all__ = [
    "PlanningState",
    "GoalStatus",
    "TaskStatus",
    "WorkflowStatus",
    "ExecutionStatus",
    "Priority",
    "EventType",
    "IdNamespace",
    "ExecutionMode",
    "RoutingStrategy",
    "RetryPolicy",
    "SerializationFormat",
    "HashAlgorithm",
    "PLANNER_VERSION",
    "SCHEMA_VERSION",
    "PROTOCOL_VERSION",
    "MAX_TASKS",
    "MAX_TASKS_PER_PLAN",
    "MAX_DEPTH",
    "MAX_RETRY",
    "DEFAULT_PRIORITY",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_EXECUTION_TIMEOUT_SECONDS",
    "DEFAULT_TASK_TIMEOUT_SECONDS",
    "DEFAULT_BACKOFF_BASE_SECONDS",
    "DEFAULT_BACKOFF_MAX_SECONDS",
    "DEFAULT_BACKOFF_FACTOR",
    "DEFAULT_JITTER_RATIO",
    "DEFAULT_MAX_CONCURRENT_TASKS",
    "DEFAULT_CHECKPOINT_INTERVAL",
    "DEFAULT_RETRY_COUNT",
    "DEFAULT_MAX_GRAPH_NODES",
    "DEFAULT_MAX_GRAPH_DEPTH",
    "DEFAULT_HASH_ALGORITHM",
    "DEFAULT_ID_ALGORITHM",
    "DEFAULT_ID_LENGTH",
    "DEFAULT_HASH_CHUNK_BYTES",
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_MAX_CACHE_ENTRIES",
    "DEFAULT_SNOWFLAKE_WORKER_ID",
    "DEFAULT_SNOWFLAKE_SEQUENCE",
]
