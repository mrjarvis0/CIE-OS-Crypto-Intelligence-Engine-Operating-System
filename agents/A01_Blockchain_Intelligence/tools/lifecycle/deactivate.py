"""
Tools :: Lifecycle :: Deactivate
================================

Temporary deactivation of a tool.

Stops execution, drains in-flight requests, releases runtime resources and
removes runtime hooks while **preserving configuration and user data**.
Deactivation is reversible: ``activate`` may later move the tool back to
``running``/``activated``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from ..core.exceptions import LifecycleError
from .state import LifecycleState

__all__ = ["DeactivationRequest", "DeactivationResult", "Deactivator"]


@dataclass
class DeactivationRequest:
    name: str
    reason: str = "operator"
    drain: bool = True        # wait for in-flight requests to finish
    preserve_config: bool = True


@dataclass
class DeactivationResult:
    ok: bool
    name: str = ""
    state: str = ""
    message: str = ""

    def as_dict(self) -> Mapping[str, Any]:
        return {"ok": self.ok, "name": self.name, "state": self.state, "message": self.message}


class Deactivator:
    """Moves a tool into a paused (reversible) state."""

    def __init__(
        self,
        state: LifecycleState | None = None,
        drain: Callable[[str], int] | None = None,
        release: Callable[[str], None] | None = None,
    ) -> None:
        self.state = state or LifecycleState()
        self.drain = drain
        self.release = release

    def deactivate(self, request: DeactivationRequest) -> DeactivationResult:
        try:
            if request.drain and self.drain is not None:
                self.drain(request.name)
            if self.release is not None:
                self.release(request.name)
            self.state.transition("paused", reason=request.reason)
            return DeactivationResult(
                ok=True, name=request.name, state=self.state.current, message="paused"
            )
        except LifecycleError as exc:
            return DeactivationResult(
                ok=False, name=request.name, state=self.state.current, message=str(exc)
            )