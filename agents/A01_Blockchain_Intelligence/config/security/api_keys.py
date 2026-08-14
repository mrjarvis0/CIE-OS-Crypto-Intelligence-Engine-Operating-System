"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.security.api_keys

Purpose:
    Typed API-key registry and redaction helpers for external providers.

Design goals:
    - Keep API keys out of logs and reprs
    - Resolve keys from the secrets layer
    - Support provider-specific aliases
    - Provide auth header helpers
    - No network I/O
    - No secret persistence
    - Safe to import anywhere
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Mapping

from .secrets import SecretValue, SecretsManager, get_default_manager


DEFAULT_API_KEY_PREFIX: Final[str] = "A01_API_KEY_"


class ApiKeyType(StrEnum):
    """Common API-key styles used by providers."""

    HEADER = "header"
    BEARER = "bearer"
    QUERY = "query"
    BASIC = "basic"


@dataclass(frozen=True, slots=True)
class ApiKeySpec:
    """
    Describe how a provider key should be used.

    name:
        Canonical provider name or key alias.
    secret_name:
        Secret lookup name in the secrets manager.
    key_type:
        How the key should be represented in requests.
    header_name:
        Name of the HTTP header for header-based auth.
    query_param:
        Query param name for query-based auth.
    enabled:
        Whether this key is active.
    """

    name: str
    secret_name: str
    key_type: ApiKeyType = ApiKeyType.HEADER
    header_name: str = "Authorization"
    query_param: str = "api_key"
    enabled: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name cannot be empty")
        if not self.secret_name.strip():
            raise ValueError("secret_name cannot be empty")
        if self.key_type == ApiKeyType.HEADER and not self.header_name.strip():
            raise ValueError("header_name cannot be empty for header auth")
        if self.key_type == ApiKeyType.QUERY and not self.query_param.strip():
            raise ValueError("query_param cannot be empty for query auth")


@dataclass(frozen=True, slots=True)
class ApiKeyValue:
    """Redacted API-key value wrapper."""

    spec: ApiKeySpec
    secret: SecretValue = field(repr=False)

    def get(self) -> str:
        return self.secret.get_secret_value()

    @property
    def source(self) -> str:
        return self.secret.source

    def __repr__(self) -> str:  # pragma: no cover
        return f"ApiKeyValue(name={self.spec.name!r}, value='**********', source={self.source!r})"

    def __str__(self) -> str:  # pragma: no cover
        return "**********"


@dataclass(frozen=True, slots=True)
class ApiKeyRegistry:
    """Immutable registry of API-key specs."""

    specs: tuple[ApiKeySpec, ...] = ()

    def __post_init__(self) -> None:
        normalized: list[ApiKeySpec] = []
        seen: set[str] = set()

        for spec in self.specs:
            canonical = spec.name.strip().upper()
            if canonical in seen:
                raise ValueError(f"duplicate api-key spec: {spec.name!r}")
            seen.add(canonical)
            normalized.append(spec)

        object.__setattr__(self, "specs", tuple(normalized))

    def get(self, name: str) -> ApiKeySpec:
        canonical = name.strip().upper()
        for spec in self.specs:
            if spec.name.strip().upper() == canonical:
                return spec
        raise KeyError(f"api-key spec not found: {name!r}")

    def names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.specs if spec.enabled)

    def enabled(self) -> tuple[ApiKeySpec, ...]:
        return tuple(spec for spec in self.specs if spec.enabled)

    def as_mapping(self) -> dict[str, ApiKeySpec]:
        return {spec.name.strip().upper(): spec for spec in self.specs}


class ApiKeyManager:
    """
    Resolve and transform API keys for providers.

    This class does not fetch credentials from the network. It only resolves
    them through the secrets layer and transforms them into safe request
    materials (headers or query params) for downstream HTTP clients.
    """

    def __init__(
        self,
        registry: ApiKeyRegistry | None = None,
        *,
        secrets_manager: SecretsManager | None = None,
    ) -> None:
        self._registry = registry or ApiKeyRegistry()
        self._secrets_manager = secrets_manager or get_default_manager()

    @property
    def registry(self) -> ApiKeyRegistry:
        return self._registry

    def has(self, name: str) -> bool:
        try:
            self._registry.get(name)
            return True
        except KeyError:
            return False

    def resolve(self, name: str) -> ApiKeyValue:
        spec = self._registry.get(name)
        secret = self._secrets_manager.get_redacted(spec.secret_name)
        return ApiKeyValue(spec=spec, secret=secret)

    def get(self, name: str) -> str:
        return self.resolve(name).get()

    def get_value(self, name: str) -> ApiKeyValue:
        return self.resolve(name)

    def get_header(self, name: str) -> dict[str, str]:
        """
        Return an auth header mapping for the specified key.

        Header conventions:
        - bearer => Authorization: Bearer <token>
        - header => header_name: <token>
        - basic  => Authorization: Basic <token>
        """
        key = self.resolve(name)
        token = key.get()

        if key.spec.key_type == ApiKeyType.BEARER:
            return {key.spec.header_name: f"Bearer {token}"}
        if key.spec.key_type == ApiKeyType.BASIC:
            return {key.spec.header_name: f"Basic {token}"}
        if key.spec.key_type == ApiKeyType.HEADER:
            return {key.spec.header_name: token}

        raise ValueError(f"Query keys do not map to headers: {name!r}")

    def get_query_param(self, name: str) -> dict[str, str]:
        """Return a query parameter mapping for the specified key."""
        key = self.resolve(name)
        if key.spec.key_type != ApiKeyType.QUERY:
            raise ValueError(f"Key is not query-based: {name!r}")
        return {key.spec.query_param: key.get()}

    def get_request_material(self, name: str) -> dict[str, Any]:
        """
        Return a provider-ready request bundle with auth material and metadata.
        """
        key = self.resolve(name)
        if key.spec.key_type == ApiKeyType.QUERY:
            return {
                "provider": key.spec.name,
                "type": key.spec.key_type.value,
                "query": {key.spec.query_param: key.get()},
            }

        return {
            "provider": key.spec.name,
            "type": key.spec.key_type.value,
            "headers": self.get_header(name),
        }

    def as_redacted_mapping(self) -> dict[str, dict[str, Any]]:
        """
        Return a safe, redacted view of all configured keys.
        """
        output: dict[str, dict[str, Any]] = {}
        for spec in self._registry.enabled():
            try:
                value = self.resolve(spec.name)
                output[spec.name] = {
                    "secret_name": spec.secret_name,
                    "type": spec.key_type.value,
                    "enabled": spec.enabled,
                    "source": value.source,
                    "redacted": True,
                }
            except Exception:
                output[spec.name] = {
                    "secret_name": spec.secret_name,
                    "type": spec.key_type.value,
                    "enabled": spec.enabled,
                    "source": "unavailable",
                    "redacted": True,
                }
        return output

    def load_many(self, names: list[str]) -> dict[str, ApiKeyValue]:
        return {name: self.resolve(name) for name in names}


# ------------------------------------------------------------------------------
# Convenience defaults
# ------------------------------------------------------------------------------

DEFAULT_API_KEYS = ApiKeyRegistry(specs=())

_default_manager: ApiKeyManager | None = None


def get_default_manager() -> ApiKeyManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = ApiKeyManager(DEFAULT_API_KEYS)
    return _default_manager


def set_default_manager(manager: ApiKeyManager) -> None:
    global _default_manager
    _default_manager = manager


def register_default_api_keys(specs: list[ApiKeySpec]) -> ApiKeyRegistry:
    """
    Create and install a default registry from a list of specs.
    """
    registry = ApiKeyRegistry(tuple(specs))
    set_default_manager(ApiKeyManager(registry))
    return registry


def get_api_key(name: str) -> str:
    """Convenience helper returning the raw API key value."""
    return get_default_manager().get(name)


def get_api_key_header(name: str) -> dict[str, str]:
    """Convenience helper returning a header mapping."""
    return get_default_manager().get_header(name)


def get_api_key_value(name: str) -> ApiKeyValue:
    """Convenience helper returning a redacted wrapper."""
    return get_default_manager().get_value(name)


__all__ = [
    "DEFAULT_API_KEY_PREFIX",
    "ApiKeyType",
    "ApiKeySpec",
    "ApiKeyValue",
    "ApiKeyRegistry",
    "ApiKeyManager",
    "DEFAULT_API_KEYS",
    "get_default_manager",
    "set_default_manager",
    "register_default_api_keys",
    "get_api_key",
    "get_api_key_header",
    "get_api_key_value",
]
