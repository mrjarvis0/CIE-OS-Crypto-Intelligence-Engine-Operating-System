"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.feature_flags

Purpose:
    Typed, immutable runtime feature flags for the A01 agent.

Design goals:
    - Runtime toggles without redeploying code
    - Strong typing
    - Safe defaults
    - Immutable objects
    - Environment/mapping loading support
    - No business logic
    - No secret handling

Notes:
    OpenFeature treats feature flags as runtime-evaluated, vendor-agnostic
    codepath controls. This module follows that philosophy in a local,
    dependency-light form suitable for the A01 configuration layer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Mapping


class FeatureFlagName(StrEnum):
    """Standard feature flag names supported by A01."""

    ENABLE_AI_REASONING = "ENABLE_AI_REASONING"
    ENABLE_VECTOR_MEMORY = "ENABLE_VECTOR_MEMORY"
    ENABLE_CONTRACT_SIMULATION = "ENABLE_CONTRACT_SIMULATION"
    ENABLE_EVENT_LISTENING = "ENABLE_EVENT_LISTENING"
    ENABLE_REPLAY_MODE = "ENABLE_REPLAY_MODE"
    ENABLE_EXPERIMENTAL_SKILLS = "ENABLE_EXPERIMENTAL_SKILLS"
    ENABLE_DETAILED_AUDIT_LOGGING = "ENABLE_DETAILED_AUDIT_LOGGING"
    ENABLE_LIVE_CHAIN_SYNC = "ENABLE_LIVE_CHAIN_SYNC"
    ENABLE_WRITE_OPERATIONS = "ENABLE_WRITE_OPERATIONS"  # must stay False


_CUSTOM_FLAG_PREFIX: Final[str] = "A01_FLAG_"

_STANDARD_FLAG_FIELDS: Final[dict[FeatureFlagName, str]] = {
    FeatureFlagName.ENABLE_AI_REASONING: "enable_ai_reasoning",
    FeatureFlagName.ENABLE_VECTOR_MEMORY: "enable_vector_memory",
    FeatureFlagName.ENABLE_CONTRACT_SIMULATION: "enable_contract_simulation",
    FeatureFlagName.ENABLE_EVENT_LISTENING: "enable_event_listening",
    FeatureFlagName.ENABLE_REPLAY_MODE: "enable_replay_mode",
    FeatureFlagName.ENABLE_EXPERIMENTAL_SKILLS: "enable_experimental_skills",
    FeatureFlagName.ENABLE_DETAILED_AUDIT_LOGGING: "enable_detailed_audit_logging",
    FeatureFlagName.ENABLE_LIVE_CHAIN_SYNC: "enable_live_chain_sync",
    FeatureFlagName.ENABLE_WRITE_OPERATIONS: "enable_write_operations",
}

_ENV_NAME_TO_FIELD: Final[dict[str, str]] = {
    flag.value: field_name for flag, field_name in _STANDARD_FLAG_FIELDS.items()
}

_DEFAULT_VALUES: Final[dict[str, bool]] = {
    "enable_ai_reasoning": False,
    "enable_vector_memory": True,
    "enable_contract_simulation": True,
    "enable_event_listening": True,
    "enable_replay_mode": True,
    "enable_experimental_skills": False,
    "enable_detailed_audit_logging": True,
    "enable_live_chain_sync": True,
    "enable_write_operations": False,
}

_TRUE_VALUES: Final[set[str]] = {"1", "true", "yes", "on", "enabled"}
_FALSE_VALUES: Final[set[str]] = {"0", "false", "no", "off", "disabled"}


def _parse_bool(value: Any, *, default: bool = False) -> bool:
    """Parse a boolean from common environment/config formats."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0

    text = str(value).strip().lower()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def _lookup(mapping: Mapping[str, Any], key: str) -> Any | None:
    """Case-tolerant key lookup for env-like mappings."""
    if key in mapping:
        return mapping[key]
    upper = key.upper()
    if upper in mapping:
        return mapping[upper]
    lower = key.lower()
    if lower in mapping:
        return mapping[lower]
    return None


@dataclass(frozen=True, slots=True)
class FeatureFlags:
    """
    Immutable typed feature flags for the A01 agent.

    Standard flags are explicit attributes.
    Additional custom flags may be supplied via the `A01_FLAG_` prefix.
    """

    enable_ai_reasoning: bool = _DEFAULT_VALUES["enable_ai_reasoning"]
    enable_vector_memory: bool = _DEFAULT_VALUES["enable_vector_memory"]
    enable_contract_simulation: bool = _DEFAULT_VALUES["enable_contract_simulation"]
    enable_event_listening: bool = _DEFAULT_VALUES["enable_event_listening"]
    enable_replay_mode: bool = _DEFAULT_VALUES["enable_replay_mode"]
    enable_experimental_skills: bool = _DEFAULT_VALUES["enable_experimental_skills"]
    enable_detailed_audit_logging: bool = _DEFAULT_VALUES["enable_detailed_audit_logging"]
    enable_live_chain_sync: bool = _DEFAULT_VALUES["enable_live_chain_sync"]
    enable_write_operations: bool = _DEFAULT_VALUES["enable_write_operations"]

    custom_flags: Mapping[str, bool] = field(default_factory=dict, repr=False)

    _custom_prefix: ClassVar[str] = _CUSTOM_FLAG_PREFIX

    def __post_init__(self) -> None:
        normalized_custom_flags = {
            str(name).strip().upper(): bool(value)
            for name, value in self.custom_flags.items()
        }
        object.__setattr__(self, "custom_flags", MappingProxyType(normalized_custom_flags))

        if self.enable_write_operations:
            raise ValueError(
                "ENABLE_WRITE_OPERATIONS must remain disabled for the read-only A01 agent."
            )

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "FeatureFlags":
        """Build feature flags from an env-like mapping."""
        standard_kwargs: dict[str, bool] = {}

        for flag_name, field_name in _STANDARD_FLAG_FIELDS.items():
            raw_value = _lookup(values, flag_name.value)
            standard_kwargs[field_name] = _parse_bool(
                raw_value,
                default=_DEFAULT_VALUES[field_name],
            )

        custom_flags: dict[str, bool] = {}
        for raw_key, raw_value in values.items():
            key = str(raw_key).strip()
            key_upper = key.upper()

            if not key_upper.startswith(cls._custom_prefix):
                continue

            custom_name = key_upper.removeprefix(cls._custom_prefix).strip()
            if not custom_name:
                continue

            custom_flags[custom_name] = _parse_bool(raw_value, default=False)

        return cls(custom_flags=custom_flags, **standard_kwargs)

    @classmethod
    def from_env(cls, env: Mapping[str, Any] | None = None) -> "FeatureFlags":
        """Load feature flags from os.environ or a provided mapping."""
        return cls.from_mapping(env or os.environ)

    def is_enabled(self, flag: FeatureFlagName | str, default: bool = False) -> bool:
        """Check whether a flag is enabled."""
        if isinstance(flag, FeatureFlagName):
            field_name = _STANDARD_FLAG_FIELDS[flag]
            return bool(getattr(self, field_name))

        key = str(flag).strip().upper()
        if key.startswith(self._custom_prefix):
            key = key.removeprefix(self._custom_prefix).strip()

        if key in self.custom_flags:
            return bool(self.custom_flags[key])

        field_name = _ENV_NAME_TO_FIELD.get(key)
        if field_name is not None:
            return bool(getattr(self, field_name))

        return default

    def as_dict(self) -> dict[str, bool]:
        """Return all flags as a plain dictionary with env-style keys."""
        result: dict[str, bool] = {
            flag_name.value: bool(getattr(self, field_name))
            for flag_name, field_name in _STANDARD_FLAG_FIELDS.items()
        }

        for custom_name, value in self.custom_flags.items():
            result[f"{self._custom_prefix}{custom_name}"] = bool(value)

        return result

    def with_overrides(self, **overrides: Any) -> "FeatureFlags":
        """
        Return a new instance with selected overrides applied.
        """
        current = self.as_dict()

        for key, value in overrides.items():
            normalized_key = str(key).strip().upper()
            if normalized_key in _ENV_NAME_TO_FIELD:
                current[normalized_key] = _parse_bool(value, default=False)
            else:
                current[f"{self._custom_prefix}{normalized_key}"] = _parse_bool(value, default=False)

        return FeatureFlags.from_mapping(current)


DEFAULT_FEATURE_FLAGS: Final[FeatureFlags] = FeatureFlags()

__all__ = [
    "FeatureFlagName",
    "FeatureFlags",
    "DEFAULT_FEATURE_FLAGS",
]
