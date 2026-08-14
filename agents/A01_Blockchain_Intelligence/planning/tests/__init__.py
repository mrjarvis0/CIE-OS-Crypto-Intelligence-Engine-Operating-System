"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    planning.tests

Purpose:
    Test suite for the planning subsystem.

Follows the repository convention: each ``test_*.py`` module defines a
``check(name, condition)`` helper, runs scenarios, and reports a
PASS/FAIL summary with a non-zero exit code on failure.
"""

from __future__ import annotations

PASS = 0
FAIL = 0


def check(name: str, condition: bool) -> None:
    """Record a single test result."""
    global PASS, FAIL  # noqa: PLW0603
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}")


def summary(label: str) -> int:
    """Print the aggregate result and return an exit code."""
    print(f"{label}: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0
