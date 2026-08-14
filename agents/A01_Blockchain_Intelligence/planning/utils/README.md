# A01 Blockchain Intelligence Agent — Planning / Utils

## Purpose

`planning/utils/` is the infrastructure layer of the planning subsystem. It
holds small, dependency-free building blocks used by every other planning
module (schemas, goals, tasks, routing, execution, reasoning, monitoring,
core).

Design constraints:

- No planning decisions live here.
- No task execution or blockchain logic lives here.
- Stdlib-first: the layer depends only on the Python standard library.
  Optional integrations (`msgpack`, `yaml`) are used only when present.
- Every module is import-safe: importing `planning.utils` must never raise.

## Module Inventory

| Module          | Responsibility                                                    |
| --------------- | ----------------------------------------------------------------- |
| `constants.py`  | Enums (states, statuses, priorities, formats) + runtime defaults. |
| `helpers.py`    | Pure utility functions (time, dicts, chunks, imports, JSON).      |
| `serialization.py` | Canonical JSON, JSON/pickle/msgpack/yaml, SafeSerializer.      |
| `hashing.py`    | Hash registry, object/file hashing, fingerprints, HMAC.          |
| `ids.py`        | UUIDs (4/7/8), ULID, NanoID, Snowflake, namespaced generators.   |
| `timers.py`     | Stopwatch, Deadline, backoff, budget, duration metrics.           |
| `validation.py` | ValidationResult, primitives, planner/domain validators.          |
| `graph.py`      | DiGraph: cycles, DAG, topo sort, BFS/DFS, paths, components.     |
| `decorators.py` | log/measure/validate/retry/cache/trace/transaction/checkpoint.   |

## Dependency Order

Each module depends only on modules listed above it (or nothing):

```
constants
helpers ─────────────┐
serialization ───────┤
hashing ─────────────┤
ids ─────────────────┤
timers ──────────────┤
validation ──────────┤
graph ───────────────┤
decorators ──────────┘   (uses constants, timers, validation)
__init__.py  ← public API re-exports
```

## Key Design Points

- `IdNamespace` prefixes (`goal_`, `task_`, `plan_`, ...) keep identifiers
  self-describing and parseable via `parse_namespace` / `strip_namespace`.
- `generate(namespace, algorithm)` is the single entry point for creating
  identifiers; default algorithm is `uuid7`. `IDGenerator` offers the same
  API as a configurable class, and `parse_timestamp` recovers the creation
  time from UUIDv7 / ULID / Snowflake IDs.
- `SafeSerializer` writes type-marked payloads (`json:` / `pickle:`) so a
  blob can be safely round-tripped without an explicit format argument.
- `canonical_json` sorts keys and compacts output, making it the stable input
  for hashing, fingerprints, and cache keys. `to_json` / `from_json` /
  `to_bytes` / `from_bytes` are conventional aliases.
- `hashing.py` marks MD5/SHA1 as `NON_SECURITY_ALGORITHMS` (checksums only)
  and defaults `usedforsecurity=False` for them so FIPS-mode systems can
  still use them. `hash_stream` / `hash_file` keep memory O(chunk_size).
- `DiGraph` is a weighted adjacency-list graph used later by routing and
  task scheduling (DAG validation, critical path).
- All decorators in `decorators.py` are sync/async aware. `timers.py`
  provides `timer` / `async_timer` context managers and a periodic
  `Ticker` for monitoring loops.
- `validation.py` offers both result-style validators (`ValidationResult`)
  and raise-style `require_fields` (`MissingFieldError`) plus boolean
  predicates (`is_valid_goal`, `is_valid_task`, ...).
- Versioning: `PLANNER_VERSION`, `SCHEMA_VERSION`, and `PROTOCOL_VERSION`.

## Usage

```python
from planning.utils import generate_goal_id, fingerprint, DiGraph, is_dag

goal_id = generate_goal_id()
digest = fingerprint({"goal": goal_id})

graph = DiGraph()
graph.add_edge("a", "b")
assert is_dag(graph)
```

```python
from planning.utils import IDGenerator, parse_timestamp, require_fields

gen = IDGenerator(namespace="task", method="uuid7")
task_id = gen.generate_id()
created = gen.parse_timestamp(task_id)      # epoch seconds

require_fields({"id": task_id}, ["id", "name"])  # raises MissingFieldError
```

## Verification

```
python -m compileall agents/A01_Blockchain_Intelligence/planning/utils
```

Then import the package and run a smoke test:

```python
import planning.utils  # must never raise
```
