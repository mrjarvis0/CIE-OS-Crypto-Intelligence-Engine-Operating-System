"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    intelligence.core

Purpose:
    Heart of the intelligence system.

    Provides the IntelligenceEngine, AnalysisPipeline, Manager,
    context, state, runtime, configuration, and session objects that
    orchestrate the full intelligence cycle for an investigation.

Submodules
----------
engine         IntelligenceEngine - top-level entry point.
pipeline       AnalysisPipeline - ordered stage orchestration.
manager        IntelligenceManager - lifecycle and coordination.
context        IntelligenceContext - shared investigation state.
state          EngineState - lifecycle state machine.
runtime        IntelligenceRuntime - runtime facilities.
configuration  IntelligenceConfig - engine configuration.
session        IntelligenceSession - per-investigation session.
"""

from __future__ import annotations

from .configuration import IntelligenceConfig
from .context import IntelligenceContext
from .engine import IntelligenceEngine
from .manager import IntelligenceManager
from .pipeline import AnalysisPipeline, StageResult
from .runtime import IntelligenceRuntime
from .session import IntelligenceSession
from .state import EngineState, InvalidTransitionError, validate_transition

__all__ = [
    "IntelligenceConfig",
    "IntelligenceContext",
    "IntelligenceEngine",
    "IntelligenceManager",
    "AnalysisPipeline",
    "StageResult",
    "IntelligenceRuntime",
    "IntelligenceSession",
    "EngineState",
    "InvalidTransitionError",
    "validate_transition",
]
