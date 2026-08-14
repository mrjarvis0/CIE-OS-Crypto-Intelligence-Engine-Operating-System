"""
Tools :: Security Layer
=======================

Authentication, authorization, permissions, secrets, encryption, rate
limiting, validation and sandboxing for the Tools subsystem.

Every tool invocation passes a security decision made by these modules
before it reaches an adapter. The layer is stdlib-only and exposes:

* Credential validation -- :mod:`tools.security.auth`
* Right-or-left gates    -- :mod:`tools.security.authorization`
* Permission grants      -- :mod:`tools.security.permissions`
* Credential storage     -- :mod:`tools.security.secrets`
* Symmetric encryption   -- :mod:`tools.security.encryption`
* Rate limiting          -- :mod:`tools.security.rate_limit`
* Input validation       -- :mod:`tools.security.validator`
* Isolation policies     -- :mod:`tools.security.isolation`
* Process sandbox        -- :mod:`tools.security.sandbox`
"""

from __future__ import annotations

from .auth import (
    AuthenticationError,
    Authenticator,
    Principal,
    SecretAuthenticator,
    Token,
    TokenAuthenticator,
    bearer_token_ok,
)
from .authorization import AuthorizationError, Authorizer, Rule, compile_rules, requirement_rule
from .encryption import decrypt_text, derive_key, encrypt_bytes, encrypt_text
from .isolation import IsolationError, IsolationPolicy, SandboxSpec, host_allowed, restrict_path
from .permissions import (
    Permission,
    PermissionChecker,
    PermissionError,
    PermissionMap,
    Role,
    allow_all,
    deny_all,
    grant_match,
)
from .rate_limit import RateLimiter, RateLimitError, RateLimitPolicy
from .sandbox import Sandbox, SandboxError, SandboxResult, run_sandboxed
from .secrets import Secret, SecretsStore, generate_secret
from .validator import (
    ValidationFailure,
    ValidationReport,
    ValidatorError,
    ValidatorRule,
    allowed,
    guard,
    reject_dangerous,
    required_field,
    validate_signature,
)

__all__ = [
    "AuthenticationError",
    "Authenticator",
    "Principal",
    "SecretAuthenticator",
    "Token",
    "TokenAuthenticator",
    "bearer_token_ok",
    "AuthorizationError",
    "Authorizer",
    "compile_rules",
    "requirement_rule",
    "decrypt_text",
    "derive_key",
    "encrypt_bytes",
    "encrypt_text",
    "IsolationError",
    "IsolationPolicy",
    "SandboxSpec",
    "host_allowed",
    "restrict_path",
    "Permission",
    "PermissionChecker",
    "PermissionError",
    "PermissionMap",
    "Role",
    "allow_all",
    "deny_all",
    "grant_match",
    "RateLimiter",
    "RateLimitError",
    "RateLimitPolicy",
    "Sandbox",
    "SandboxError",
    "SandboxResult",
    "run_sandboxed",
    "Secret",
    "SecretsStore",
    "generate_secret",
    "ValidationFailure",
    "ValidationReport",
    "ValidatorError",
    "ValidatorRule",
    "allowed",
    "guard",
    "reject_dangerous",
    "required_field",
    "validate_signature",
]