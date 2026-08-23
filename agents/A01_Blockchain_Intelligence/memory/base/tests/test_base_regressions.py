"""
Regression tests for latent NameError bugs in ``memory.base``.

Both defects were found by a pyflakes sweep on 2026-08-22 and lived in code
paths the collected suite never drove -- which is exactly why they survived a
green run. Each test is named for the defect it guards.

Runs under pytest (``asyncio_mode = auto``) or standalone::

    python memory/base/tests/test_base_regressions.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from memory.base.conversation import ConversationConfig, ConversationMemory  # noqa: E402
from memory.base.vector_memory import VectorMemory, VectorMemoryConfig  # noqa: E402


async def test_health_check_computes_overall_status() -> None:
    """
    Guards ``conversation.py`` ``health_check()``.

    It aggregated its per-check results with a bare ``_is_healthy(...)`` call
    rather than ``self._is_healthy(...)``. ``_is_healthy`` is a method, so the
    bare name is undefined in the generator's scope and computing
    ``overall_status`` raised ``NameError`` on every call.
    """
    mem = ConversationMemory(config=ConversationConfig(db_path=":memory:"))
    await mem.initialize()
    try:
        checks = await mem.health_check()
    finally:
        await mem.close()

    assert "overall_status" in checks
    assert isinstance(checks["overall_status"], bool)


def test_row_to_entry_generates_uuid_when_id_missing() -> None:
    """
    Guards ``vector_memory.py`` ``_row_to_entry()``.

    A row whose id column is empty fell through to a bare ``uuid4()`` -- but the
    module imports only the ``uuid`` module, so hydrating such a row raised
    ``NameError``. A stored id must round-trip; a missing one must be generated.
    """
    vm = VectorMemory(config=VectorMemoryConfig())

    generated = vm._row_to_entry(("", "k1", None, None, "hello", None, "{}"))
    assert isinstance(generated.identifier, uuid.UUID)

    known = str(uuid.uuid4())
    preserved = vm._row_to_entry((known, "k2", None, None, "world", None, "{}"))
    assert str(preserved.identifier) == known


def main() -> int:
    asyncio.run(test_health_check_computes_overall_status())
    test_row_to_entry_generates_uuid_when_id_missing()
    print("memory.base regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
