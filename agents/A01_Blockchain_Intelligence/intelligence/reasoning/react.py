"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reasoning.react

Purpose:
    ReAct (Reason-Act) cycle: alternate reasoning and tool actions.

    Each iteration asks a planner for the next (action, arguments),
    executes the tool, records the observation, and feeds the result
    back into the context so the loop genuinely progresses. Without a
    planner, a single configured action is executed once and the loop
    concludes, so the cycle always terminates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .reasoning_engine import ReasoningStep

Planner = Callable[[dict[str, Any]], tuple[str, dict[str, Any]]]


@dataclass
class ToolCall:
    """
    A reason-act tool invocation.
    """

    name: str
    arguments: dict[str, Any]


class React:
    """
    Alternates reasoning steps with tool calls until a conclusion.
    """

    def __init__(self, max_iterations: int = 8) -> None:
        self._max_iterations = max_iterations

    @staticmethod
    def _default_planner(context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """
        Execute the configured action at most once, then conclude.
        """
        if context.get("_react_executed"):
            return ("conclude", {})
        return (context.get("action", "conclude"), context.get("arguments", {}))

    def cycle(
        self,
        question: str,
        tools: dict[str, Callable[..., Any]] | None = None,
        context: dict[str, Any] | None = None,
        planner: Planner | None = None,
    ) -> list[ReasoningStep]:
        """
        Run the reason-act loop using the provided tools.

        Parameters
        ----------
        question
            The question under investigation.
        tools
            Available tool callables keyed by action name.
        context
            Mutable state observed by the planner; the loop updates it
            with ``last_action``/``last_result`` after each execution.
        planner
            Optional callable returning the next ``(action, arguments)``
            from the current context. Defaults to a single-shot planner.
        """
        context = dict(context or {})
        tools = tools or {}
        planner = planner or self._default_planner
        steps: list[ReasoningStep] = [
            ReasoningStep(kind="observation", content=question)
        ]

        for iteration in range(self._max_iterations):
            try:
                action, arguments = planner(dict(context))
            except Exception as exc:  # noqa: BLE001 - planner boundary
                steps.append(
                    ReasoningStep(
                        kind="error", content=f"planner failed: {exc}"
                    )
                )
                break

            steps.append(
                ReasoningStep(
                    kind="thought",
                    content=f"deciding next action (iteration {iteration + 1})",
                )
            )
            if action == "conclude":
                steps.append(ReasoningStep(kind="conclusion", content="concluding"))
                break
            if action not in tools:
                steps.append(
                    ReasoningStep(kind="error", content=f"unknown tool {action}")
                )
                break
            try:
                result = tools[action](**arguments)
            except Exception as exc:  # noqa: BLE001 - tool boundary
                steps.append(
                    ReasoningStep(
                        kind="error",
                        content=f"tool {action} failed: {exc}",
                        metadata={"tool": action},
                    )
                )
                break
            steps.append(
                ReasoningStep(
                    kind="observation",
                    content=f"tool {action} -> {result}",
                    metadata={"tool": action},
                )
            )
            context["last_action"] = action
            context["last_result"] = result
            context["_react_executed"] = True

        return steps
