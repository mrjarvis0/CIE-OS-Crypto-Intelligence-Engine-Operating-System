"""
Tools :: Lifecycle :: Cleanup
=============================

Removal of unused resources after retirement.

Cleanup deletes temporary files, empties caches and removes stale metadata.
It must never remove active resources: the machine only allows cleanup for
tools already in ``retired``/``archived``, and the manager double-checks the
tool is not currently executing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from ..core.exceptions import LifecycleError
from .state import LifecycleState

__all__ = ["CleanupRequest", "CleanupResult", "Cleaner"]


@dataclass
class CleanupRequest:
    name: str
    remove_metadata: bool = True
    remove_tmp: bool = True
    clear_cache: bool = True
    force: bool = False


@dataclass
class CleanupResult:
    ok: bool
    name: str = ""
    state: str = ""
    message: str = ""
    removed: Sequence[str] = ()

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "ok": self.ok,
            "name": self.name,
            "state": self.state,
            "message": self.message,
            "removed": list(self.removed),
        }


class Cleaner:
    """Removes retired/archived tool resources without touching active tools."""

    def __init__(
        self,
        state: LifecycleState | None = None,
        clear_fn: Callable[[str], Sequence[str]] | None = None,
        removing_fn: Callable[[str], Sequence[str]] | None = None,
    ) -> None:
        self.state = state or LifecycleState()
        self.clear_fn = clear_fn
        self.removing_fn = removing_fn

    def cleanup(self, request: CleanupRequest) -> CleanupResult:
        removed: list[str] = []
        try:
            if self.state.current not in ("retired", "archived") and not request.force:
                raise LifecycleError(
                    f"cannot clean %r while state=%r" % (request.name, self.state.current)
                )
            if request.clear_cache and self.clear_fn is not None:
                removed.extend(self.clear_fn(request.name))
            if request.remove_metadata and self.removing_fn is not None:
                removed.extend(self.removing_fn(request.name))
            self.state.transition("removed", reason="cleanup") if self.state.allows("removed") else None
            return CleanupResult(
                ok=True,
                name=request.name,
                state=self.state.current,
                message="cleaned",
                removed=removed,
            )
        except LifecycleError as exc:
            return CleanupResult(
                ok=False, name=request.name, state=self.state.current, message=str(exc)
            )