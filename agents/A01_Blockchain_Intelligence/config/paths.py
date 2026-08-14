"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.paths

Purpose:
    Central filesystem path registry for the entire agent.

Design Rules:
    - Uses pathlib only
    - Cross-platform
    - No business logic
    - No blockchain logic
    - No settings loading
    - Safe to import everywhere
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

# ==============================================================================
# PROJECT ROOTS
# ==============================================================================

# .../CIE-OS/
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

# .../agents/A01-Blockchain-Intelligence/
AGENT_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

# ==============================================================================
# AGENT DIRECTORIES
# ==============================================================================

CONFIG_DIR: Final[Path] = AGENT_ROOT / "config"
CORE_DIR: Final[Path] = AGENT_ROOT / "core"
MEMORY_DIR: Final[Path] = AGENT_ROOT / "memory"
STATE_MANAGER_DIR: Final[Path] = AGENT_ROOT / "state_manager"
CONTRACTS_DIR: Final[Path] = AGENT_ROOT / "contracts"
SCHEMAS_DIR: Final[Path] = AGENT_ROOT / "schemas"
DOCS_DIR: Final[Path] = AGENT_ROOT / "docs"
TESTS_DIR: Final[Path] = AGENT_ROOT / "tests"

# ==============================================================================
# DATA DIRECTORIES
# ==============================================================================

DATA_DIR: Final[Path] = AGENT_ROOT / "data"

CACHE_DIR: Final[Path] = DATA_DIR / "cache"

DATABASE_DIR: Final[Path] = DATA_DIR / "database"

VECTOR_DB_DIR: Final[Path] = DATA_DIR / "vector"

CHECKPOINT_DIR: Final[Path] = DATA_DIR / "checkpoints"

SNAPSHOT_DIR: Final[Path] = DATA_DIR / "snapshots"

EXPORT_DIR: Final[Path] = DATA_DIR / "exports"

IMPORT_DIR: Final[Path] = DATA_DIR / "imports"

# ==============================================================================
# RUNTIME DIRECTORIES
# ==============================================================================

RUNTIME_DIR: Final[Path] = AGENT_ROOT / "runtime"

LOGS_DIR: Final[Path] = RUNTIME_DIR / "logs"

TEMP_DIR: Final[Path] = RUNTIME_DIR / "temp"

PID_DIR: Final[Path] = RUNTIME_DIR / "pid"

SOCKET_DIR: Final[Path] = RUNTIME_DIR / "socket"

# ==============================================================================
# KNOWLEDGE
# ==============================================================================

KNOWLEDGE_DIR: Final[Path] = AGENT_ROOT / "knowledge"

PROMPTS_DIR: Final[Path] = KNOWLEDGE_DIR / "prompts"

TEMPLATES_DIR: Final[Path] = KNOWLEDGE_DIR / "templates"

# ==============================================================================
# BLOCKCHAIN
# ==============================================================================

CHAINS_DIR: Final[Path] = CONFIG_DIR / "rpc"

ABI_DIR: Final[Path] = CONTRACTS_DIR / "abi"

TOKEN_LISTS_DIR: Final[Path] = DATA_DIR / "token_lists"

# ==============================================================================
# ENVIRONMENT FILES
# ==============================================================================

ENV_FILE: Final[Path] = PROJECT_ROOT / ".env"

DEV_ENV_FILE: Final[Path] = PROJECT_ROOT / ".env.development"

TEST_ENV_FILE: Final[Path] = PROJECT_ROOT / ".env.testing"

STAGING_ENV_FILE: Final[Path] = PROJECT_ROOT / ".env.staging"

PRODUCTION_ENV_FILE: Final[Path] = PROJECT_ROOT / ".env.production"

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def ensure_runtime_directories() -> None:
    """
    Create runtime directories if missing.

    Safe to call multiple times.
    """

    directories = (
        CACHE_DIR,
        DATABASE_DIR,
        VECTOR_DB_DIR,
        CHECKPOINT_DIR,
        SNAPSHOT_DIR,
        EXPORT_DIR,
        IMPORT_DIR,
        LOGS_DIR,
        TEMP_DIR,
        PID_DIR,
        SOCKET_DIR,
    )

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


def validate_project_root() -> bool:
    """
    Verify project root exists.
    """
    return PROJECT_ROOT.exists()


def validate_agent_root() -> bool:
    """
    Verify agent root exists.
    """
    return AGENT_ROOT.exists()


def get_chain_directory(chain_name: str) -> Path:
    """
    Return blockchain-specific directory.

    Example:
        data/chains/ethereum
    """
    return DATA_DIR / "chains" / chain_name.lower()


def get_contract_directory(protocol: str) -> Path:
    """
    Return protocol contract directory.
    """
    return ABI_DIR / protocol.lower()


def get_log_file(filename: str) -> Path:
    """
    Return log file path.
    """
    return LOGS_DIR / filename


def get_checkpoint_file(name: str) -> Path:
    """
    Return checkpoint file.
    """
    return CHECKPOINT_DIR / f"{name}.json"


__all__ = [
    "PROJECT_ROOT",
    "AGENT_ROOT",
    "CONFIG_DIR",
    "CORE_DIR",
    "MEMORY_DIR",
    "STATE_MANAGER_DIR",
    "CONTRACTS_DIR",
    "SCHEMAS_DIR",
    "DOCS_DIR",
    "DATA_DIR",
    "CACHE_DIR",
    "DATABASE_DIR",
    "VECTOR_DB_DIR",
    "CHECKPOINT_DIR",
    "SNAPSHOT_DIR",
    "EXPORT_DIR",
    "IMPORT_DIR",
    "RUNTIME_DIR",
    "LOGS_DIR",
    "TEMP_DIR",
    "PID_DIR",
    "SOCKET_DIR",
    "ENV_FILE",
    "DEV_ENV_FILE",
    "TEST_ENV_FILE",
    "STAGING_ENV_FILE",
    "PRODUCTION_ENV_FILE",
    "ensure_runtime_directories",
    "validate_project_root",
    "validate_agent_root",
    "get_chain_directory",
    "get_contract_directory",
    "get_log_file",
    "get_checkpoint_file",
]