"""
Tools :: Lifecycle :: Migration
===============================

Structural changes to a tool's data, config, metadata or registry entry.

Migrations are declarative, versioned steps that run in order and are
recorded against the machine. Forward and backward compatibility are
supported where possible: a failed forward migration can be reverted by its
corresponding ``backward`` step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from ..core.exceptions import LifecycleError
from .state import LifecycleState

__all__ = ["MigrationStep", "MigrationRequest", "MigrationResult", "Migrator"]


@dataclass
class MigrationStep:
    """One declarative data/schema migration."""

    name: str
    version: str = ""
    forward: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None
    backward: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class MigrationRequest:
    name: str
    target_version: str = ""
    current_version: str = ""
    steps: Sequence[MigrationStep] = field(default_factory=list)


@dataclass
class MigrationResult:
    ok: bool
    name: str = ""
    applied: Sequence[str] = field(default_factory=list)
    state: str = ""
    message: str = ""

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "ok": self.ok,
            "name": self.name,
            "applied": list(self.applied),
            "state": self.state,
            "message": self.message,
        }


class Migrator:
    """Applies migration steps in order and transitions the machine."""

    def __init__(self, state: LifecycleState | None = None) -> None:
        self.state = state or LifecycleState()

    def migrate(self, request: MigrationRequest, *, payload: Optional[Mapping[str, Any]] = None) -> MigrationResult:
        applied: list[str] = []
        try:
            for step in request.steps:
                if step.forward is not None:
                    payload = step.forward(payload or step.data)
                applied.append(step.name)
            self.state.transition("migrated", reason=f"migrate to {request.target_version}")
            return MigrationResult(
                ok=True, name=request.name, applied=applied, state=self.state.current, message="migrated"
            )
        except LifecycleError as exc:
            return MigrationResult(
                ok=False, name=request.name, applied=applied, state=self.state.current, message=str(exc)
            )

    def rollback_steps(
        self, steps: Sequence[MigrationStep], *, payload: Optional[Mapping[str, Any]] = None
    ) -> Mapping[str, Any]:
        """Apply ``backward`` steps in reverse, returning the final payload."""
        for step in reversed(steps):
            if step.backward is not None:
                payload = step.backward(payload)
        return payload