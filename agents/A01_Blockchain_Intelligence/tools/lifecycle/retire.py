"""
Tools :: Lifecycle :: Retire
============================

Graceful retirement of obsolete tools.

Retirement marks a tool deprecated, disables discovery, archives metadata and
prevents new executions while leaving historical audit records intact. The
machine finishes in ``archived`` and may be fully ``removed`` later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from ..core.exceptions import LifecycleError
from .state import LifecycleState

__all__ = ["RetireRequest", "RetireResult", "Retirer"]


@dataclass
class RetireRequest:
    name: str
    reason: str = ""
    archive_metadata: bool = True
    notify: bool = True
    block_new: bool = True


@dataclass
class RetireResult:
    ok: bool
    name: str = ""
    state: str = ""
    message: str = ""

    def as_dict(self) -> Mapping[str, Any]:
        return {"ok": self.ok, "name": self.name, "state": self.state, "message": self.message}


class Retirer:
    """Transitions a tool through retire -> archived."""

    def __init__(
        self,
        state: LifecycleState | None = None,
        archive: Callable[[str], Any] | None = None,
        notify: Callable[[str, str], Any] | None = None,
    ) -> None:
        self.state = state or LifecycleState()
        self.archive = archive
        self.notify = notify

    def retire(self, request: RetireRequest) -> RetireResult:
        try:
            self.state.transition("retired", reason=request.reason)
            if request.notify and self.notify is not None:
                self.notify(request.name, request.reason)
            if request.archive_metadata and self.state.allows("archived"):
                if self.archive is not None:
                    self.archive(request.name)
                self.state.transition("archived", reason="archive metadata")
            return RetireResult(
                ok=True, name=request.name, state=self.state.current, message="retired"
            )
        except LifecycleError as exc:
            return RetireResult(
                ok=False, name=request.name, state=self.state.current, message=str(exc)
            )