"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    intelligence.utils

Purpose:
    Shared reusable helpers for the intelligence layer.

Submodules
----------
normalization  Entity and address normalization.
helpers        Generic helpers (clamping, ids, time parsing).
hashing        Content and identifier hashing.
formatting     Human and machine output formatting.
ranking        Score ordering and top-N selection.
converters     Value and type converters.
"""

from __future__ import annotations

from .converters import (
    percent_ratio,
    to_bool,
    to_float,
    to_hex_int,
    to_int,
    wei_to_ether,
)
from .formatting import (
    format_address,
    format_amount,
    format_number,
    format_percent,
    pretty_json,
)
from .hashing import content_hash, short_hash
from .helpers import (
    age_seconds,
    clamp,
    is_within,
    new_id,
    now_utc,
    parse_iso_datetime,
    retry_async,
    run_with_timeout,
)
from .normalization import (
    normalize_address,
    normalize_entity_id,
    validate_address,
)
from .ranking import rank_asc, rank_desc, top_n, top_n_asc

__all__ = [
    "normalize_address",
    "normalize_entity_id",
    "validate_address",
    "clamp",
    "now_utc",
    "new_id",
    "parse_iso_datetime",
    "age_seconds",
    "is_within",
    "retry_async",
    "run_with_timeout",
    "content_hash",
    "short_hash",
    "format_number",
    "format_percent",
    "pretty_json",
    "format_address",
    "format_amount",
    "rank_desc",
    "rank_asc",
    "top_n",
    "top_n_asc",
    "to_bool",
    "to_float",
    "to_int",
    "to_hex_int",
    "wei_to_ether",
    "percent_ratio",
]
