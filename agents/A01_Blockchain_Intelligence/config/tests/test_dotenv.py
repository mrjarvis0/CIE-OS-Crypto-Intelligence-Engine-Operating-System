"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for `.env` loading.

This module exists because of a silent failure: provider credentials are read
from `os.environ`, a `.env` file was only ever read into a pydantic settings
object, and the two never met. A correctly written key file activated nothing,
`configured_providers()` returned empty, and no error appeared anywhere.

The tests that matter are the ones about precedence and disclosure — a
credential loader that can quietly override an exported value, or that logs one,
is worse than not having it.
"""

from __future__ import annotations

import logging

import pytest

from config.dotenv import (
    ENV_FILENAMES,
    DotenvResult,
    candidate_paths,
    describe,
    load,
    parse,
    reset,
)


@pytest.fixture(autouse=True)
def clean_cache():
    """The loader caches per process; each test needs its own first load."""
    reset()
    yield
    reset()


# ==============================================================================
# PARSING
# ==============================================================================

def test_simple_assignments_are_read():
    assert parse("A=1\nB=two\n") == {"A": "1", "B": "two"}


def test_comments_and_blanks_are_ignored():
    assert parse("# note\n\nA=1\n") == {"A": "1"}


def test_export_prefixes_are_tolerated():
    """People paste shell exports into these files."""
    assert parse("export A=1\n") == {"A": "1"}


@pytest.mark.parametrize("line", ['A="quoted"', "A='quoted'"])
def test_quotes_are_stripped(line):
    assert parse(line)["A"] == "quoted"


def test_a_value_containing_equals_survives():
    """Base64 keys and connection URLs routinely contain '='."""
    assert parse("URL=https://x/y?a=b&c=d")["URL"] == "https://x/y?a=b&c=d"


def test_a_line_that_is_not_an_assignment_is_skipped_not_guessed():
    assert parse("this is not a setting\nA=1\n") == {"A": "1"}


def test_a_malformed_name_is_skipped():
    assert parse("not a name=1\nA=1\n") == {"A": "1"}


# ==============================================================================
# PRECEDENCE — the rule that must not invert
# ==============================================================================

def test_an_exported_variable_beats_the_file(tmp_path):
    """
    A stale checked-out `.env` must never defeat a deliberate export, and an
    operator has no way to see which value won if it can.
    """
    (tmp_path / ".env").write_text("KEY=from_file\n", encoding="utf-8")
    environ = {"KEY": "from_export"}

    result = load(tmp_path, environ=environ)

    assert environ["KEY"] == "from_export"
    assert result.skipped == ("KEY",)
    assert result.names == ()


def test_a_variable_absent_from_the_environment_is_applied(tmp_path):
    (tmp_path / ".env").write_text("KEY=from_file\n", encoding="utf-8")
    environ: dict[str, str] = {}

    load(tmp_path, environ=environ)

    assert environ["KEY"] == "from_file"


def test_override_is_available_but_not_the_default(tmp_path):
    (tmp_path / ".env").write_text("KEY=from_file\n", encoding="utf-8")
    environ = {"KEY": "from_export"}

    load(tmp_path, environ=environ, override=True)

    assert environ["KEY"] == "from_file"


# ==============================================================================
# SEARCH
# ==============================================================================

def test_the_local_file_is_preferred(tmp_path):
    """`.env.local` is where a developer's own keys go, and it wins."""
    (tmp_path / ".env").write_text("KEY=shared\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("KEY=personal\n", encoding="utf-8")
    environ: dict[str, str] = {}

    load(tmp_path, environ=environ)

    assert environ["KEY"] == "personal"


def test_the_search_walks_upward(tmp_path):
    """A key file at the repo root should serve an agent nested inside it."""
    nested = tmp_path / "agents" / "A01"
    nested.mkdir(parents=True)
    (tmp_path / ".env").write_text("KEY=from_root\n", encoding="utf-8")
    environ: dict[str, str] = {}

    load(nested, environ=environ)

    assert environ["KEY"] == "from_root"


def test_the_search_is_bounded_by_the_actual_tree_depth(tmp_path):
    """
    A checkout nearer the drive root has fewer parents than the CIE-OS layout.
    Walking a fixed number of levels off the end either raises or silently
    resolves to the drive root — which is how the original bug hid.
    """
    paths = candidate_paths(tmp_path)

    assert paths
    assert all(p.name in ENV_FILENAMES for p in paths)


def test_no_file_is_a_normal_state_not_an_error(tmp_path):
    result = load(tmp_path, environ={})

    assert not result.loaded
    assert result.applied == 0
    assert "must be exported" in describe(result)


def test_an_unreadable_file_does_not_raise(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("KEY=v\n", encoding="utf-8")

    def refuse(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr("pathlib.Path.read_text", refuse)
    result = load(tmp_path, environ={})

    assert not result.loaded


# ==============================================================================
# DISCLOSURE — a logged key is a rotated key
# ==============================================================================

def test_values_never_appear_in_the_result(tmp_path):
    (tmp_path / ".env").write_text("SECRET_KEY=sentinel-value\n", encoding="utf-8")

    result = load(tmp_path, environ={})

    rendered = str(result.as_dict())
    assert "SECRET_KEY" in rendered
    assert "sentinel-value" not in rendered


def test_values_never_appear_in_the_log(tmp_path, caplog):
    (tmp_path / ".env").write_text("SECRET_KEY=sentinel-value\n", encoding="utf-8")

    with caplog.at_level(logging.DEBUG, logger="config.dotenv"):
        load(tmp_path, environ={})

    assert "sentinel-value" not in caplog.text


def test_the_description_names_the_file_it_used(tmp_path):
    (tmp_path / ".env").write_text("A=1\n", encoding="utf-8")

    result = load(tmp_path, environ={})

    assert ".env" in describe(result)


# ==============================================================================
# IDEMPOTENCE
# ==============================================================================

def test_loading_twice_reports_the_first_load(tmp_path, monkeypatch):
    """
    Every entry point calls this. A second pass finds everything already set
    and would report "0 applied", which reads as "your key file did nothing".
    """
    monkeypatch.setenv("PATH", monkeypatch.__class__.__name__)  # touch real env
    (tmp_path / ".env").write_text("A01_TEST_KEY=v\n", encoding="utf-8")

    first = load(tmp_path)
    second = load(tmp_path)

    assert second is first
    assert second.applied == first.applied


def test_force_re_reads(tmp_path):
    (tmp_path / ".env").write_text("A01_TEST_KEY=v\n", encoding="utf-8")
    load(tmp_path)

    again = load(tmp_path, force=True)

    assert again.skipped == ("A01_TEST_KEY",)


# ==============================================================================
# THE POINT OF ALL THIS
# ==============================================================================

def test_a_key_file_activates_a_provider(tmp_path):
    """
    The end-to-end property. Before this module, this test could not pass:
    the file was read into a settings object that `keys.py` never consulted.
    """
    from blockchain.rpc.providers.keys import configured_providers

    environ: dict[str, str] = {}
    (tmp_path / ".env").write_text("ALCHEMY_API_KEY=demo\n", encoding="utf-8")

    assert configured_providers(environ) == ()
    load(tmp_path, environ=environ)

    assert "alchemy" in configured_providers(environ)
