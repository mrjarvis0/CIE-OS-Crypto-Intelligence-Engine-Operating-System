"""
CIE-OS
A02 News Intelligence Agent

Module:
    config.paths

Purpose:
    Central filesystem path registry.

Design goals:
    - Uses pathlib only
    - Cross-platform
    - No business logic
    - Safe to import everywhere
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

# ==============================================================================
# ROOTS
# ==============================================================================

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
AGENT_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

# ==============================================================================
# AGENT DIRECTORIES
# ==============================================================================

CONFIG_DIR: Final[Path] = AGENT_ROOT / "config"
CORE_DIR: Final[Path] = AGENT_ROOT / "core"
INTELLIGENCE_DIR: Final[Path] = AGENT_ROOT / "intelligence"
MODELS_DIR: Final[Path] = AGENT_ROOT / "models"
CLI_DIR: Final[Path] = AGENT_ROOT / "cli"
TESTS_DIR: Final[Path] = AGENT_ROOT / "tests"

# ==============================================================================
# DATA DIRECTORIES
# ==============================================================================

DATA_DIR: Final[Path] = AGENT_ROOT / "data"
RAW_DATA_DIR: Final[Path] = DATA_DIR / "raw"
PROCESSED_DATA_DIR: Final[Path] = DATA_DIR / "processed"
OUTCOMES_DIR: Final[Path] = DATA_DIR / "outcomes"

DATABASE_FILE: Final[Path] = PROCESSED_DATA_DIR / "a02.db"

# ==============================================================================
# ENVIRONMENT FILES
# ==============================================================================

ENV_FILE: Final[Path] = PROJECT_ROOT / ".env"
ENV_EXAMPLE_FILE: Final[Path] = AGENT_ROOT / ".env.example"


def ensure_data_directories() -> None:
    """Create data directories if missing. Safe to call multiple times."""

    for directory in (RAW_DATA_DIR, PROCESSED_DATA_DIR, OUTCOMES_DIR, MODELS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


__all__ = [
    "PROJECT_ROOT",
    "AGENT_ROOT",
    "CONFIG_DIR",
    "CORE_DIR",
    "INTELLIGENCE_DIR",
    "MODELS_DIR",
    "CLI_DIR",
    "TESTS_DIR",
    "DATA_DIR",
    "RAW_DATA_DIR",
    "PROCESSED_DATA_DIR",
    "OUTCOMES_DIR",
    "DATABASE_FILE",
    "ENV_FILE",
    "ENV_EXAMPLE_FILE",
    "ensure_data_directories",
]
