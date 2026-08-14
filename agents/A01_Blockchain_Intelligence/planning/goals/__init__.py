"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    planning.goals

Purpose:
    Goal lifecycle, objectives, assumptions, constraints, and success
    evaluation for the planning subsystem.
"""

from __future__ import annotations

# ==============================================================================
# Goal
# ==============================================================================

from .goal import (
    GoalError,
    GoalManager,
    GoalNotFoundError,
    InvalidGoalTransitionError,
    now_iso,
)

# ==============================================================================
# Objective
# ==============================================================================

from .objective import (
    Objective,
    ObjectiveError,
    ObjectiveManager,
    ObjectiveNotFoundError,
)

# ==============================================================================
# Assumptions
# ==============================================================================

from .assumptions import (
    Assumption,
    AssumptionError,
    AssumptionManager,
    AssumptionNotFoundError,
)

# ==============================================================================
# Constraints
# ==============================================================================

from .constraints import (
    Constraint,
    ConstraintError,
    ConstraintManager,
    ConstraintNotFoundError,
    ConstraintReport,
)

# ==============================================================================
# Success
# ==============================================================================

from .success import (
    SuccessError,
    SuccessEvaluator,
    SuccessReport,
)

# ==============================================================================
# Public API
# ==============================================================================

__all__ = [
    # Goal
    "GoalError",
    "GoalNotFoundError",
    "InvalidGoalTransitionError",
    "GoalManager",
    "now_iso",
    # Objective
    "ObjectiveError",
    "ObjectiveNotFoundError",
    "Objective",
    "ObjectiveManager",
    # Assumptions
    "AssumptionError",
    "AssumptionNotFoundError",
    "Assumption",
    "AssumptionManager",
    # Constraints
    "ConstraintError",
    "ConstraintNotFoundError",
    "Constraint",
    "ConstraintReport",
    "ConstraintManager",
    # Success
    "SuccessError",
    "SuccessReport",
    "SuccessEvaluator",
]
