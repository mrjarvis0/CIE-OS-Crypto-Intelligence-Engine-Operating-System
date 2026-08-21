"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the redirect packages.

Eight directories in this tree name a concept that is implemented somewhere
else: `api/`, `monitoring/`, `models/`, `plugins/`, `reasoning/`,
`reporting/`, `security/` and `workflows/`. Each used to be empty with a
generated README explaining where to look, and
`docs/architecture/folder-architecture.md` section 10 says what an empty
directory with a name like that invites -- code written in the wrong place.

Each is now a package that binds the canonical module object itself. The
tests below are what make that claim mean something:

    test_every_redirect_is_the_canonical_module_itself
        `api.rest is interfaces.rest`. Identity, not equality of surface. A
        re-implementation inside the redirect directory breaks this, which is
        the entire point of writing it down.

    test_no_redirect_package_defines_its_own_implementation
        The file-count check. A redirect package holding a second module is
        the failure this design exists to prevent, and it would not
        necessarily break the identity test -- so it gets its own.

`sandbox/` is excluded on purpose and has its own rule in
`tools/tests/test_placement.py`: it stays empty because there is nothing to
redirect it to, and code placed there ships by accident.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent

#: ``(package, attribute, canonical module)`` for every single-target redirect.
REDIRECTS: tuple[tuple[str, str, str], ...] = (
    ("api", "rest", "interfaces.rest"),
    ("monitoring", "metrics", "telemetry.metrics"),
    ("models", "provider", "intelligence.narrative.provider"),
    ("plugins", "plugins", "tools.plugins"),
    ("reasoning", "reasoning", "intelligence.reasoning"),
    ("reporting", "reporting", "intelligence.reporting"),
    ("workflows", "planning", "planning"),
)

#: ``security/`` binds two canonical homes and merges neither.
SECURITY_BINDINGS: tuple[tuple[str, str], ...] = (
    ("configuration", "config.security"),
    ("runtime", "tools.security"),
)

ALL_REDIRECT_PACKAGES = tuple(name for name, _, _ in REDIRECTS) + ("security",)


# ==============================================================================
# IDENTITY
# ==============================================================================

@pytest.mark.parametrize("package,attribute,canonical", REDIRECTS)
def test_every_redirect_is_the_canonical_module_itself(
    package: str, attribute: str, canonical: str
):
    """
    Identity, not a copy of the surface.

    A second implementation written inside the redirect directory fails here,
    which is what turns "do not add code here" from a request into a rule.
    """
    facade = importlib.import_module(package)
    target = importlib.import_module(canonical)

    assert getattr(facade, attribute) is target


@pytest.mark.parametrize("attribute,canonical", SECURITY_BINDINGS)
def test_security_binds_both_homes_without_merging_them(attribute: str, canonical: str):
    import security

    assert getattr(security, attribute) is importlib.import_module(canonical)


def test_security_does_not_merge_two_colliding_secret_wrappers():
    """
    `config.security.SecretValue` refuses pickling, copying and
    `dataclasses.asdict`; `tools.security.Secret` is a lighter holder. A
    merged namespace would let a caller reach for `security.Secret` with no
    reason to suspect there was a choice.
    """
    import security

    with pytest.raises(AttributeError):
        security.Secret

    with pytest.raises(AttributeError):
        security.SecretValue

    assert hasattr(security.runtime, "Secret")
    assert hasattr(security.configuration, "SecretValue")


# ==============================================================================
# FORWARDING
# ==============================================================================

@pytest.mark.parametrize("package,attribute,canonical", REDIRECTS)
def test_a_public_name_forwards_live(package: str, attribute: str, canonical: str):
    """
    Delegation, not a star-import. The name is read from the canonical module
    at the moment of the call, so this package cannot hold one the canonical
    module has since dropped.
    """
    facade = importlib.import_module(package)
    target = importlib.import_module(canonical)

    public = [name for name in dir(target) if not name.startswith("_")]
    assert public, f"{canonical} exposes nothing to forward"

    for name in public[:5]:
        assert getattr(facade, name) is getattr(target, name)


@pytest.mark.parametrize("package,attribute,canonical", REDIRECTS)
def test_a_missing_name_says_which_package_redirected_and_where(
    package: str, attribute: str, canonical: str
):
    """
    A bare `AttributeError` from a redirect is confusing: the reader looks in
    a directory holding one file. The message has to name the real home.
    """
    facade = importlib.import_module(package)

    with pytest.raises(AttributeError) as excinfo:
        facade.a_name_that_does_not_exist_anywhere

    message = str(excinfo.value)
    assert package in message
    assert canonical in message


@pytest.mark.parametrize("package,attribute,canonical", REDIRECTS)
def test_dir_lists_what_the_canonical_module_offers(
    package: str, attribute: str, canonical: str
):
    facade = importlib.import_module(package)
    target = importlib.import_module(canonical)

    listed = set(dir(facade))
    assert set(dir(target)) <= listed


# ==============================================================================
# NOTHING IS IMPLEMENTED HERE
# ==============================================================================

@pytest.mark.parametrize("package", ALL_REDIRECT_PACKAGES)
def test_no_redirect_package_defines_its_own_implementation(package: str):
    """
    One file, and it is the redirect.

    This is the check the identity test cannot make. A redirect package could
    keep `api.rest is interfaces.rest` intact while quietly growing an
    `api/handlers.py` beside it, and the second implementation would be
    exactly what this whole arrangement exists to prevent.
    """
    directory = ROOT / package
    modules = sorted(
        path.name
        for path in directory.glob("*.py")
        if path.name != "__init__.py"
    )

    assert modules == [], (
        f"{package}/ holds {modules}; it is a redirect to a canonical module "
        "and must not grow an implementation of its own"
    )


@pytest.mark.parametrize("package", ALL_REDIRECT_PACKAGES)
def test_a_redirect_package_says_where_it_points(package: str):
    """
    The docstring is the thing a reader hits first, and it replaced a
    generated README that used to do this job.
    """
    module = importlib.import_module(package)

    assert module.__doc__
    assert "redirect" in module.__doc__.lower()


@pytest.mark.parametrize("package", ALL_REDIRECT_PACKAGES)
def test_a_redirect_package_declares_what_it_binds(package: str):
    module = importlib.import_module(package)

    assert getattr(module, "__all__", None), f"{package} declares no __all__"
    for name in module.__all__:
        assert hasattr(module, name)


def test_sandbox_is_not_a_redirect_and_stays_empty():
    """
    The one directory where a redirect would be wrong: there is nothing to
    redirect to, and code placed there ships by accident.
    """
    sandbox = ROOT / "sandbox"

    assert sandbox.is_dir()
    assert list(sandbox.glob("*.py")) == []
