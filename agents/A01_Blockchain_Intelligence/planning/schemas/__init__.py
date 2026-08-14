"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    planning.schemas

Purpose:
    Canonical data models for the planning subsystem.

Each schema object is a slots dataclass with ``validate()``,
``to_dict()``, and ``from_dict()`` support. Schemas are the contract
boundary: business logic never consumes raw external payloads.
"""

from __future__ import annotations

# ==============================================================================
# Base
# ==============================================================================

from .base import (
    SCHEMA_VERSION,
    SchemaError,
    SchemaSerializationError,
    SchemaValidationError,
)

# ==============================================================================
# Goal
# ==============================================================================

from .goal import GoalSchema

# ==============================================================================
# Task
# ==============================================================================

from .task import TaskSchema

# ==============================================================================
# Plan
# ==============================================================================

from .plan import PlanSchema

# ==============================================================================
# State
# ==============================================================================

from .state import PlanStateSchema

# ==============================================================================
# Execution
# ==============================================================================

from .execution import ExecutionSchema

# ==============================================================================
# Public API
# ==============================================================================

__all__ = [
    # Base
    "SCHEMA_VERSION",
    "SchemaError",
    "SchemaValidationError",
    "SchemaSerializationError",
    # Goal
    "GoalSchema",
    # Task
    "TaskSchema",
    # Plan
    "PlanSchema",
    # State
    "PlanStateSchema",
    # Execution
    "ExecutionSchema",
]
