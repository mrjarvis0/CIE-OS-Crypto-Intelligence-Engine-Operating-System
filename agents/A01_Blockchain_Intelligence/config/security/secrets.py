"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.security.secrets

Purpose:
    Secret loading, redaction, and safe access helpers for the A01 agent.

Design goals:
    - Secrets must not be logged or printed accidentally
    - Support environment variables and secret files
    - Avoid hardcoded credentials
    - Keep the module import-safe
    - Provide typed, explicit access to sensitive values

Notes:
    Pydantic Settings supports loading values from environment variables or
    secrets files, and Pydantic secret types are designed to avoid exposing
    sensitive values in logs or tracebacks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hmac import compare_digest
import os
from pathlib import Path, PurePath
from typing import Any, Final, Mapping


DEFAULT_SECRETS_DIR_NAME: Final[str] = "secrets"
DEFAULT_ENV_PREFIX: Final[str] = "A01_SECRET_"
REDACTED_VALUE: Final[str] = "**********"


class SecretValue:
    """
    Redacted, immutable wrapper around a sensitive value.

    Deliberately **not** a dataclass. ``dataclasses.asdict()`` walks
    ``__dataclass_fields__`` and calls ``getattr`` directly, so it returns the
    secret in plaintext and bypasses ``__repr__``/``__str__`` redaction
    entirely. Any code that serialized a config object containing one of these
    would write the secret into a log line, an evidence record, or a report.

    Every implicit escape route is therefore closed: no dataclass fields for
    ``asdict`` to walk, and pickle/copy are refused. The value leaves only via
    an explicit :meth:`get_secret_value` call at the point of use, which is
    greppable in review.
    """

    __slots__ = ("name", "source", "_value")

    def __init__(
        self,
        *,
        name: str,
        _value: str,
        source: str = "unknown",
    ) -> None:
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "_value", _value)
        object.__setattr__(self, "source", source)

    # -- retrieval ------------------------------------------------------

    def get_secret_value(self) -> str:
        """Return the plaintext secret. The only path that exposes it."""
        return self._value

    def to_dict(self) -> dict[str, str]:
        """Redacted mapping, safe for logs, evidence records, and reports."""
        return {
            "name": self.name,
            "value": REDACTED_VALUE,
            "source": self.source,
        }

    # -- immutability ---------------------------------------------------

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("SecretValue is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("SecretValue is immutable")

    # -- redacted rendering ---------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        return f"SecretValue(name={self.name!r}, value={REDACTED_VALUE!r}, source={self.source!r})"

    def __str__(self) -> str:  # pragma: no cover
        return REDACTED_VALUE

    # -- comparison ------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SecretValue):
            return NotImplemented
        # compare_digest keeps the secret comparison constant-time.
        return (
            self.name == other.name
            and self.source == other.source
            and compare_digest(self._value, other._value)
        )

    def __hash__(self) -> int:
        # Deliberately excludes the secret so hashing never depends on it.
        return hash((self.name, self.source))

    # -- serialization guards ---------------------------------------------

    def __reduce__(self) -> tuple[Any, ...]:
        raise TypeError(
            "SecretValue cannot be pickled or copied; "
            "call get_secret_value() explicitly at the point of use."
        )

    def __getstate__(self) -> None:
        raise TypeError(
            "SecretValue cannot be serialized; "
            "call get_secret_value() explicitly at the point of use."
        )


@dataclass(frozen=True, slots=True)
class SecretsConfig:
    """
    Configuration for secret resolution.

    Precedence:
        1. Explicit mapping overrides
        2. Environment variables
        3. Secret files directory
    """

    secrets_dir: Path | None = None
    env_prefix: str = DEFAULT_ENV_PREFIX
    strict: bool = False
    encoding: str = "utf-8"

    def __post_init__(self) -> None:
        if not self.env_prefix:
            raise ValueError("env_prefix cannot be empty")
        if self.encoding.strip() == "":
            raise ValueError("encoding cannot be empty")


class SecretsManager:
    """
    Resolve secrets from environment variables and/or secret files.
    """

    def __init__(
        self,
        config: SecretsConfig | None = None,
        *,
        overrides: Mapping[str, str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._config = config or SecretsConfig()
        self._overrides = dict(overrides or {})
        self._env = env or os.environ

    @property
    def config(self) -> SecretsConfig:
        return self._config

    def _normalize_name(self, name: str) -> str:
        clean = name.strip()
        if not clean:
            raise ValueError("secret name cannot be empty")
        return clean

    def _env_name(self, name: str) -> str:
        return f"{self._config.env_prefix}{self._normalize_name(name)}".upper()

    @staticmethod
    def _is_single_path_segment(name: str) -> bool:
        """
        True when ``name`` can only ever address a direct child of a directory.

        A secret name arrives from a caller, and callers pass names built from
        config files, CLI arguments and provider identifiers. Any of those can
        carry a separator. ``Path(secrets_dir) / name`` places no constraint of
        its own: ``"../../.env"`` walks out of the directory, and an absolute
        name discards ``secrets_dir`` entirely.

        Both separators are checked on every platform. A POSIX host treats
        ``"a\b"`` as one filename, so rejecting it there costs nothing, while
        accepting it on a host that later runs Windows would be a traversal.
        """
        if not name or name in {".", ".."}:
            return False
        if "/" in name or "\\" in name:
            return False
        # A NUL truncates the name at the OS layer, so a guard that ran
        # before it would be inspecting a different filename than the one
        # opened.
        if chr(0) in name:
            return False
        # Drive letters and UNC roots: ``C:secret`` is relative to the drive's
        # own cwd, which is not this directory.
        if PurePath(name).is_absolute() or PurePath(name).drive:
            return False
        return True

    def _file_path(self, name: str) -> Path | None:
        """
        Path of the file backing ``name``, or None when it cannot be one.

        Returns None rather than raising for a name that is not a single path
        segment: file resolution is one of three sources, and a name that
        cannot be a filename simply has no file to read. It may still resolve
        from the environment or an override.
        """
        if self._config.secrets_dir is None:
            return None

        normalized = self._normalize_name(name)
        if not self._is_single_path_segment(normalized):
            return None

        root = self._config.secrets_dir
        candidate = root / normalized

        # Belt and braces: a symlink inside the directory can still point out
        # of it, and the segment check above cannot see that.
        try:
            resolved_root = root.resolve()
            if not candidate.resolve().is_relative_to(resolved_root):
                return None
        except OSError:
            return None

        return candidate

    def _read_secret_file(self, path: Path) -> str | None:
        try:
            if not path.exists() or not path.is_file():
                return None
            data = path.read_text(encoding=self._config.encoding).strip()
            return data or None
        except OSError:
            if self._config.strict:
                raise
            return None

    def _read_env_value(self, env_name: str) -> str | None:
        value = self._env.get(env_name)
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    def resolve(self, name: str, *, default: str | None = None) -> SecretValue:
        """
        Resolve a secret by name.
        """
        normalized = self._normalize_name(name)
        env_name = self._env_name(normalized)

        if normalized in self._overrides:
            value = self._overrides[normalized]
            return SecretValue(name=normalized, _value=value, source="override")

        env_value = self._read_env_value(env_name)
        if env_value is not None:
            return SecretValue(name=normalized, _value=env_value, source=f"env:{env_name}")

        file_path = self._file_path(normalized)
        if file_path is not None:
            file_value = self._read_secret_file(file_path)
            if file_value is not None:
                return SecretValue(name=normalized, _value=file_value, source=f"file:{file_path}")

        if default is not None:
            return SecretValue(name=normalized, _value=default, source="default")

        if self._config.strict:
            raise KeyError(f"Secret not found: {normalized!r}")

        return SecretValue(name=normalized, _value="", source="missing")

    def exists(self, name: str) -> bool:
        try:
            return self.resolve(name).get_secret_value() != ""
        except KeyError:
            return False

    def get(self, name: str, *, default: str | None = None) -> str:
        secret = self.resolve(name, default=default)
        value = secret.get_secret_value()
        if value == "" and default is None and not self._config.strict:
            raise KeyError(f"Secret not found: {name!r}")
        return value

    def get_redacted(self, name: str, *, default: str | None = None) -> SecretValue:
        return self.resolve(name, default=default)

    def all_env_secrets(self) -> dict[str, SecretValue]:
        prefix = self._config.env_prefix.upper()
        output: dict[str, SecretValue] = {}

        for key, value in self._env.items():
            key_upper = str(key).upper()
            if not key_upper.startswith(prefix):
                continue
            name = key_upper.removeprefix(prefix)
            output[name] = SecretValue(name=name, _value=str(value), source=f"env:{key_upper}")

        return output

    def load_many(self, names: list[str]) -> dict[str, SecretValue]:
        return {name: self.resolve(name) for name in names}

    def as_plain_mapping(self, names: list[str]) -> dict[str, str]:
        return {name: self.get(name) for name in names}


_default_manager: SecretsManager | None = None


def get_default_manager() -> SecretsManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = SecretsManager()
    return _default_manager


def set_default_manager(manager: SecretsManager) -> None:
    global _default_manager
    _default_manager = manager


def get_secret(name: str, *, default: str | None = None) -> str:
    return get_default_manager().get(name, default=default)


def get_secret_value(name: str, *, default: str | None = None) -> SecretValue:
    return get_default_manager().get_redacted(name, default=default)


def load_secrets(names: list[str]) -> dict[str, SecretValue]:
    return get_default_manager().load_many(names)


def has_secret(name: str) -> bool:
    return get_default_manager().exists(name)


def create_file_backed_manager(
    secrets_dir: Path,
    *,
    env_prefix: str = DEFAULT_ENV_PREFIX,
    strict: bool = False,
) -> SecretsManager:
    return SecretsManager(
        SecretsConfig(secrets_dir=secrets_dir, env_prefix=env_prefix, strict=strict)
    )


__all__ = [
    "DEFAULT_SECRETS_DIR_NAME",
    "DEFAULT_ENV_PREFIX",
    "REDACTED_VALUE",
    "SecretValue",
    "SecretsConfig",
    "SecretsManager",
    "get_default_manager",
    "set_default_manager",
    "get_secret",
    "get_secret_value",
    "load_secrets",
    "has_secret",
    "create_file_backed_manager",
]
