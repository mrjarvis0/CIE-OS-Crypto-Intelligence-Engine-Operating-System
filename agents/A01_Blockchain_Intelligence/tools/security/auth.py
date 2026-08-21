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
from ..utils.helpers import now_utc

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
        """
        True once ``expires_at`` has passed.

        ``now_utc`` is imported at module scope. It used to be a deferred
        ``from .utils.helpers import ...`` inside this property, and
        ``tools.security.utils`` does not exist -- so every credential that
        carried an expiry raised ``ModuleNotFoundError`` on the one check that
        was supposed to reject it.
        """
        if self.expires_at is None:
            return False
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
    """
    Validate an opaque bearer token against a static token table.

    ``expiries`` maps a token value to the epoch second it stops being valid.
    Without it, :attr:`Token.expired` had nothing to act on: this table held
    principals only, so an expiring credential was accepted forever.
    """

    def __init__(
        self,
        tokens: Mapping[str, Principal],
        *,
        expiries: Optional[Mapping[str, float]] = None,
    ) -> None:
        self._tokens: Dict[str, Principal] = {}
        for value, principal in tokens.items():
            self._tokens[value] = (
                principal if isinstance(principal, Principal) else Principal(id=str(principal))
            )
        self._expiries: Dict[str, float] = dict(expiries or {})

    def authenticate(self, credentials: Mapping[str, object]) -> Principal:
        presented = credentials.get("token")
        if not presented:
            raise AuthenticationError("missing token")

        presented = str(presented)

        # Compared against every entry rather than looked up, so the work done
        # is the same whether the token is known or not. A dict lookup returns
        # sooner for an unknown token than for a known one.
        matched: Optional[str] = None
        for value in self._tokens:
            if constant_time_compare(presented, value):
                matched = value

        if matched is None:
            raise AuthenticationError("unknown token")

        expires_at = self._expiries.get(matched)
        if expires_at is not None and Token(value=matched, expires_at=expires_at).expired:
            raise AuthenticationError("expired token")

        return self._tokens[matched]


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