"""
CIE-OS
A01 Blockchain Intelligence Agent

Regression tests for `config.security`.

Three defects, all reproduced against the shipped code:

    1. `SecretsManager` read files outside `secrets_dir`. A secret name is
       joined onto the directory, and `Path.__truediv__` places no constraint
       of its own, so `resolve("../../pyproject.toml")` returned the contents
       of a file two levels up. On a deployment where names come from
       configuration, that is arbitrary file read through the secrets API.

    2. `validate_secret_name` would not have stopped it either: its pattern
       admitted `/` and `.`, so `A/../../.ENV` was a valid secret name.

    3. `ApiKeyManager()` recursed until the stack ran out. The module imported
       `get_default_manager` from `.secrets` and then defined its own function
       of the same name; the later definition won at call time, so the manager
       resolved its secrets backend to itself.

Plus one correctness bug in an auth path: BASIC keys were sent as a bare
token rather than base64("user:pass"), so every server rejected the header
and the failure surfaced as a provider auth error.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from config.security.api_keys import (
    ApiKeyManager,
    ApiKeyRegistry,
    ApiKeySpec,
    ApiKeyType,
)
from config.security.secrets import SecretsConfig, SecretsManager
from config.security.validation import ValidationError, validate_secret_name


# ==============================================================================
# THE SECRETS DIRECTORY IS A BOUNDARY
# ==============================================================================

@pytest.fixture
def secrets_dir(tmp_path: Path) -> Path:
    """A secrets directory with one real secret, and a file outside it."""
    directory = tmp_path / "secrets"
    directory.mkdir()
    (directory / "ALCHEMY").write_text("real-secret-value", encoding="utf-8")
    (tmp_path / "private.txt").write_text("NOT-A-SECRET-OF-THIS-DIRECTORY", encoding="utf-8")
    return directory


@pytest.mark.parametrize(
    "name",
    [
        "../private.txt",
        "..\\private.txt",
        "../../etc/passwd",
        "subdir/ALCHEMY",
        "..",
        ".",
    ],
)
def test_a_name_that_leaves_the_directory_resolves_to_nothing(
    secrets_dir: Path, name: str
):
    manager = SecretsManager(SecretsConfig(secrets_dir=secrets_dir))
    resolved = manager.resolve(name)

    assert resolved.source == "missing"
    assert resolved.get_secret_value() == ""


def test_an_absolute_name_does_not_discard_the_directory(secrets_dir: Path, tmp_path: Path):
    """`Path(dir) / "/etc/passwd"` is `/etc/passwd`: the root is thrown away."""
    manager = SecretsManager(SecretsConfig(secrets_dir=secrets_dir))
    outside = tmp_path / "private.txt"

    assert manager.resolve(str(outside)).source == "missing"
    assert manager.resolve("/etc/passwd").source == "missing"


def test_a_symlink_out_of_the_directory_is_refused(secrets_dir: Path, tmp_path: Path):
    """
    The segment check cannot see a symlink, so containment is verified again
    after resolution.
    """
    target = tmp_path / "private.txt"
    link = secrets_dir / "ESCAPE"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this host")

    manager = SecretsManager(SecretsConfig(secrets_dir=secrets_dir))
    assert manager.resolve("ESCAPE").source == "missing"


def test_a_legitimate_secret_still_resolves_from_its_file(secrets_dir: Path):
    manager = SecretsManager(SecretsConfig(secrets_dir=secrets_dir))
    resolved = manager.resolve("ALCHEMY")

    assert resolved.get_secret_value() == "real-secret-value"
    assert resolved.source.startswith("file:")


def test_the_environment_still_wins_over_the_file(secrets_dir: Path):
    """Precedence is documented as override, then env, then file."""
    manager = SecretsManager(
        SecretsConfig(secrets_dir=secrets_dir),
        env={"A01_SECRET_ALCHEMY": "from-the-environment"},
    )
    assert manager.resolve("ALCHEMY").get_secret_value() == "from-the-environment"


def test_a_traversal_name_can_still_resolve_from_the_environment(secrets_dir: Path):
    """
    File resolution is one source of three. A name that cannot be a filename
    has no file to read; it is not, by itself, an error.
    """
    manager = SecretsManager(
        SecretsConfig(secrets_dir=secrets_dir),
        overrides={"../odd-name": "supplied-explicitly"},
    )
    assert manager.resolve("../odd-name").get_secret_value() == "supplied-explicitly"


# ==============================================================================
# THE VALIDATOR AGREES WITH THE MANAGER
# ==============================================================================

@pytest.mark.parametrize(
    "name",
    ["A/../../.ENV", "A/B", "../SECRET", "..", "A..B"],
)
def test_the_validator_rejects_names_that_could_address_another_directory(name: str):
    with pytest.raises(ValidationError):
        validate_secret_name(name)


@pytest.mark.parametrize("name", ["ALCHEMY", "A01_ALCHEMY_KEY", "provider.name", "a-b-c"])
def test_the_validator_accepts_ordinary_names(name: str):
    assert validate_secret_name(name) == name.upper()


# ==============================================================================
# API KEYS
# ==============================================================================

def test_a_default_api_key_manager_can_be_constructed():
    """This raised RecursionError: the manager resolved its backend to itself."""
    manager = ApiKeyManager()
    assert isinstance(manager._secrets_manager, SecretsManager)


def test_a_basic_key_is_base64_encoded():
    """RFC 7617: the credential is base64("user:pass"), not the bare token."""
    registry = ApiKeyRegistry(
        (ApiKeySpec(name="provider", secret_name="P", key_type=ApiKeyType.BASIC),)
    )
    manager = ApiKeyManager(
        registry, secrets_manager=SecretsManager(overrides={"P": "user:pass"})
    )

    header = manager.get_header("provider")
    assert header["Authorization"] == "Basic " + base64.b64encode(b"user:pass").decode()


def test_a_bearer_key_keeps_its_prefix():
    registry = ApiKeyRegistry(
        (ApiKeySpec(name="provider", secret_name="P", key_type=ApiKeyType.BEARER),)
    )
    manager = ApiKeyManager(
        registry, secrets_manager=SecretsManager(overrides={"P": "tok"})
    )

    assert manager.get_header("provider") == {"Authorization": "Bearer tok"}


def test_the_redacted_mapping_never_carries_a_key():
    registry = ApiKeyRegistry(
        (ApiKeySpec(name="provider", secret_name="P", key_type=ApiKeyType.HEADER),)
    )
    manager = ApiKeyManager(
        registry, secrets_manager=SecretsManager(overrides={"P": "super-secret-key"})
    )

    rendered = repr(manager.as_redacted_mapping())
    assert "super-secret-key" not in rendered
    assert manager.as_redacted_mapping()["provider"]["redacted"] is True
