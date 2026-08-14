"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.execution.checkpoint

Purpose:
    Checkpoint management for the planning subsystem.

Captures execution state at intervals so a plan can be resumed after
an interruption without losing progress.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from planning.schemas.base import SchemaValidationError, _now
from planning.utils.ids import generate_checkpoint_id

logger = logging.getLogger("a01.planning.execution")

CheckpointSaver = Callable[[str, dict[str, Any]], Any]


@dataclass(slots=True)
class Checkpoint:
    """
    A persisted snapshot of plan execution.

    Fields:
        * Identifier, plan, and step metadata
        * Serialized state payload
        * Timestamps
    """

    plan_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    step: int = 0
    id: str = field(default_factory=generate_checkpoint_id)
    created_at: datetime = field(default_factory=_now)

    def validate(self) -> None:
        """Validate the checkpoint contract."""
        if not self.plan_id or not self.plan_id.strip():
            raise SchemaValidationError("checkpoint.plan_id must be non-empty.")

        if self.step < 0:
            raise SchemaValidationError("checkpoint.step must be non-negative.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "step": self.step,
            "payload": dict(self.payload),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Checkpoint":
        try:
            checkpoint = cls(
                plan_id=str(payload["plan_id"]),
                step=int(payload.get("step", 0)),
                payload=dict(payload.get("payload", {})),
                id=str(payload.get("id", generate_checkpoint_id())),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"invalid checkpoint payload: {exc}") from exc
        checkpoint.validate()
        return checkpoint

    def __repr__(self) -> str:
        return f"Checkpoint(id={self.id!r}, step={self.step})"


class CheckpointManager:
    """
    Creates, persists, and restores checkpoints.

    Responsibilities:
        * Checkpoint creation
        * Optional external persistence via a saver
        * Retrieval of the latest checkpoint
    """

    def __init__(
        self,
        saver: CheckpointSaver | None = None,
    ) -> None:
        self._saver = saver
        self._checkpoints: dict[str, Checkpoint] = {}
        self._lock = asyncio.Lock()

    @property
    def checkpoints(self) -> dict[str, Checkpoint]:
        """Read-only view of checkpoints by id."""
        return dict(self._checkpoints)

    def set_saver(self, saver: CheckpointSaver) -> None:
        """Install an external persistence callback."""
        self._saver = saver

    async def create(
        self,
        plan_id: str,
        payload: dict[str, Any],
        *,
        step: int = 0,
        persist: bool = True,
    ) -> Checkpoint:
        """Create and store a checkpoint."""
        checkpoint = Checkpoint(
            plan_id=plan_id,
            payload=payload,
            step=step,
        )
        checkpoint.validate()

        async with self._lock:
            self._checkpoints[checkpoint.id] = checkpoint

        if persist and self._saver is not None:
            try:
                self._saver(checkpoint.id, checkpoint.to_dict())
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("checkpoint saver failed: %s", exc)

        logger.info(
            "checkpoint created for plan %s (step %d)",
            plan_id,
            step,
        )
        return checkpoint

    async def latest(self, plan_id: str) -> Checkpoint | None:
        """Return the most recent checkpoint for a plan."""
        candidates = [
            checkpoint
            for checkpoint in self._checkpoints.values()
            if checkpoint.plan_id == plan_id
        ]

        if not candidates:
            return None

        return max(candidates, key=lambda checkpoint: checkpoint.step)

    async def list_for_plan(self, plan_id: str) -> list[Checkpoint]:
        """Return all checkpoints for a plan, oldest first."""
        return sorted(
            (
                checkpoint
                for checkpoint in self._checkpoints.values()
                if checkpoint.plan_id == plan_id
            ),
            key=lambda checkpoint: checkpoint.step,
        )

    async def restore(
        self,
        plan_id: str,
    ) -> dict[str, Any] | None:
        """Return the payload of the latest checkpoint for a plan."""
        checkpoint = await self.latest(plan_id)
        return checkpoint.payload if checkpoint is not None else None

    async def clear(self) -> None:
        """Remove all checkpoints."""
        async with self._lock:
            self._checkpoints.clear()

        logger.info("checkpoints cleared")
