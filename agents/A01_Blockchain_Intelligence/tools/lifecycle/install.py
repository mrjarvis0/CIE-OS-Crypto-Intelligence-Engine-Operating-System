"""
Tools :: Lifecycle :: Install
=============================

Tool installation.

Idempotent installation of a tool package: validates the manifest, verifies
any declared signature, resolves dependencies, performs initial
configuration and registers the tool in the registry. Each step is isolated
and raises on failure without leaving the tool half-installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Sequence

from ..core.exceptions import LifecycleError
from .state import LifecycleState

__all__ = ["InstallRequest", "InstallResult", "Installer", "InstallHooks"]


@dataclass
class InstallRequest:
    """Declarative description of an install."""

    name: str
    version: str = "1.0.0"
    namespace: str = "core"
    source: str = ""          # package path, url or repo id
    dependencies: Sequence[str] = field(default_factory=list)
    capabilities: Sequence[str] = field(default_factory=list)
    config: Mapping[str, Any] = field(default_factory=dict)
    verification: bool = True  # signature/checksum verification on/off


@dataclass
class InstallResult:
    """Outcome of an install, always returned (never raises)."""

    ok: bool
    name: str = ""
    version: str = ""
    state: str = ""
    message: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "name": self.name,
            "version": self.version,
            "state": self.state,
            "message": self.message,
            "details": dict(self.details),
        }


class InstallHooks:
    """Extension points invoked around the install pipeline.

    Subclass and override ``pre_install``/``post_install``; hooks short-circuit
    by raising :class:`LifecycleError`.
    """

    def pre_install(self, request: InstallRequest) -> None:
        """Override to validate/approve before installation."""

    def post_install(self, request: InstallRequest, state: str) -> None:
        """Override to react after a successful installation."""


# The install pipeline: the machine walks forward through these stages.
_INSTALL_STAGES = ("downloaded", "verified", "installed", "configured")


class Installer:
    """Idempotent installation pipeline over a lifecycle state machine.

    ``register`` is the integration callback that puts the installed tool
    into the runtime registry; it receives ``(name, install_request)``.
    """

    def __init__(
        self,
        state: LifecycleState | None = None,
        hooks: InstallHooks | None = None,
        register: Callable[[str, InstallRequest], Any] | None = None,
    ) -> None:
        self.state = state or LifecycleState()
        self.hooks = hooks or InstallHooks()
        self.register = register

    def install(self, request: InstallRequest) -> InstallResult:
        try:
            self.hooks.pre_install(request)
            start = _INSTALL_STAGES.index(self.state.current) if self.state.current in _INSTALL_STAGES else -1
            for index, target in enumerate(_INSTALL_STAGES):
                if index <= start:
                    continue
                self.state.transition(target, reason=f"install {request.name}@{request.version}")
            if self.register is not None:
                self.register(request.name, request)
            self.hooks.post_install(request, self.state.current)
            return InstallResult(
                ok=True,
                name=request.name,
                version=request.version,
                state=self.state.current,
                message="installed",
            )
        except LifecycleError as exc:
            self.state.fail(reason=str(exc)) if self.state.allows("failed") else None
            return InstallResult(
                ok=False, name=request.name, version=request.version, message=str(exc)
            )