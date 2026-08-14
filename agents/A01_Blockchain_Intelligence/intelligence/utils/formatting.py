"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.utils.formatting

Purpose:
    Human and machine output formatting helpers.

    Values that represent normalized ratios (0..1) are rendered as
    percentages; values already expressed as percentages are passed
    through unchanged. No discontinuous cutoffs are applied.
"""

from __future__ import annotations

import json

from typing import Any


def format_number(value: float | int, decimals: int = 2) -> str:
    """
    Format a number with a fixed number of decimals.
    """
    return f"{float(value):.{decimals}f}"


def format_percent(value: float, decimals: int = 1) -> str:
    """
    Format a ratio or percentage as a percent string.

    Values in the closed interval [0.0, 1.0] are treated as normalized
    ratios and scaled by 100 (e.g. ``0.75`` -> ``"75.0%"``). Values
    outside that interval are assumed to already be percentages
    (e.g. ``150.0`` -> ``"150.0%"``).
    """
    raw = value * 100.0 if 0.0 <= value <= 1.0 else value
    return f"{raw:.{decimals}f}%"


def pretty_json(data: Any) -> str:
    """
    Pretty-print JSON-compatible data.
    """
    return json.dumps(data, indent=2, sort_keys=True, default=str)


def format_address(address: str, prefix: int = 6, suffix: int = 4) -> str:
    """
    Shorten an address for display as ``0x1234...abcd``.

    Prefix and suffix lengths may be zero to disable either side.
    """
    address = str(address)
    if len(address) <= prefix + suffix:
        return address
    head = address[:prefix] if prefix > 0 else ""
    tail = address[-suffix:] if suffix > 0 else ""
    separator = "..." if prefix > 0 and suffix > 0 else ""
    return f"{head}{separator}{tail}"


def format_amount(
    value: float,
    token_symbol: str = "ETH",
    decimals: int = 4,
) -> str:
    """
    Format a token amount for human display, e.g. ``"12.5000 ETH"``.
    """
    return f"{format_number(value, decimals)} {token_symbol}"
