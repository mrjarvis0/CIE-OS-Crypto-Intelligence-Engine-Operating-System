"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    config.security

Purpose:
    Security-related configuration utilities for the A01 agent.

This package exposes:
    - Secrets management
    - API key management
    - Validation helpers

Python uses __init__.py to mark a directory as a regular package, and the file
may also define package-level exports via __all__.
"""

from __future__ import annotations

from .api_keys import (
    DEFAULT_API_KEY_PREFIX,
    ApiKeyManager,
    ApiKeyRegistry,
    ApiKeySpec,
    ApiKeyType,
    ApiKeyValue,
    DEFAULT_API_KEYS,
    get_api_key,
    get_api_key_header,
    get_api_key_value,
    register_default_api_keys,
    set_default_manager as set_default_api_key_manager,
)
from .secrets import (
    DEFAULT_ENV_PREFIX,
    DEFAULT_SECRETS_DIR_NAME,
    REDACTED_VALUE,
    SecretValue,
    SecretsConfig,
    SecretsManager,
    create_file_backed_manager,
    get_default_manager as get_default_secrets_manager,
    get_secret,
    get_secret_value,
    has_secret,
    load_secrets,
    set_default_manager as set_default_secrets_manager,
)
from .validation import (
    ValidationError,
    ValidationIssue,
    ValidationReport,
    ensure,
    validate_boolean,
    validate_choice,
    validate_directory,
    validate_env_name,
    validate_env_prefix,
    validate_file,
    validate_host,
    validate_non_empty_collection,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_percentage,
    validate_path_exists,
    validate_port,
    validate_positive_float,
    validate_positive_int,
    validate_rpcs,
    validate_secret_name,
    validate_secret_names,
    validate_unique_strings,
    validate_url,
)

__all__ = [
    "DEFAULT_API_KEY_PREFIX",
    "ApiKeyManager",
    "ApiKeyRegistry",
    "ApiKeySpec",
    "ApiKeyType",
    "ApiKeyValue",
    "DEFAULT_API_KEYS",
    "get_api_key",
    "get_api_key_header",
    "get_api_key_value",
    "register_default_api_keys",
    "set_default_api_key_manager",
    "DEFAULT_ENV_PREFIX",
    "DEFAULT_SECRETS_DIR_NAME",
    "REDACTED_VALUE",
    "SecretValue",
    "SecretsConfig",
    "SecretsManager",
    "create_file_backed_manager",
    "get_default_secrets_manager",
    "get_secret",
    "get_secret_value",
    "has_secret",
    "load_secrets",
    "set_default_secrets_manager",
    "ValidationError",
    "ValidationIssue",
    "ValidationReport",
    "ensure",
    "validate_boolean",
    "validate_choice",
    "validate_directory",
    "validate_env_name",
    "validate_env_prefix",
    "validate_file",
    "validate_host",
    "validate_non_empty_collection",
    "validate_non_empty_string",
    "validate_non_negative_int",
    "validate_percentage",
    "validate_path_exists",
    "validate_port",
    "validate_positive_float",
    "validate_positive_int",
    "validate_rpcs",
    "validate_secret_name",
    "validate_secret_names",
    "validate_unique_strings",
    "validate_url",
]
