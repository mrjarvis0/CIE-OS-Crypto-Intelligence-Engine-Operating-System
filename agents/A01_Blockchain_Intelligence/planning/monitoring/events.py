"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.monitoring.events

Purpose:
    Event emission and subscription for the planning subsystem.

Provides a lightweight publish/subscribe bus over ``EventType``
constants so components can react to lifecycle changes without
tight coupling.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from planning.schemas.base import _now
from planning.utils.constants import EventType
from planning.utils.ids import generate_correlation_id

logger = logging.getLogger("a01.planning.monitoring")

Subscriber = Callable[[dict[str, Any]], Any]


@dataclass(slots=True)
class PlanEvent:
    """
    A single emitted planning event.

    Fields:
        * Event type and correlation id
        * Optional plan / task / source reference
        * Payload and timestamp
    """

    type: EventType
    correlation_id: str = field(default_factory=generate_correlation_id)
    plan_id: str | None = None
    task_id: str | None = None
    source: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    emitted_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "correlation_id": self.correlation_id,
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "source": self.source,
            "payload": dict(self.payload),
            "emitted_at": self.emitted_at.isoformat(),
        }


class EventBus:
    """
    Publish/subscribe bus for planning events.

    Responsibilities:
        * Subscriber registration
        * Event emission
        * Event history retention
    """

    def __init__(
        self,
        *,
        history_limit: int = 1000,
    ) -> None:
        self._subscribers: dict[EventType, list[Subscriber]] = {}
        self._wildcards: list[Subscriber] = []
        self._history: list[PlanEvent] = []
        self._history_limit = history_limit
        self._lock = asyncio.Lock()

    def subscribe(
        self,
        event_type: EventType,
        subscriber: Subscriber,
    ) -> None:
        """Subscribe a callback to a specific event type."""
        self._subscribers.setdefault(event_type, []).append(subscriber)

    def subscribe_all(self, subscriber: Subscriber) -> None:
        """Subscribe a callback to every event type."""
        self._wildcards.append(subscriber)

    async def emit(self, event: PlanEvent) -> None:
        """
        Deliver an event to matching subscribers and record it in
        history.
        """

        callbacks = list(self._wildcards)
        callbacks.extend(self._subscribers.get(event.type, []))

        for callback in callbacks:
            try:
                result = callback(event.to_dict())
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "event subscriber %r failed: %s",
                    getattr(callback, "__name__", callback),
                    exc,
                )

        async with self._lock:
            self._history.append(event)

            if self._history_limit > 0:
                self._history = self._history[-self._history_limit :]

    async def history(
        self,
        *,
        event_type: EventType | None = None,
        limit: int = 100,
    ) -> list[PlanEvent]:
        """Return recent events, optionally filtered by type."""
        events = self._history

        if event_type is not None:
            events = [event for event in events if event.type == event_type]

        return events[-limit:]

    async def clear(self) -> None:
        """Clear event history."""
        async with self._lock:
            self._history.clear()
