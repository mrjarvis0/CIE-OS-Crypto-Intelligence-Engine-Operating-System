"""
Tools :: Lifecycle :: Rollback
==============================

Recovery from failed updates or bad configurations.

Rollback restores the previous version, configuration, dependencies and
registry state, then verifies recovery. The machine may move backward from
``failed``/``updated`` into ``configured`` so the operator can re-attempt
activation; the full history (including the failed attempt) is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from ..core.exceptions import LifecycleError
from .state import LifecycleState

__all__ = ["RollbackRequest", "RollbackResult", "RollbackManager"]


@dataclass
class RollbackRequest:
    name: str
    from_version: str = ""
    to_version: str = ""


@dataclass
class RollbackResult:
    ok: bool
    name: str = ""
    state: str = ""
    restored_version: str = ""
    message: str = ""

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "ok": self.ok,
            "name": self.name,
            "state": self.state,
            "restored_version": self.restored_version,
            "message": self.message,
        }


class RollbackManager:
    """Recovers the lifecycle machine to a previously-known-good state."""

    def __init__(
        self,
        state: LifecycleState | None = None,
        restore: Callable[[str, str], None] | None = None,
        verify: Callable[[str], bool] | None = None,
    ) -> None:
        self.state = state or LifecycleState()
        self.restore = restore
        self.verify = verify

    def rollback(self, request: RollbackRequest) -> RollbackResult:
        try:
            if self.restore is not None:
                self.restore(request.name, request.to_version)
            if self.verify is not None and not self.verify(request.name):
                raise LifecycleError(f"recovery verification failed for {request.name!r}")
            self.state.transition("configured", reason=f"rollback to {request.to_version}")
            return RollbackResult(
                ok=True,
                name=request.name,
                state=self.state.current,
                restored_version=request.to_version,
                message="rolled back",
            )
        except LifecycleError as exc:
            return RollbackResult(
                ok=False, name=request.name, state=self.state.current, message=str(exc)
            )