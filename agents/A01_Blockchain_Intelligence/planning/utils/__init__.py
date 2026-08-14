"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    planning.utils

Purpose:
    Planning Infrastructure Layer.

This package provides common infrastructure used by every planning
module: constants, IDs, hashing, serialization, validation, graphs,
timers, decorators, and helpers.

Design principles:
    - No planning decisions here
    - No task execution here
    - No blockchain logic here
    - Stdlib-first, portable, safe to import anywhere
"""

from __future__ import annotations

# ==============================================================================
# Constants
# ==============================================================================

from .constants import (
    DEFAULT_BACKOFF_BASE_SECONDS,
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_BACKOFF_MAX_SECONDS,
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_CHECKPOINT_INTERVAL,
    DEFAULT_EXECUTION_TIMEOUT_SECONDS,
    DEFAULT_HASH_ALGORITHM,
    DEFAULT_ID_ALGORITHM,
    DEFAULT_ID_LENGTH,
    DEFAULT_JITTER_RATIO,
    DEFAULT_MAX_CONCURRENT_TASKS,
    DEFAULT_PRIORITY,
    DEFAULT_RETRY_COUNT,
    DEFAULT_TASK_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    ExecutionMode,
    ExecutionStatus,
    EventType,
    GoalStatus,
    HashAlgorithm,
    IdNamespace,
    MAX_DEPTH,
    MAX_RETRY,
    MAX_TASKS,
    MAX_TASKS_PER_PLAN,
    PLANNER_VERSION,
    PlanningState,
    Priority,
    PROTOCOL_VERSION,
    RetryPolicy,
    RoutingStrategy,
    SCHEMA_VERSION,
    SerializationFormat,
    TaskStatus,
    WorkflowStatus,
)

# ==============================================================================
# Helpers
# ==============================================================================

from .helpers import (
    chunk_list,
    compact,
    deep_copy,
    ensure_list,
    flatten_dict,
    get_nested,
    iso_now,
    monotonic_ms,
    monotonic_seconds,
    object_eq,
    parse_int,
    safe_import,
    safe_merge,
    safe_metadata,
    shallow_copy,
    slugify,
    to_json_pretty,
    tree_builder,
    truncate,
    type_convert,
    unique_preserve_order,
    utc_now,
)

# ==============================================================================
# Serialization
# ==============================================================================

from .serialization import (
    SafeSerializer,
    canonical_json,
    canonical_json_bytes,
    compress_gzip,
    compress_zlib,
    decompress_gzip,
    decompress_zlib,
    deserialize,
    from_bytes,
    from_dict,
    from_json,
    json_dumps,
    json_loads,
    msgpack_dumps,
    msgpack_loads,
    pickle_dumps,
    pickle_loads,
    serialize,
    to_bytes,
    to_dict,
    to_json,
    yaml_dumps,
    yaml_loads,
)

# ==============================================================================
# Hashing
# ==============================================================================

from .hashing import (
    NON_SECURITY_ALGORITHMS,
    config_fingerprint,
    crc32,
    fingerprint,
    graph_fingerprint,
    hash_bytes,
    hash_file,
    hash_lines,
    hash_object,
    hash_stream,
    hash_text,
    hmac_hex,
    hmac_verify,
    plan_fingerprint,
    state_fingerprint,
    supported_algorithms,
    task_fingerprint,
)

# ==============================================================================
# IDs
# ==============================================================================

from .ids import (
    CollisionReport,
    IDGenerator,
    check_collisions,
    deterministic_id,
    format_identifier,
    generate,
    generate_checkpoint_id,
    generate_correlation_id,
    generate_execution_id,
    generate_goal_id,
    generate_objective_id,
    generate_plan_id,
    generate_route_id,
    generate_task_id,
    generate_trace_id,
    generate_workflow_id,
    nanoid,
    parse_namespace,
    parse_timestamp,
    short_id,
    snowflake,
    strip_namespace,
    ulid,
    uuid4,
    uuid7,
    uuid8,
    validate_identifier,
)

# ==============================================================================
# Timers
# ==============================================================================

from .timers import (
    BackoffConfig,
    BudgetLimits,
    Deadline,
    DurationMetric,
    ExecutionBudget,
    ExponentialBackoff,
    SchedulerClock,
    Stopwatch,
    Ticker,
    async_timer,
    check_timeout,
    measure_duration,
    retry_delay,
    sleep_retry,
    timer,
    with_timeout,
)

# ==============================================================================
# Validation
# ==============================================================================

from .validation import (
    MissingFieldError,
    PermissionValidator,
    ValidationResult,
    Validator,
    chain_validators,
    is_valid_goal,
    is_valid_plan,
    is_valid_task,
    is_valid_workflow,
    ok_result,
    require_fields,
    require_non_empty,
    validate_dependency,
    validate_depth,
    validate_enum,
    validate_goal,
    validate_length,
    validate_pattern,
    validate_plan,
    validate_retry_count,
    validate_schema,
    validate_task,
    validate_task_count,
    validate_type,
    validate_workflow,
)

# ==============================================================================
# Graph
# ==============================================================================

from .graph import (
    DiGraph,
    bfs,
    connected_components,
    critical_path,
    dfs,
    find_cycles,
    has_cycle,
    is_dag,
    merge_graphs,
    shortest_path,
    shortest_path_weighted,
    split_subgraph,
    topological_sort,
)

# ==============================================================================
# Decorators
# ==============================================================================

from .decorators import (
    cache,
    checkpoint,
    log_execution,
    measure_time,
    retry,
    trace,
    transaction,
    validate,
)

# ==============================================================================
# Public API
# ==============================================================================

__all__ = [
    # Constants
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
    "DEFAULT_BACKOFF_FACTOR",
    "DEFAULT_BACKOFF_MAX_SECONDS",
    "DEFAULT_JITTER_RATIO",
    "DEFAULT_MAX_CONCURRENT_TASKS",
    "DEFAULT_CHECKPOINT_INTERVAL",
    "DEFAULT_HASH_ALGORITHM",
    "DEFAULT_ID_ALGORITHM",
    "DEFAULT_ID_LENGTH",
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_RETRY_COUNT",
    # Helpers
    "utc_now",
    "iso_now",
    "monotonic_ms",
    "monotonic_seconds",
    "deep_copy",
    "shallow_copy",
    "safe_metadata",
    "safe_merge",
    "flatten_dict",
    "get_nested",
    "chunk_list",
    "unique_preserve_order",
    "compact",
    "ensure_list",
    "type_convert",
    "parse_int",
    "slugify",
    "truncate",
    "object_eq",
    "safe_import",
    "tree_builder",
    "to_json_pretty",
    # Serialization
    "canonical_json",
    "canonical_json_bytes",
    "json_dumps",
    "json_loads",
    "to_json",
    "from_json",
    "to_bytes",
    "from_bytes",
    "pickle_dumps",
    "pickle_loads",
    "to_dict",
    "from_dict",
    "compress_zlib",
    "decompress_zlib",
    "compress_gzip",
    "decompress_gzip",
    "msgpack_dumps",
    "msgpack_loads",
    "yaml_dumps",
    "yaml_loads",
    "SafeSerializer",
    "serialize",
    "deserialize",
    # Hashing
    "supported_algorithms",
    "NON_SECURITY_ALGORITHMS",
    "hash_bytes",
    "hash_text",
    "hash_object",
    "hash_stream",
    "hash_file",
    "hash_lines",
    "crc32",
    "fingerprint",
    "plan_fingerprint",
    "task_fingerprint",
    "graph_fingerprint",
    "config_fingerprint",
    "state_fingerprint",
    "hmac_hex",
    "hmac_verify",
    # IDs
    "uuid4",
    "uuid7",
    "uuid8",
    "ulid",
    "nanoid",
    "snowflake",
    "short_id",
    "deterministic_id",
    "generate",
    "generate_goal_id",
    "generate_objective_id",
    "generate_task_id",
    "generate_plan_id",
    "generate_execution_id",
    "generate_workflow_id",
    "generate_checkpoint_id",
    "generate_route_id",
    "generate_trace_id",
    "generate_correlation_id",
    "parse_namespace",
    "strip_namespace",
    "validate_identifier",
    "format_identifier",
    "parse_timestamp",
    "IDGenerator",
    "CollisionReport",
    "check_collisions",
    # Timers
    "Stopwatch",
    "timer",
    "async_timer",
    "Deadline",
    "check_timeout",
    "with_timeout",
    "BackoffConfig",
    "ExponentialBackoff",
    "retry_delay",
    "sleep_retry",
    "SchedulerClock",
    "BudgetLimits",
    "ExecutionBudget",
    "DurationMetric",
    "measure_duration",
    "Ticker",
    # Validation
    "ValidationResult",
    "ok_result",
    "MissingFieldError",
    "require_fields",
    "require_non_empty",
    "validate_type",
    "validate_length",
    "validate_enum",
    "validate_pattern",
    "validate_schema",
    "Validator",
    "chain_validators",
    "validate_goal",
    "validate_task",
    "validate_plan",
    "validate_workflow",
    "validate_dependency",
    "is_valid_goal",
    "is_valid_task",
    "is_valid_plan",
    "is_valid_workflow",
    "validate_task_count",
    "validate_depth",
    "validate_retry_count",
    "PermissionValidator",
    # Graph
    "DiGraph",
    "has_cycle",
    "find_cycles",
    "is_dag",
    "topological_sort",
    "bfs",
    "dfs",
    "shortest_path",
    "shortest_path_weighted",
    "critical_path",
    "merge_graphs",
    "split_subgraph",
    "connected_components",
    # Decorators
    "log_execution",
    "measure_time",
    "validate",
    "retry",
    "cache",
    "trace",
    "transaction",
    "checkpoint",
]
