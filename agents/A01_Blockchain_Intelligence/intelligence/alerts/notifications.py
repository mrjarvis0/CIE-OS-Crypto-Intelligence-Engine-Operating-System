"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.alerts.notifications

Purpose:
    Alert notification dispatch.
"""

from __future__ import annotations

from typing import Any, Callable

from .alerts import Alert


class Notifier:
    """
    Dispatches alerts to registered handlers.
    """

    def __init__(self) -> None:
        self._handlers: list[Callable[[Alert], Any]] = []

    def add_handler(self, handler: Callable[[Alert], Any]) -> "Notifier":
        """
        Register an alert handler.
        """
        self._handlers.append(handler)
        return self

    def notify(self, alert: Alert) -> list[Any]:
        """
        Deliver an alert to all handlers.
        """
        return [handler(alert) for handler in self._handlers]
