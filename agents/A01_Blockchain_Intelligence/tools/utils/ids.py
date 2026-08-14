"""
Tools :: Utils :: Identifiers
=============================

Deterministic, collision-resistant identifier generation and validation used
across every layer of the Tools subsystem: requests, tools, executions,
traces, routes, approvals, packages and files.

The module deliberately avoids depending on third-party libraries: identifiers
are built on :mod:`uuid`, :mod:`secrets`, and :mod:`hashlib`.  All generated
identifiers are lowercase, URL-safe, and comparable.

Public helpers
--------------
* :func:`new_id`          -- random opaque id (UUID4 hex unless ``short``).
* :func:`new_hex_id`      -- random fixed-width hex id from ``secrets``.
* :func:`new_ulid`        -- lexicographically sortable, time-ordered id.
* :func:`new_name_id`     -- kebab-case id derived from a human label.
* :func:`slugify`         -- normalize arbitrary free text into a slug.
* :func:`is_id`           -- validate an opaque identifier form.
* :func:`fingerprint`     -- stable hash of structured data (for dedup/caching).
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from typing import Any, Optional

__all__ = [
    "new_id",
    "new_hex_id",
    "new_short_id",
    "new_trace_id",
    "new_route_id",
    "new_name_id",
    "slugify",
    "is_id",
    "fingerprint",
]

_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_UUID_LEN = 32
_TRACE_LEN = 32

# Characters usable in compact human-machine ids (32-character alphabet)
BASE32 = "0123456789abcdefghjkmnpqrstuvwxyz"


def new_id(prefix: Optional[str] = None) -> str:
    """
    Generate a random opaque id.

    The returned id is the hex encoding of a UUID v4.  When ``prefix`` is
    supplied it is joined with a ``-``:
    ``tools-1e2f3a4b5c6d7e8f...``.  Lowercase, safe for URLs, filesystem
    names, database keys and correlation headers.
    """
    value = secrets.token_hex(16)
    return f"{prefix}-{value}" if prefix else value


def new_hex_id(prefix: Optional[str] = None, bytes: int = 16) -> str:
    """
    Random hex id with configurable entropy.

    ``bytes`` controls the number of random bytes (the result is twice that
    long in hex characters).  Raises :class:`ValueError` for non-positive sizes.
    """
    if bytes < 1:
        raise ValueError("bytes must be >= 1")
    value = secrets.token_hex(bytes)
    return f"{prefix}-{value}" if prefix else value


def new_short_id(prefix: Optional[str] = None, length: int = 12) -> str:
    """
    Compact, readable, collision-resistant id using a 32-char alphabet.

    Use for user-facing surfaces (display ids, short trace refs).  The default
    length of 12 yields roughly 2 ** 60 possible values.
    """
    if length < 4:
        raise ValueError("length must be >= 4 to remain collision resistant")
    alphabet = BASE32
    rand = secrets.SystemRandom()
    value = "".join(rand.choice(alphabet) for _ in range(length))
    return f"{prefix}-{value}" if prefix else value


def new_trace_id() -> str:
    """
    Opaque trace identifier suitable for distributed correlation.

    Produced by the same mechanism as :func:`new_id` but always exactly 32
    hex characters, so it can be embedded inside W3C-style trace headers
    without normalisation.
    """
    return secrets.token_hex(16)


def new_route_id(*, seed: Any = None) -> str:
    """
    Deterministic-but-unique route identifier.

    Uses the current epoch if no ``seed`` is given; when ``seed`` is provided
    (for example a tool name or request hash) the identifier is stable and
    can be used to group repeated routing decisions.
    """
    if seed is None:
        return new_id(prefix="route")
    return fingerprint("route", seed)[:_TRACE_LEN]


def slugify(value: Any) -> str:
    """
    Turn arbitrary text into a kebab-case slug.

    Only ``[a-z0-9]`` plus ``-`` survive; consecutive separators are merged;
    leading and trailing dashes are removed.  Empty input yields an empty
    string (callers validate separately).
    """
    normalized = str(value or "").lower().strip()
    slug = _SLUG_RE.sub("-", normalized).strip("-")
    return slug


def new_name_id(name: Any, *, prefix: Optional[str] = None, max_length: int = 64) -> str:
    """
    Build a human-readable kebab-case id from a display name.

    Keeps ``max_length`` short by truncating at a word boundary when possible.
    The result is deterministic for a given ``name``, so tool designers can use
    it as the primary stable tool id.
    """
    slug = slugify(name)
    if not slug:
        slug = new_short_id(length=8)
    slug = slug[:max_length].rstrip("-")
    return f"{prefix}-{slug}" if prefix else slug


def is_id(value: Any, *, length: Optional[int] = None) -> bool:
    """
    True when ``value`` looks like a programmatically generated id.

    Accepts any ASCII hex string; when ``length`` is given the value must
    match exactly.  Human labels (spaces/case, punctuation) return False.
    """
    if not isinstance(value, str) or not value:
        return False
    if not _HEX_RE.fullmatch(value):
        return False
    if length is not None and len(value) != length:
        return False
    return True


def fingerprint(parts: Any, *, algorithm: str = "sha256") -> str:
    """
    Stable, collision-resistant fingerprint of arbitrary data.

    Mirrors :func:`tools.utils.hashing.fingerprint` but only intended for
    cache keys, request dedup, and id construction.  ``parts`` may be a
    single value or an iterable; values are normalized to JSON where
    possible and hashed together with a delimiter so ``["a", "bc"]`` and
    ``["ab", "c"]`` do not collide.

    The result is the first 16 hex chars of the digest.
    """
    if not isinstance(parts, (list, tuple)):
        parts = [parts]
    payload = "\x1f".join(_stable(part) for part in parts)
    digest = hashlib.new(algorithm, payload.encode("utf-8", "replace")).hexdigest()
    return digest[:16]


def _stable(value: Any) -> str:
    """Serialize a value to a stable string for hashing."""
    if value is None:
        return "~"
    if isinstance(value, (bool, int, float)):
        return str(value)
    if isinstance(value, str):
        return f"s:{value}"
    if isinstance(value, (bytes, bytearray)):
        return f"b:{bytes(value).hex()}"
    try:
        return f"j:{json.dumps(value, sort_keys=True, default=str)}"
    except (TypeError, ValueError):
        return f"r:{str(value)}"