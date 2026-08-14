"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    planning.reasoning

Purpose:
    Reasoning subsystem for the planning stack.

Provides critique, evaluation, reflection, validation, verification,
retry decisioning, and plan revision.
"""

from __future__ import annotations

# ==============================================================================
# Critic
# ==============================================================================

from .critic import (
    Critique,
    CritiqueReport,
    Critic,
    Severity,
)

# ==============================================================================
# Evaluator
# ==============================================================================

from .evaluator import (
    CriterionCheck,
    EvaluationResult,
    Evaluator,
)

# ==============================================================================
# Reflection
# ==============================================================================

from .reflection import (
    Reflection,
    Reflector,
)

# ==============================================================================
# Replanner
# ==============================================================================

from .replanner import (
    ReplanResult,
    Replanner,
    Revision,
)

# ==============================================================================
# Retry
# ==============================================================================

from .retry import (
    RetryAnalyzer,
    RetryDecision,
    RetryError,
)

# ==============================================================================
# Validator
# ==============================================================================

from .validator import (
    PlanValidator,
    ValidationIssue,
    ValidationReport,
)

# ==============================================================================
# Verifier
# ==============================================================================

from .verifier import (
    VerificationResult,
    Verifier,
)

# ==============================================================================
# Public API
# ==============================================================================

__all__ = [
    # Critic
    "Severity",
    "Critique",
    "CritiqueReport",
    "Critic",
    # Evaluator
    "CriterionCheck",
    "EvaluationResult",
    "Evaluator",
    # Reflection
    "Reflection",
    "Reflector",
    # Replanner
    "Revision",
    "ReplanResult",
    "Replanner",
    # Retry
    "RetryError",
    "RetryDecision",
    "RetryAnalyzer",
    # Validator
    "ValidationIssue",
    "ValidationReport",
    "PlanValidator",
    # Verifier
    "VerificationResult",
    "Verifier",
]
