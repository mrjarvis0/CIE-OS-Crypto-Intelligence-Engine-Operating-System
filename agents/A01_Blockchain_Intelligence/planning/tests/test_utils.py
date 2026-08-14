"""
Tests for planning.utils.

Covers constants, helpers, ids, hashing, serialization, timers,
validation, graph, and decorators.
"""

from __future__ import annotations

import asyncio
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from planning.utils import graph, hashing, helpers, ids, serialization, timers, validation
from planning.utils.constants import (
    DEFAULT_ID_LENGTH,
    DEFAULT_MAX_GRAPH_DEPTH,
    DEFAULT_MAX_GRAPH_NODES,
    EventType,
    ExecutionStatus,
    GoalStatus,
    IdNamespace,
    PLANNER_VERSION,
    PlanningState,
    Priority,
    PROTOCOL_VERSION,
    RetryPolicy,
    RoutingStrategy,
    SCHEMA_VERSION,
    TaskStatus,
    WorkflowStatus,
)
from planning.utils.decorators import cache, measure_time, retry
from planning.tests import check, summary


def test_constants() -> None:
    check("PlanningState has CREATED", PlanningState.CREATED.value == "created")
    check("PlanningState has COMPLETED", PlanningState.COMPLETED.value == "completed")
    check("GoalStatus has IN_PROGRESS", GoalStatus.IN_PROGRESS.value == "in_progress")
    check("TaskStatus no STARTED", not hasattr(TaskStatus, "STARTED"))
    check("ExecutionStatus has RECOVERED", ExecutionStatus.RECOVERED.value == "recovered")
    check("WorkflowStatus has QUEUED", WorkflowStatus.QUEUED.value == "queued")
    check("Priority HIGH = 75", Priority.HIGH == 75)
    check("EventType TASK_SUCCEEDED", EventType.TASK_SUCCEEDED.value == "task_succeeded")
    check("RetryPolicy EXPONENTIAL", RetryPolicy.EXPONENTIAL.value == "exponential")
    check("RoutingStrategy BEST_SCORE", RoutingStrategy.BEST_SCORE.value == "best_score")
    check("PLANNER_VERSION str", isinstance(PLANNER_VERSION, str))
    check("SCHEMA_VERSION int", SCHEMA_VERSION >= 1)
    check("PROTOCOL_VERSION str", isinstance(PROTOCOL_VERSION, str))


def test_helpers() -> None:
    check("utc_now tz-aware", helpers.utc_now().tzinfo is not None)
    check("iso_now str", isinstance(helpers.iso_now(), str))
    check("chunk_list", helpers.chunk_list([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]])
    check("compact drops None", helpers.compact([0, "", None, "x", [], [1]]) == [0, "", "x", [], [1]])
    check(
        "flatten_dict",
        helpers.flatten_dict({"a": {"b": 1}, "c": 2}) == {"a.b": 1, "c": 2},
    )
    check("get_nested", helpers.get_nested({"a": {"b": 5}}, "a.b") == 5)
    check(
        "unique_preserve_order",
        helpers.unique_preserve_order([1, 2, 1, 3, 2]) == [1, 2, 3],
    )
    check("ensure_list None", helpers.ensure_list(None) == [])
    check("ensure_list scalar", helpers.ensure_list("x") == ["x"])
    check("ensure_list tuple", helpers.ensure_list((1, 2)) == [1, 2])
    check("ensure_list passthrough", helpers.ensure_list([3]) == [3])
    check("parse_int str", helpers.parse_int("42") == 42)
    check("parse_int underscore", helpers.parse_int("1_000") == 1000)
    check("parse_int negative", helpers.parse_int(" -3 ") == -3)
    check("parse_int bad", helpers.parse_int("abc") is None)
    check("parse_int bool", helpers.parse_int(True) is None)
    check("slugify", helpers.slugify("Hello, World!") == "hello-world")
    check("slugify accents", helpers.slugify("Café & Bakery") == "caf-bakery")
    check("truncate short", helpers.truncate("abc", max_length=10) == "abc")
    check("truncate long", helpers.truncate("abcdef", max_length=5) == "ab...")


def test_ids() -> None:
    goal = ids.generate(IdNamespace.GOAL)
    plan = ids.generate(IdNamespace.PLAN)
    task = ids.generate("task")

    check("goal id prefixed", goal.startswith("goal_"))
    check("plan id prefixed", plan.startswith("plan_"))
    check("task id prefixed", task.startswith("task_"))
    check("unique ids", len({goal, plan, task, ids.uuid7(), ids.uuid4()}) == 5)
    check("short_id length", len(ids.short_id()) == 10)
    check("nanoid length", len(ids.nanoid(size=8)) == 8)
    check("deterministic id", ids.deterministic_id("x") == ids.deterministic_id("x"))
    check("deterministic differs", ids.deterministic_id("x") != ids.deterministic_id("y"))
    check("validate_identifier", ids.validate_identifier("goal_abcdef123456"))
    check("format_identifier str", isinstance(ids.format_identifier("a b"), str))
    check("strip_namespace", ids.strip_namespace(goal) != goal)
    check("parse_timestamp uuid7", isinstance(ids.parse_timestamp(goal), float))
    check("parse_timestamp ulid", isinstance(ids.parse_timestamp(ids.ulid()), float))
    check("parse_timestamp snowflake", isinstance(ids.parse_timestamp(ids.snowflake()), float))
    check("parse_timestamp garbage", ids.parse_timestamp("abc") is None)

    generator = ids.IDGenerator(namespace=IdNamespace.TASK, method="uuid7")
    generated = generator.generate_id()
    check("IDGenerator prefixed", generated.startswith("task_"))
    check("IDGenerator validate", generator.validate_id(generated))
    check("IDGenerator timestamp", isinstance(generator.parse_timestamp(generated), float))

    raw = ids.IDGenerator(method="nanoid", size=10)
    check("IDGenerator raw", len(raw.generate_id()) == 10)
    check("IDGenerator raw validate", raw.validate_id(raw.generate_id()))

    try:
        ids.IDGenerator(method="bogus")
        check("IDGenerator rejects bogus", False)
    except ValueError:
        check("IDGenerator rejects bogus", True)


def test_hashing() -> None:
    check("hash_text stable", hashing.hash_text("hello") == hashing.hash_text("hello"))
    check("hash_text differs", hashing.hash_text("hello") != hashing.hash_text("world"))
    check("supported sha256", "sha256" in hashing.supported_algorithms())
    check("supported md5", "md5" in hashing.supported_algorithms())
    check("supported sha1", "sha1" in hashing.supported_algorithms())
    check("non-security marked", "md5" in hashing.NON_SECURITY_ALGORITHMS)
    check("md5 digest len", len(hashing.hash_text("x", algorithm="md5")) == 32)
    check("sha1 digest len", len(hashing.hash_text("x", algorithm="sha1")) == 40)
    check("hash_lines order matters", hashing.hash_lines(["a", "b"]) != hashing.hash_lines(["b", "a"]))
    check("hash_stream ok", len(hashing.hash_stream(io.BytesIO(b"hello"))) == 64)
    check("hash_file ok", len(hashing.hash_file(Path(__file__))) == 64)
    check("fingerprint namespace", hashing.fingerprint({"a": 1}).startswith("obj_"))
    hmac = hashing.hmac_hex(b"k", b"data")
    check("hmac_hex hex", len(hmac) == 64)
    check("hmac_verify", hashing.hmac_verify(b"k", b"data", hmac))


def test_serialization() -> None:
    payload = {"id": "x", "items": [1, 2], "ok": True}
    dumped = serialization.json_dumps(payload)
    check("json_dumps str", isinstance(dumped, str))
    check("json round trip", serialization.json_loads(dumped) == payload)
    check("canonical_json", serialization.canonical_json({"b": 1, "a": 2}) == serialization.canonical_json({"a": 2, "b": 1}))
    compressed = serialization.compress_zlib(b"abc")
    check("zlib round trip", serialization.decompress_zlib(compressed) == b"abc")
    gzip_data = serialization.compress_gzip(b"xyz")
    check("gzip round trip", serialization.decompress_gzip(gzip_data) == b"xyz")
    check("to_json alias", serialization.to_json({"a": 1}) == serialization.json_dumps({"a": 1}))
    check("from_json alias", serialization.from_json('{"x":1}') == {"x": 1})
    check("to_bytes alias", isinstance(serialization.to_bytes({"k": "v"}), bytes))
    check("from_bytes alias", serialization.from_bytes(serialization.to_bytes({"k": "v"})) == {"k": "v"})


def test_timers() -> None:
    sw = timers.Stopwatch()
    sw.start()
    check("stopwatch elapsed is float", isinstance(sw.elapsed_ms(), float))
    check("deadline not expired", not timers.Deadline(60).expired)
    backoff = timers.ExponentialBackoff()
    delays = [backoff.next_delay(i) for i in range(1, 4)]
    check("backoff delays positive", all(d > 0 for d in delays))
    budget = timers.ExecutionBudget()
    check("budget elapsed is float", isinstance(budget.elapsed_seconds, float))
    budget.record_step()
    check("budget step recorded", budget.steps == 1)

    reported: list[float] = []
    with timers.timer("block", callback=lambda name, ms: reported.append(ms)):
        pass
    check("timer callback fired", len(reported) == 1)
    check("timer elapsed positive", reported[0] >= 0.0)

    async def async_block() -> bool:
        reported_async: list[float] = []
        async with timers.async_timer("block", callback=lambda name, ms: reported_async.append(ms)):
            await asyncio.sleep(0.001)
        return len(reported_async) == 1

    check("async_timer fired", asyncio.run(async_block()))

    ticker = timers.Ticker(0.01)
    check("ticker not due initially", not ticker.due)
    time.sleep(0.02)
    check("ticker due", ticker.due)
    check("ticker tick", ticker.tick())
    check("ticker re-arm", not ticker.tick())


def test_validation() -> None:
    result = validation.require_non_empty("x")
    check("require_non_empty ok", result.valid)
    result = validation.require_non_empty("")
    check("require_non_empty fail", not result.valid)
    result = validation.validate_enum(Priority.HIGH.value, Priority)
    check("validate_enum ok", result.valid)
    result = validation.validate_enum("bogus", Priority)
    check("validate_enum fail", not result.valid)
    result = validation.validate_length([1, 2], max_length=2)
    check("validate_length ok", result.valid)
    result = validation.validate_length([1, 2, 3], max_length=2)
    check("validate_length fail", not result.valid)
    chained = validation.chain_validators(
        lambda v: validation.require_non_empty(v, name="v"),
        lambda v: validation.validate_length(v, min_length=2, name="v"),
    )
    check("chain ok", chained("abc").valid)
    check("chain fail", not chained("a").valid)

    validation.require_fields({"a": 1}, ["a"])
    check("require_fields ok", True)
    try:
        validation.require_fields({"a": 1}, ["a", "b"])
        check("require_fields raises", False)
    except validation.MissingFieldError as error:
        check("require_fields raises", True)
        check("missing field reported", "b" in error.missing)
    check("is_valid_goal fail", not validation.is_valid_goal({}))
    check("is_valid_task fail", not validation.is_valid_task({}))
    check("is_valid_plan fail", not validation.is_valid_plan({}))


def test_graph() -> None:
    g = graph.DiGraph[str]()
    g.add_nodes(["a", "b", "c", "d"])
    g.add_edge("a", "b")
    g.add_edge("a", "c")
    g.add_edge("b", "d")
    g.add_edge("c", "d")

    check("graph node count", len(g.nodes) == 4)
    check("is_dag", graph.is_dag(g))
    check("has_cycle false", not graph.has_cycle(g))
    check("topological sort", graph.topological_sort(g)[0] == "a")
    check("bfs from a", graph.bfs(g, "a")[0] == "a")
    check("shortest path a->d", graph.shortest_path(g, "a", "d") == ["a", "b", "d"])
    check("shortest path missing", graph.shortest_path(g, "x", "z") is None)
    check("successors", sorted(g.successors("a")) == ["b", "c"])
    check("predecessors d", sorted(g.predecessors("d")) == ["b", "c"])

    cyclic = graph.DiGraph[str]()
    cyclic.add_nodes(["a", "b"])
    cyclic.add_edge("a", "b")
    cyclic.add_edge("b", "a")
    check("has_cycle true", graph.has_cycle(cyclic))
    check("is_dag false", not graph.is_dag(cyclic))


def test_decorators() -> None:
    calls = {"n": 0}

    @retry(max_attempts=3, jittered=False)
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        return "ok"

    result = flaky()
    check("retry eventually succeeds", result == "ok")
    check("retry attempt count", calls["n"] == 3)

    times: list[float] = []

    @measure_time(lambda label, ms: times.append(ms))
    def work() -> int:
        time.sleep(0.005)
        return 42

    check("measure_time returns value", work() == 42)
    check("measure_time collected", len(times) == 1)

    cached: dict[str, int] = {"n": 0}

    @cache(max_entries=10)
    def counted(x: int) -> int:
        cached["n"] += 1
        return x * 2

    counted(1)
    counted(1)
    check("cache hit count", cached["n"] == 1)
    check("cache returns value", counted(2) == 4)


def main() -> int:
    print("utils tests")
    test_constants()
    test_helpers()
    test_ids()
    test_hashing()
    test_serialization()
    test_timers()
    test_validation()
    test_graph()
    test_decorators()
    return summary("utils")


if __name__ == "__main__":
    raise SystemExit(main())
