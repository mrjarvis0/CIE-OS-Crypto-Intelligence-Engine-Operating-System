"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.utils.converters

Purpose:
    Defensive value and type converters for untrusted external data.
"""

from __future__ import annotations

from typing import Any


def to_int(value: Any, default: int | None = None) -> int | None:
    """
    Convert a value to int, returning default on failure.
    """
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def to_float(value: Any, default: float | None = None) -> float | None:
    """
    Convert a value to float, returning default on failure.
    """
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def to_bool(value: Any, default: bool = False) -> bool:
    """
    Convert a value to bool using common truthy representations.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on", "y", "t"}:
        return True
    if lowered in {"0", "false", "no", "off", "n", "f"}:
        return False
    return default


def to_hex_int(value: Any, default: int | None = None) -> int | None:
    """
    Convert a hex string (e.g. ``"0xde0b6b3a7640000"``) to an int.

    Accepts values with or without the ``0x`` prefix. Returns ``default``
    for non-hex input or ``None``.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    try:
        return int(text, 16)
    except (TypeError, ValueError):
        return default


def wei_to_ether(value: Any, decimals: int = 18, default: float | None = None) -> float | None:
    """
    Convert a raw integer amount (in base units) to a decimal float.

    ``decimals`` defaults to 18 (EVM ``wei``). Accepts decimal ints and
    hex strings (``0x...``). Non-numeric input returns ``default``.
    """
    if isinstance(value, str) and value.strip().lower().startswith("0x"):
        integer = to_hex_int(value, default=None)
    else:
        integer = to_int(value, default=None)
    if integer is None:
        return default
    return integer / (10**decimals)


def percent_ratio(value: Any, default: float = 0.0) -> float:
    """
    Coerce a value into a 0..1 ratio.

    Values already in 0..1 are returned unchanged; values in 0..100 are
    divided by 100; anything else yields ``default``.
    """
    number = to_float(value, default=None)
    if number is None:
        return default
    if 0.0 <= number <= 1.0:
        return number
    if 0.0 <= number <= 100.0:
        return number / 100.0
    return default
