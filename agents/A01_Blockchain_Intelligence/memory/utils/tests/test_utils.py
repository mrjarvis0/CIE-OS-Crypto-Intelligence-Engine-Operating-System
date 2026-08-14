"""
Tests for the memory utils package.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from memory.base.memory import MemoryEntry, MemoryPriority, MemoryType
from memory.utils import (
    build_tags,
    chunks,
    decode_importance,
    decode_memory_type,
    decode_priority,
    dict_to_entry,
    entry_to_dict,
    expires_at,
    fingerprint,
    flatten,
    from_json,
    get_logger,
    is_expired,
    iso_timestamp,
    namespaced_key,
    normalize_tags,
    parse_ttl,
    partition,
    require_key,
    require_tags,
    require_value,
    retry,
    sanitize,
    short_hash,
    stable_hash,
    to_json,
    validate_namespace,
    value_hash,
    windows,
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
    from memory.utils.batching import batched
    from memory.utils.hashing import composite_key, content_key
    from memory.utils.retry import RetryError
    from memory.utils.time import TimeError
    from memory.utils.validation import ValidationError

    check("sanitize", sanitize("a b/c!") == "a_b_c_")
    check("namespaced_key", namespaced_key("k", "ns") == "ns:k")
    check("composite_key stable", composite_key("a", 1) == composite_key("a", 1))
    check("content_key differs", content_key("x") != content_key("y"))

    check("stable_hash stable", stable_hash("abc") == stable_hash("abc"))
    check("stable_hash length", len(stable_hash("abc")) == 64)
    check("short_hash", len(short_hash("abc")) == 16)
    check("value_hash", value_hash({"a": 1}) == value_hash({"a": 1}))
    check("fingerprint metadata", fingerprint("x", {"a": 1}) != fingerprint("x", {"a": 2}))

    check("parse_ttl s", parse_ttl("5s").total_seconds() == 5)
    check("parse_ttl m", parse_ttl("2m").total_seconds() == 120)
    check("parse_ttl number", parse_ttl(30).total_seconds() == 30)
    try:
        parse_ttl("5x")
        check("parse_ttl bad raises", False)
    except TimeError:
        check("parse_ttl bad raises", True)
    future = expires_at("10s")
    check("expires_at future", future > datetime.now(timezone.utc))
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    check("is_expired past", is_expired(past))
    check("is_expired none", not is_expired(None))
    check("iso_timestamp", iso_timestamp().endswith("+00:00"))

    require_key("k")
    check("require_key ok", True)
    try:
        require_key("")
        check("require_key empty raises", False)
    except ValidationError:
        check("require_key empty raises", True)
    require_value(0)
    check("require_value zero ok", True)
    check("require_tags", require_tags(["a", "b"]) == ["a", "b"])
    check("normalize_tags", normalize_tags([" a ", "b", "a", ""]) == ["a", "b"])
    check("validate_namespace", validate_namespace("ns") == "ns")

    entry = MemoryEntry("k1", "v1", metadata=None)
    d = entry_to_dict(entry)
    check("entry_to_dict key", d["key"] == "k1")
    round_trip = dict_to_entry(d)
    check("dict_to_entry round trip", round_trip.key == entry.key and round_trip.value == entry.value)
    text = to_json(entry)
    parsed = from_json(text)
    check("to_json/from_json round trip", parsed.key == "k1")
    check("to_json string", isinstance(text, str))

    check("chunks", chunks([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]])
    check("batched", list(batched([1, 2, 3], 2)) == [[1, 2], [3]])
    check("partition", partition([1, 2, 3, 4], 2) == [[1, 2], [3, 4]])
    check("windows", windows([1, 2, 3, 4], 3) == [[1, 2, 3], [2, 3, 4]])
    check("flatten", flatten([[1], [2, 3]]) == [1, 2, 3])

    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ValueError("boom")
        return "ok"

    result = await retry(flaky, attempts=4, base_delay=0.0)
    check("retry succeeds", result == "ok")
    check("retry attempts", attempts == 3)

    attempts = 0

    async def always_fail() -> None:
        nonlocal attempts
        attempts += 1
        raise ValueError("nope")

    try:
        await retry(always_fail, attempts=2, base_delay=0.0)
        check("retry exhausts raises", False)
    except RetryError:
        check("retry exhausts raises", True)
    check("retry exhaust attempts", attempts == 2)

    logger = get_logger("test", level=logging.DEBUG)
    check("get_logger", logger.name == "memory.test")
    check("get_logger has handler", bool(logger.handlers))

    check("encode type", decode_memory_type([build_tags(memory_type=MemoryType.VECTOR)[0]]) == MemoryType.VECTOR)
    check("decode type default", decode_memory_type(["x"]) == MemoryType.LONG_TERM)
    check("encode importance", decode_importance(["lt:importance:0.9"]) == 0.9)
    check("encode priority", decode_priority([f"lt:priority:{MemoryPriority.CRITICAL.value}"]) == MemoryPriority.CRITICAL)
    tags = build_tags(
        memory_type=MemoryType.SHORT_TERM,
        importance=0.7,
        priority=MemoryPriority.HIGH,
        extra=["custom"],
    )
    check("build_tags count", len(tags) == 4)
    check("build_tags type", decode_memory_type(tags) == MemoryType.SHORT_TERM)
    check("build_tags importance", decode_importance(tags) == 0.7)
    check("build_tags priority", decode_priority(tags) == MemoryPriority.HIGH)


def main() -> int:
    print("utils tests")
    asyncio.run(scenario())
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
