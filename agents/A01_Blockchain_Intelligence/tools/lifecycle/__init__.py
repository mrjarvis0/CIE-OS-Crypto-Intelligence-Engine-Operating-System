"""
Tools :: Lifecycle
==================

Operational lifecycle management for every tool.

A tool is not simply "installed" and "executed": it progresses through a
well-defined state chain, and every transition is validated, recorded in an
immutable history, and recoverable. This package implements the state
machine plus each lifecycle operation as an isolated module.

Modules:

* :mod:`~.state` -- the transition machine and history (source of truth).
* :mod:`~.install` -- idempotent installation + registration.
* :mod:`~.activate` -- activation into runtime use.
* :mod:`~.deactivate` -- temporary pause with config preservation.
* :mod:`~.update` -- validated version upgrades.
* :mod:`~.rollback` -- recovery from failed updates/configs.
* :mod:`~.retire` -- graceful withdrawal from discovery.
* :mod:`~.migration` -- versioned data/schema migration steps.
* :mod:`~.cleanup` -- resource removal after retirement.

The public entry point is :class:`Lifecycle` which ties a state machine to a
small set of named operations.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .state import LifecycleState, StateRecord, ALL_STATES
from .install import Installer, InstallRequest, InstallResult, InstallHooks
from .activate import Activator, ActivationRequest, ActivationResult, ActivationHooks
from .deactivate import Deactivator, DeactivationRequest, DeactivationResult
from .update import Updater, UpdateRequest, UpdateResult
from .rollback import RollbackManager, RollbackRequest, RollbackResult
from .retire import Retirer, RetireRequest, RetireResult
from .migration import Migrator, MigrationStep, MigrationRequest, MigrationResult
from .cleanup import Cleaner, CleanupRequest, CleanupResult
from .state import State

__all__ = [
    "Lifecycle",
    "LifecycleState",
    "StateRecord",
    "ALL_STATES",
    "Installer",
    "InstallRequest",
    "InstallResult",
    "InstallHooks",
    "Activator",
    "ActivationRequest",
    "ActivationResult",
    "ActivationHooks",
    "Deactivator",
    "DeactivationRequest",
    "DeactivationResult",
    "Updater",
    "UpdateRequest",
    "UpdateResult",
    "RollbackManager",
    "RollbackRequest",
    "RollbackResult",
    "Retirer",
    "RetireRequest",
    "RetireResult",
    "Migrator",
    "MigrationStep",
    "MigrationRequest",
    "MigrationResult",
    "Cleaner",
    "CleanupRequest",
    "CleanupResult",
    "State",
]


class Lifecycle:
    """Facade bundling a state machine with all lifecycle operations."""

    def __init__(
        self,
        *,
        name: str = "",
        state: Optional[LifecycleState] = None,
        register: Optional[Any] = None,
    ) -> None:
        self.name = name
        self.state = state or LifecycleState()
        self._register = register
        self.installer = Installer(self.state, register=self._register)
        self.activator = Activator(self.state)
        self.deactivator = Deactivator(self.state)
        self.updater = Updater(self.state)
        self.rollback = RollbackManager(self.state)
        self.retirer = Retirer(self.state)
        self.migrator = Migrator(self.state)
        self.cleaner = Cleaner(self.state)

    @property
    def current(self) -> str:
        return self.state.current

    def transition(self, target: str, *, reason: str = "", operator: str = "") -> "StateRecord":
        return self.state.transition(target, reason=reason, operator=operator)

    def as_dict(self) -> Mapping[str, Any]:
        return {"name": self.name, "state": self.state.as_dict()}