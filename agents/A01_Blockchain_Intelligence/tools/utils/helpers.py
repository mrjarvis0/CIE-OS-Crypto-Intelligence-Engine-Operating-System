"""
Tools :: Utils :: Helpers
=========================

Small, dependency-free utility functions used across the Tools subsystem:
nested dictionary navigation, text normalization, timing helpers and
collection manipulation.  Kept separate from the domain packages so the
core layers never import business code.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

__all__ = [
    "now_utc",
    "iso_now",
    "elapsed_ms",
    "Timer",
    "deep_get",
    "deep_set",
    "deep_merge",
    "chunked",
    "unique",
    "flatten",
    "truncate",
    "compact_dict",
    "redact",
    "mask_secret",
    "MIN_MASKABLE_LENGTH",
    "safe_dump",
    "balanced_json",
]


def now_utc() -> datetime:
    """Timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


def iso_now() -> str:
    """ISO-8601 timestamp string for logs/telemetry."""
    return now_utc().isoformat()


def elapsed_ms(started: float) -> float:
    """Seconds elapsed since a :func:`time.monotonic` ``started`` mark."""
    return (time.monotonic() - started) * 1000.0


class Timer:
    """Context manager measuring elapsed time in milliseconds.

    Usage::

        with Timer() as t:
            work()
        print(t.ms)
    """

    def __init__(self) -> None:
        self.started: float = time.monotonic()
        self.ms: float = 0.0

    def __enter__(self) -> "Timer":
        self.started = time.monotonic()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.ms = elapsed_ms(self.started)

    def reset(self) -> None:
        self.started = time.monotonic()
        self.ms = 0.0


def compact_dict(data: Mapping[str, Any], *, drop_empty: bool = True) -> Dict[str, Any]:
    """Return a copy of ``data`` with ``None`` (and optionally empty) values removed."""
    out: Dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if drop_empty and value in ("", [], (), {}):
            continue
        out[key] = value
    return out


def balanced_json(raw: str) -> bool:
    """Check whether ``raw`` is a complete, balanced JSON document."""
    if not isinstance(raw, str) or not raw.strip():
        return False
    try:
        json.loads(raw)
        return True
    except ValueError:
        return False


def deep_get(data: Mapping[str, Any], path: str, default: Any = None) -> Any:
    """Retrieve a nested value from ``data`` using a dotted ``path``."""
    cursor: Any = data
    for part in path.split("."):
        if isinstance(cursor, Mapping) and part in cursor:
            cursor = cursor[part]
        else:
            return default
    return cursor


def deep_set(data: Dict[str, Any], path: str, value: Any) -> None:
    """Assign ``value`` at a nested dotted ``path``, creating dicts as needed."""
    parts = path.split(".")
    cursor = data
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def deep_merge(base: Dict[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a new dict merging ``override`` into ``base`` recursively."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def deep_copy(data: Any) -> Any:
    """JSON-safe deep copy (drops non-JSON values after string coercion)."""
    return json.loads(json.dumps(data, default=str))


def chunked(iterable: Iterable[Any], size: int) -> Iterable[List[Any]]:
    """Yield successive ``size``-sized chunks from ``iterable``."""
    if size < 1:
        raise ValueError("chunk size must be >= 1")
    batch: List[Any] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def unique(items: Iterable[Any]) -> List[Any]:
    """Return items in order, deduplicated."""
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def flatten(items: Iterable[Any]) -> List[Any]:
    """Flatten one level of nesting."""
    out: List[Any] = []
    for item in items:
        if isinstance(item, (list, tuple)):
            out.extend(item)
        else:
            out.append(item)
    return out


def to_dict(obj: Any) -> Dict[str, Any]:
    """Best-effort conversion of an object or mapping to a dict."""
    if isinstance(obj, Mapping):
        return dict(obj)
    if hasattr(obj, "as_dict"):
        return obj.as_dict()
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    return {"value": obj}


def truncate(text: str, max_chars: int = 512, suffix: str = "...") -> str:
    """Limit a string to ``max_chars`` appending ``suffix`` when truncated."""
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - len(suffix))] + suffix


def to_dict2(value: Any) -> Any:  # kept minimal
    return to_dict(value)


def redact(value: Any, sensitive_keys: Iterable[str] = ("password", "token", "secret", "key", "private")) -> Any:
    """
    Recursively mask values whose keys look sensitive, for safe logging.
    """
    sensitive = {str(k).lower() for k in sensitive_keys}
    return _redact_inner(value, sensitive)


def _redact_inner(node: Any, sensitive: set) -> Any:
    if isinstance(node, Mapping):
        return {
            k: (_redact_inner(v, sensitive) if str(k).lower() not in sensitive else "[REDACTED]")
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_redact_inner(v, sensitive) for v in node]
    return node


#: A secret shorter than this reveals nothing at all. Four visible characters
#: out of seven is not a mask, and short values are exactly the ones a reader
#: could reconstruct or recognise.
MIN_MASKABLE_LENGTH = 12


def mask_secret(value: str, visible: int = 4) -> str:
    """
    Show at most the last ``visible`` characters of an opaque secret.

    The mask is a fixed width. It used to be ``"*" * (len(value) - visible)``,
    which published the secret's exact length in every log line it appeared
    in -- enough to distinguish a 32-character API key from a 64-character
    one, and to confirm a guess about which provider issued it.
    """
    value = str(value)
    if len(value) < MIN_MASKABLE_LENGTH:
        return "[REDACTED]"
    return "*" * 8 + value[-visible:]


def safe_dump(value: Any, *, indent: Optional[int] = 2) -> str:
    """JSON dump that never raises on exotic values."""
    return json.dumps(value, indent=indent, default=str, ensure_ascii=False)


def run_in_thread(func: Callable[[], Any]) -> Any:
    """Synchronously run ``func`` in a worker thread (unblocking the loop)."""
    result: Dict[str, Any] = {}

    def _runner() -> None:
        try:
            result["value"] = func()
        except BaseException as exc:  # pragma: no cover - defensive
            result["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


_SLUG_STRIP = re.compile(r"[^a-zA-Z0-9]+")


def to_slug(value: str, sep: str = "-") -> str:
    """kebab/slug normalization for ids and names."""
    return _SLUG_STRIP.sub(sep, str(value).strip().lower()).strip(sep)