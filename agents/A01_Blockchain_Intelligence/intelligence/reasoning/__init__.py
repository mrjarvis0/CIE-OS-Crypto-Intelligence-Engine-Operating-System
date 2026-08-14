"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    intelligence.reasoning

Purpose:
    Structured reasoning engines for the intelligence layer.

    The reasoning package implements explicit, inspectable reasoning
    patterns (chain-of-thought, tree-of-thought, ReAct, reflection,
    self-critique, self-verification, constraint reasoning) so that
    intelligence is derived through auditable steps rather than opaque
    single-shot answers.

Submodules
----------
reasoning_engine    Central reasoning orchestrator.
chain_of_thought    Linear step-by-step reasoning.
tree_of_thought     Multi-branch exploration.
react               Reason-Act cycle over tools.
reflection          Post-hoc reflection on outputs.
critic              Self-critique and counter-argument generation.
self_verification   Verify conclusions against evidence.
decision            Decision making from reasoning.
planner_bridge      Bridge between reasoning and planning.
constraints         Constraint-aware reasoning.
"""

from __future__ import annotations

from .chain_of_thought import ChainOfThought
from .constraints import ConstraintReasoner
from .critic import Critic
from .decision import DecisionEngine
from .planner_bridge import PlannerBridge
from .react import React
from .reasoning_engine import ReasoningEngine
from .reflection import Reflection
from .self_verification import SelfVerifier
from .tree_of_thought import TreeOfThought

__all__ = [
    "ReasoningEngine",
    "ChainOfThought",
    "TreeOfThought",
    "React",
    "Reflection",
    "Critic",
    "SelfVerifier",
    "DecisionEngine",
    "PlannerBridge",
    "ConstraintReasoner",
]
