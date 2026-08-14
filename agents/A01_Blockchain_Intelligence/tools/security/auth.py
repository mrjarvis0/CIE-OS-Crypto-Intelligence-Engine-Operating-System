"""
Tools :: Security :: Authentication
===================================

Authentication primitives: verify that a presented credential maps to a known
principal.

The module is credential-flash and transport-agnostic:

* :class:`Principal` models a validated identity (human or service).
* :class:`TokenAuthenticator` validates opaque bearer tokens against a table.
* :class:`SecretAuthenticator` validates an API key against a secret store.
* Every failure is a :class:`AuthenticationError` with a stable ``code`` so
  adapters can translate it to ``AdapterAuthenticationError``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, Optional, Tuple

from ..utils.hashing import constant_time_compare

__all__ = [
    "AuthenticationError",
    "Principal",
    "Token",
    "Authenticator",
    "TokenAuthenticator",
    "SecretAuthenticator",
    "bearer_token_ok",
]


class AuthenticationError(Exception):
    """Raised when presented credentials cannot be validated."""

    code = "AUTHENTICATION_ERROR"

    def __init__(self, message: str = "authentication failed") -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Principal:
    """A validated identity that requests tool execution."""

    id: str
    name: str = ""
    roles: Tuple[str, ...] = ()
    attributes: Mapping[str, object] = field(default_factory=dict)

    @property
    def is_human(self) -> bool:
        return self.id.startswith("user:")

    @property
    def is_service(self) -> bool:
        return self.id.startswith("svc:")

    def __str__(self) -> str:
        return self.id


@dataclass(frozen=True)
class Token:
    """A bearer credential plus its metadata."""

    value: str
    principal_id: str = ""
    expires_at: Optional[float] = None

    @property
    def expired(self) -> bool:
        if self.expires_at is None:
            return False
        from .utils.helpers import now_utc

        return now_utc().timestamp() > self.expires_at


class Authenticator:
    """Base contract: ``authenticate(credentials) -> Principal``."""

    def authenticate(self, credentials: Mapping[str, object]) -> Principal:
        raise NotImplementedError

    def validate(self, credentials: Mapping[str, object]) -> Optional["Principal"]:
        try:
            return self.authenticate(credentials)
        except AuthenticationError:
            return None


class TokenAuthenticator(Authenticator):
    """Validate an opaque bearer token against a static token table."""

    def __init__(self, tokens: Mapping[str, Principal]) -> None:
        self._tokens: Dict[str, Principal] = {}
        for value, principal in tokens.items():
            self._tokens[value] = (
                principal if isinstance(principal, Principal) else Principal(id=str(principal))
            )

    def authenticate(self, credentials: Mapping[str, object]) -> Principal:
        token = credentials.get("token")
        if not token:
            raise AuthenticationError("missing token")
        stored = self._tokens.get(str(token))
        if stored is None:
            raise AuthenticationError("unknown token")
        return stored


# recursive import would be required for SecretManager typing; the store is
# duck-typed: only ``get(name) -> Optional[str]`` is consumed.
class SecretAuthenticator(Authenticator):
    """Validate an API key from ``credentials`` against a secret store."""

    def __init__(self, secrets: object, *, key_name: str = "api_key") -> None:
        self._secrets = secrets  # duck-type: .get(key_name) -> str | None
        self.key_name = key_name

    def authenticate(self, credentials: Mapping[str, object]) -> Principal:
        presented = str(credentials.get("api_key") or credentials.get("key") or "")
        if not presented:
            raise AuthenticationError("missing api key")
        expected = self._secrets.get(self.key_name) if hasattr(self._secrets, "get") else None  # type: ignore[attr-defined]
        if not expected or not constant_time_compare(presented, expected):
            raise AuthenticationError("invalid api key")
        return Principal(id="svc:api", name="api-client")


def bearer_token_ok(token: str, valid_tokens: Iterable[str]) -> bool:
    """True when ``token`` matches any value in ``valid_tokens`` (constant-time)."""
    token = str(token)
    return any(constant_time_compare(token, str(valid)) for valid in valid_tokens)