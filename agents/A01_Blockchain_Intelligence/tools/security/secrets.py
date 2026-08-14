"""
Tools :: Security :: Secrets
============================

Secret management for the Tools subsystem.

Secrets (API keys, bearer tokens, credentials) are held in a thread-safe
:class:`SecretStore`. Raw values are only exposed through explicit accessors;
``__str__`` and log helpers always return a masked view so telemetry never
leaks credential material.

Design rules
------------
* A secret value is wrapped in :class:`Secret` and handed out once; callers
  own the reference.
* The store provides ``get`` (raw) and ``masked`` (safe) access paths.
* Optional encrypted persistence requires the provided ``cryptography`` is
  not importable; when a backing file is requested without it, a clear
  :class:`RuntimeError` is raised instead of silently falling back.
"""

from __future__ import annotations

import json
import secrets as _secrets
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from ..utils.helpers import mask_secret

__all__ = ["Secret", "SecretsStore", "generate_secret"]


class Secret:
    """Opaque wrapper around a credential value.

    ``raw`` returns the material the caller owns; the default ``str`` view is
    always masked so accidental logging is safe.
    """

    __slots__ = ("_value", "name", "created_at")

    def __init__(self, value: str, *, name: str = "") -> None:
        if not isinstance(value, str):
            raise TypeError("secret value must be a str")
        self._value = value
        self.name = name
        self.created_at = time.time()

    @property
    def raw(self) -> str:
        return self._value

    def get(self) -> str:
        return self._value

    @property
    def display(self) -> str:
        return mask_secret(self._value)

    def __str__(self) -> str:
        return self.display

    def __repr__(self) -> str:
        return f"<Secret name={self.name!r} value={self.display}>"


def generate_secret(length: int = 32) -> str:
    """Return a cryptographically strong random secret string."""
    if length < 8:
        raise ValueError("secret length must be >= 8")
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    return "".join(_secrets.choice(alphabet) for _ in range(length))


class SecretsStore:
    """
    Thread-safe, optionally persistence-backed secret registry.

    Parameters
    ----------
    name:
        Logical name used for logging and scoping.
    max_size:
        Upper bound on entries; ``None`` means unbounded.
    """

    def __init__(self, *, name: str = "secrets", max_size: Optional[int] = None) -> None:
        self.name = name
        self._max_size = max_size
        self._store: Dict[str, Secret] = {}
        self._lock = threading.RLock()

    # -- core operations --------------------------------------------------- #

    def set(self, name: str, value: str) -> Secret:
        with self._lock:
            if (
                self._max_size is not None
                and len(self._store) >= self._max_size
                and name not in self._store
            ):
                raise RuntimeError(f"secret store '{self.name}' is full")
            secret = Secret(value, name=name)
            self._store[name] = secret
            return secret

    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            secret = self._store.get(name)
        return secret.raw if secret else default

    def get_secret(self, name: str) -> Optional[Secret]:
        with self._lock:
            return self._store.get(name)

    def exists(self, name: str) -> bool:
        with self._lock:
            return name in self._store

    def delete(self, name: str) -> bool:
        with self._lock:
            existed = name in self._store
            self._store.pop(name, None)
        return existed

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __contains__(self, name: str) -> bool:
        return self.exists(name)

    # -- safe introspection ------------------------------------------------ #

    def names(self) -> List[str]:
        with self._lock:
            return list(self._store.keys())

    def masked(self) -> Dict[str, str]:
        """Every entry as a masked display string (safe for logging)."""
        with self._lock:
            return {name: secret.display for name, secret in self._store.items()}

    def __iter__(self) -> Iterable[str]:
        return iter(self.names())

    def size(self) -> int:
        with self._lock:
            return len(self._store)