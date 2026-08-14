"""
Tools :: Lifecycle :: Update
============================

Upgrade existing tools to a new version.

Performs semantic-version comparison, pre-flight validation and
compatibility checks before transitioning the machine. On success the tool
moves to ``updated``; the caller may then continue to ``running``. A failed
update records the failure so :mod:`rollback` can recover cleanly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from ..core.exceptions import LifecycleError
from ..core.version import is_compatible
from .state import LifecycleState

__all__ = ["UpdateRequest", "UpdateResult", "Updater"]


@dataclass
class UpdateRequest:
    name: str
    target_version: str
    current_version: str = ""
    compatibility: Sequence[str] = ()
    preflight: bool = True


@dataclass
class UpdateResult:
    ok: bool
    name: str = ""
    from_version: str = ""
    to_version: str = ""
    state: str = ""
    message: str = ""

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "ok": self.ok,
            "name": self.name,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "state": self.state,
            "message": self.message,
        }


class Updater:
    """Performs a validated version upgrade on the lifecycle machine."""

    def __init__(
        self,
        state: LifecycleState | None = None,
        preflight: Callable[[UpdateRequest], None] | None = None,
        apply: Callable[[UpdateRequest], None] | None = None,
    ) -> None:
        self.state = state or LifecycleState()
        self.preflight_cb = preflight
        self.apply_cb = apply

    def update(self, request: UpdateRequest) -> UpdateResult:
        try:
            if request.preflight:
                for compatible in request.compatibility:
                    if not is_compatible(request.target_version, compatible):
                        raise LifecycleError(
                            f"target {request.target_version} incompatible with {compatible!r}"
                        )
                if request.target_version == request.current_version:
                    raise LifecycleError("target version equals current version")
            if self.preflight_cb is not None:
                self.preflight_cb(request)
            self.state.transition("updated", reason=f"update {request.target_version}")
            if self.apply_cb is not None:
                self.apply_cb(request)
            return UpdateResult(
                ok=True,
                name=request.name,
                from_version=request.current_version,
                to_version=request.target_version,
                state=self.state.current,
                message="updated",
            )
        except LifecycleError as exc:
            return UpdateResult(
                ok=False,
                name=request.name,
                to_version=request.target_version,
                state=self.state.current,
                message=str(exc),
            )