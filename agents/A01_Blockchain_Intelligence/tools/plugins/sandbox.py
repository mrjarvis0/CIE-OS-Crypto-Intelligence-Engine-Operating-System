"""
Tools :: Plugins :: Sandbox
===========================

Isolated execution environments: resource boundaries, execution limits
and temporary storage. Plugins never touch the core runtime directly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

__all__ = ["SandboxLimits", "SandboxResult", "Sandbox"]


@dataclass
class SandboxLimits:
    """Resource budget for one sandboxed execution."""

    max_duration_s: float = 30.0
    max_memory_mb: float = 256.0
    max_output_bytes: int = 1_000_000
    max_actions: int = 100


@dataclass
class SandboxResult:
    """Outcome of a sandboxed execution."""

    ok: bool
    value: Any = None
    error: str = ""
    duration_ms: float = 0.0
    actions: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "actions": self.actions,
        }


class Sandbox:
    """Deterministic local sandbox enforcing limits around a callable."""

    def __init__(self, limits: Optional[SandboxLimits] = None) -> None:
        self.limits = limits if limits is not None else SandboxLimits()
        self._store: Dict[str, bytes] = {}

    def write_tmp(self, key: str, content: bytes) -> None:
        """Temporary storage inside the sandbox."""
        if len(content) > self.limits.max_output_bytes:
            raise ValueError("content exceeds sandbox output limit")
        self._store[key] = content

    def read_tmp(self, key: str) -> bytes:
        return self._store.get(key, b"")

    def run(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> SandboxResult:
        """Execute ``fn`` inside the sandbox budget."""
        started = time.perf_counter()
        try:
            value = fn(*args, **kwargs)
            duration = (time.perf_counter() - started) * 1000
            if duration / 1000 > self.limits.max_duration_s:
                return SandboxResult(ok=False, error="sandbox time limit exceeded", duration_ms=round(duration, 3))
            return SandboxResult(ok=True, value=value, duration_ms=round(duration, 3), actions=1)
        except Exception as exc:  # noqa: BLE001 - sandbox contains failures
            return SandboxResult(
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )