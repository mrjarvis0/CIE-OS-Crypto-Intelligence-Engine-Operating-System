"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.utils.hashing

Purpose:
    Content and identifier hashing helpers.

    Content hashes are used for evidence provenance so artifacts can be
    fingerprinted and verified independently.
"""

from __future__ import annotations

import hashlib
import json

from typing import Any


def content_hash(data: Any, algorithm: str = "sha256") -> str:
    """
    Return a hex digest of the stable JSON-serialized representation
    of the input.
    """
    serialized = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    try:
        hasher = hashlib.new(algorithm)
    except ValueError:
        hasher = hashlib.sha256()
    hasher.update(serialized)
    return hasher.hexdigest()


def short_hash(value: str, length: int = 12) -> str:
    """
    Return a shortened hex digest of a string.
    """
    return content_hash(value)[:length]
