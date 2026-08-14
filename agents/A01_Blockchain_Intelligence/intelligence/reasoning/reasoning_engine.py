"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reasoning.reasoning_engine

Purpose:
    Central reasoning orchestrator and shared reasoning-step model.

    Ships with built-in strategies (chain-of-thought, tree-of-thought,
    react, reflection, constraint) and allows custom strategies to be
    registered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Callable


class ReasoningStrategy(StrEnum):
    """
    Supported reasoning strategy identifiers.
    """

    CHAIN_OF_THOUGHT = "chain_of_thought"
    TREE_OF_THOUGHT = "tree_of_thought"
    REACT = "react"
    REFLECTION = "reflection"
    CONSTRAINT = "constraint"


@dataclass(slots=True)
class ReasoningStep:
    """
    A single auditable step in a reasoning trace.
    """

    kind: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


class ReasoningEngine:
    """
    Orchestrates a reasoning strategy over a question and context.

    Ships with built-in strategies (chain-of-thought, tree-of-thought,
    react, reflection, constraint) and allows custom strategies to be
    registered.
    """

    def __init__(self) -> None:
        self._strategies: dict[str, Callable[..., list[ReasoningStep]]] = {}
        self._trace: list[ReasoningStep] = []
        self._register_builtins()

    def _register_builtins(self) -> None:
        # Local imports to avoid circular dependency with the modules
        # that import ReasoningStep from this module.
        from .chain_of_thought import ChainOfThought
        from .constraints import ConstraintReasoner
        from .react import React
        from .tree_of_thought import TreeOfThought

        self.register(
            ReasoningStrategy.CHAIN_OF_THOUGHT.value, ChainOfThought().reason
        )
        self.register(
            ReasoningStrategy.TREE_OF_THOUGHT.value, TreeOfThought().reason
        )
        self.register(ReasoningStrategy.REACT.value, React().cycle)
        self.register(
            ReasoningStrategy.REFLECTION.value, self._reflection_strategy
        )
        self.register(
            ReasoningStrategy.CONSTRAINT.value, ConstraintReasoner().reason
        )

    @staticmethod
    def _reflection_strategy(
        question: str, context: dict[str, Any] | None = None, **_: Any
    ) -> list[ReasoningStep]:
        """Reflection adapter: reflect over the trace carried in context."""
        from .reflection import Reflection

        return Reflection().reflect(list((context or {}).get("trace", [])))

    def register(
        self, name: str, strategy: Callable[..., list[ReasoningStep]]
    ) -> "ReasoningEngine":
        """
        Register a named reasoning strategy.
        """
        self._strategies[name] = strategy
        return self

    def reason(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        strategy: ReasoningStrategy | str = ReasoningStrategy.CHAIN_OF_THOUGHT,
        **kwargs: Any,
    ) -> list[ReasoningStep]:
        """
        Run a named strategy and record its trace.
        """
        fn = self._strategies.get(str(strategy))
        if fn is None:
            raise ValueError(f"unknown reasoning strategy: {strategy}")
        steps = fn(question=question, context=context or {}, **kwargs)
        self._trace.extend(steps)
        return list(steps)

    @property
    def trace(self) -> list[ReasoningStep]:
        """
        Full reasoning trace across all invocations.
        """
        return list(self._trace)
