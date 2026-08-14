"""
Tools :: Utils :: Configuration
===============================

Stdlib-only configuration loading and merging for the Tools subsystem.

Configuration sources are layered in order of increasing precedence:

1. built-in defaults       (``defaults`` dict)
2. TOML/JSON file          (``file`` path)
3. environment variables   (``env_prefix`` overrides)
4. explicit overrides      (``overrides`` dict)

Later sources win.  Values read from the environment are automatically
coerced to ``bool``/``int``/``float``/JSON when the string matches, which
keeps wiring small packages and adapters consistent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

try:  # pragma: no cover - environment dependent
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

__all__ = [
    "Config",
    "load_config",
    "read_json_file",
    "read_toml_file",
    "flatten_env",
]


class Config:
    """
    Immutable-style dotted access to a merged configuration mapping.

    ``get("a.b.c")`` navigates nested dictionaries; ``from_`` is used for
    type coercion when the value was produced by environment coercion.
    """

    def __init__(self, data: Mapping[str, Any]) -> None:
        self._data: Dict[str, Any] = dict(data)

    def raw(self) -> Dict[str, Any]:
        return dict(self._data)

    def get(
        self,
        key: str,
        default: Any = None,
        *,
        _value: Any = None,
    ) -> Any:
        """Dotted lookup returning ``default`` when missing."""
        cursor: Any = _value if _value is not None else self._data
        for part in key.split("."):
            if not isinstance(cursor, dict) or part not in cursor:
                return default
            cursor = cursor[part]
        return cursor

    def get_str(self, key: str, default: str = "") -> str:
        value = self.get(key, default)
        return default if value is None else str(value)

    def get_int(self, key: str, default: int = 0) -> int:
        value = self.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        value = self.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    def merge(self, other: Mapping[str, Any]) -> "Config":
        return Config(_deep_merge(dict(self._data), dict(other)))

    def __contains__(self, key: str) -> bool:
        return self.get(key, None) is not None


def _deep_merge(base: Dict[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def read_json_file(path: Union[str, Path]) -> Dict[str, Any]:
    """Load and return the JSON object stored at ``path``."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_toml_file(path: Union[str, Path]) -> Dict[str, Any]:
    if tomllib is None:  # pragma: no cover
        raise RuntimeError("tomllib is not available on this Python version")
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def _coerce(value: str) -> Any:
    """Coerce a bare environment string into a typed value when it matches one."""
    if value.isdigit():
        return int(value)
    lowered = value.lower()
    if lowered in ("true", "yes", "on", "1"):
        return True
    if lowered in ("false", "no", "off", "0"):
        return False
    return value


def flatten_env(prefix: str, env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """
    Collect ``PREFIX__A__B`` variables into a nested ``{"a": {"b": ...}}`` dict.

    Double underscore is the separator so that single underscores inside names
    are preserved.  Values are coerced with :func:`_coerce`.
    """
    env = env if env is not None else os.environ
    prefix = prefix.upper().rstrip("_")
    result: Dict[str, Any] = {}
    for key, raw in env.items():
        if not key.startswith(prefix + "__"):
            continue
        parts = key[len(prefix) + 2 :].lower().split("__")
        cursor = result
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = _coerce(raw)
    return result


def load_config(
    *,
    defaults: Optional[Mapping[str, Any]] = None,
    file: Optional[Union[str, Path]] = None,
    env_prefix: str = "",
    overrides: Optional[Mapping[str, Any]] = None,
    require_file: bool = False,
) -> Config:
    """
    Assemble a layered :class:`Config`.

    ``defaults`` supply baseline values; ``file`` (JSON or TOML by extension)
    is merged next; ``env_prefix`` pulls ``PREFIX__KEY`` variables; final
    ``overrides`` win.  ``require_file`` raises :class:`FileNotFoundError`.
    """
    base: Dict[str, Any] = dict(defaults or {})
    if file is not None:
        path = Path(file)
        if not path.exists():
            if require_file:
                raise FileNotFoundError(f"config file not found: {file}")
        else:
            if path.suffix.lower() in (".toml", ".tml"):
                base = _deep_merge(base, read_toml_file(path))
            else:
                base = _deep_merge(base, read_json_file(path))
    if env_prefix:
        base = _deep_merge(base, flatten_env(env_prefix))
    if overrides:
        base = _deep_merge(base, overrides)
    return Config(base)