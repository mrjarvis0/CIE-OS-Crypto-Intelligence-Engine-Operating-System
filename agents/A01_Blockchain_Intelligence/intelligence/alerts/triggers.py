"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.alerts.triggers

Purpose:
    Alert trigger evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..utils.helpers import new_id
from .alerts import Alert


@dataclass(slots=True)
class Trigger:
    """
    A named condition that fires an alert.
    """

    name: str
    condition: Callable[[dict[str, Any]], bool]
    severity: str = "info"
    title: str = ""


class TriggerEvaluator:
    """
    Evaluates triggers against a subject/context.

    Fired alerts get a unique id per firing (so repeat firings are
    individually addressable), receive a snapshot copy of the context
    as payload, and are recorded in a history for audit.
    """

    def __init__(self) -> None:
        self._triggers: list[Trigger] = []
        self._history: list[Alert] = []

    def add(
        self,
        name: str,
        condition: Callable[[dict[str, Any]], bool],
        severity: str = "info",
        title: str | None = None,
    ) -> "TriggerEvaluator":
        """
        Register a trigger.
        """
        self._triggers.append(
            Trigger(
                name=name,
                condition=condition,
                severity=severity,
                title=title or name,
            )
        )
        return self

    def evaluate(self, context: dict[str, Any]) -> list[Alert]:
        """
        Fire alerts for all satisfied triggers.

        A raising condition is skipped rather than aborting the whole
        evaluation, so one broken trigger cannot suppress the rest.
        """
        alerts: list[Alert] = []
        snapshot = dict(context)
        for trigger in self._triggers:
            try:
                if trigger.condition(snapshot):
                    alert = Alert(
                        alert_id=new_id("alert"),
                        title=trigger.title,
                        severity=trigger.severity,
                        trigger=trigger.name,
                        payload=snapshot,
                    )
                    alerts.append(alert)
                    self._history.append(alert)
            except Exception:  # noqa: BLE001
                continue
        return alerts

    @property
    def history(self) -> list[Alert]:
        """
        All alerts fired across evaluations.
        """
        return list(self._history)
