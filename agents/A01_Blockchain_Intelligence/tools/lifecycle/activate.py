"""
Tools :: Lifecycle :: Activate
==============================

Activation: enabling a tool for runtime use.

Moves the machine into ``activated``/``running``, runs initialization and
health verification, then makes the tool discoverable via the integration
callback. Activation may take the tool straight to ``running`` when runtime
integration is supplied.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from ..core.exceptions import LifecycleError
from .state import LifecycleState

__all__ = ["ActivationRequest", "ActivationResult", "Activator", "ActivationHooks"]


@dataclass
class ActivationRequest:
    name: str
    version: str = ""
    warm_cache: bool = True
    verify_health: bool = True
    capabilities: tuple = ()


@dataclass
class ActivationResult:
    ok: bool
    name: str = ""
    state: str = ""
    message: str = ""

    def as_dict(self) -> Mapping[str, Any]:
        return {"ok": self.ok, "name": self.name, "state": self.state, "message": self.message}


class ActivationHooks:
    def pre_activate(self, request: ActivationRequest) -> None:
        ...

    def post_activate(self, request: ActivationRequest, state: str) -> None:
        ...


class Activator:
    """Transitions a tool into the activated/running state."""

    def __init__(
        self,
        state: LifecycleState | None = None,
        hooks: ActivationHooks | None = None,
        initialize: Callable[[str], Any] | None = None,
        warmup: Callable[[str], Any] | None = None,
    ) -> None:
        self.state = state or LifecycleState()
        self.hooks = hooks or ActivationHooks()
        self.initialize = initialize
        self.warmup = warmup

    def activate(self, request: ActivationRequest, *, run: bool = False) -> ActivationResult:
        try:
            self.hooks.pre_activate(request)
            if self.initialize is not None:
                self.initialize(request.name)
            self.state.transition("activated", reason=f"activate {request.name}")
            if run and self.state.allows("running"):
                self.state.transition("running", reason=f"run {request.name}")
            if request.warm_cache and self.warmup is not None:
                self.warmup(request.name)
            self.hooks.post_activate(request, self.state.current)
            return ActivationResult(
                ok=True, name=request.name, state=self.state.current, message="activated"
            )
        except LifecycleError as exc:
            return ActivationResult(
                ok=False, name=request.name, state=self.state.current, message=str(exc)
            )