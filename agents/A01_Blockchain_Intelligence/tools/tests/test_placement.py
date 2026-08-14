"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the placement map, and for the things it promises.

The test that earns this file is `test_every_pointer_target_exists`. 140
generated READMEs each name a path; the day one of those paths is renamed, every
reader of that README is sent somewhere that does not exist, and nothing else in
the system would notice. Documentation that cannot fail is documentation that
quietly goes wrong.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools.placement import (
    GENERATED_MARKER,
    PLACEMENT,
    ROOT,
    Placement,
    State,
    empty_directories,
    generate,
    planned_reasons,
    resolve,
    verify,
)

SKIP_PARTS = frozenset(
    {"__pycache__", ".git", ".pytest_cache", ".venv", "node_modules", "data", "logs"}
)


def all_directories() -> list[Path]:
    return [
        d
        for d in ROOT.rglob("*")
        if d.is_dir() and not (SKIP_PARTS & set(d.relative_to(ROOT).parts))
    ]


# ==============================================================================
# THE PROMISE: NO HOLLOW DIRECTORIES
# ==============================================================================

def test_no_directory_is_completely_empty():
    """
    Every directory holds at least one file.

    An unexplained empty directory named `security/` invites code to be written
    in the wrong place — `docs/architecture/folder-architecture.md` §10.
    """
    hollow = [
        d.relative_to(ROOT).as_posix()
        for d in all_directories()
        if not any(c.is_dir() for c in d.iterdir())
        and not any(c.is_file() for c in d.iterdir())
    ]

    assert not hollow, f"directories with no file at all: {hollow[:10]}"


def test_no_directory_holds_only_a_gitkeep():
    """
    A `.gitkeep` makes git track a directory; it tells a reader nothing.
    """
    bare = []
    for d in all_directories():
        if any(c.is_dir() for c in d.iterdir()):
            continue
        files = [c for c in d.iterdir() if c.is_file()]
        if files and all(c.name == ".gitkeep" for c in files):
            bare.append(d.relative_to(ROOT).as_posix())

    assert not bare, f"directories with only a .gitkeep: {bare[:10]}"


def test_every_empty_directory_is_covered_by_the_table():
    report = verify()

    assert not report.uncovered, report.describe()


# ==============================================================================
# THE POINTERS MUST NOT ROT
# ==============================================================================

def test_every_pointer_target_exists():
    """
    The reason this module exists.

    Rename `contracts/events.py` and this fails, instead of leaving seven
    READMEs pointing at nothing.
    """
    report = verify()

    assert not report.missing_targets, report.describe()


def test_every_planned_directory_states_what_blocks_it():
    """An absence without a reason is indistinguishable from an oversight."""
    report = verify()

    assert not report.unexplained, report.describe()


def test_planned_skill_reasons_come_from_the_registry():
    """
    Two lists of "why this is not built" drift, and the drift is invisible. The
    table carries no skill reasons of its own; it reads them.
    """
    reasons = planned_reasons()
    assert reasons, "PLANNED_SKILLS should be readable"

    skill_rule = resolve("skills/smart_money")
    assert skill_rule is not None
    assert skill_rule.state is State.PLANNED
    assert not skill_rule.note, "the rule must defer to the registry, not restate it"


def test_a_generated_readme_names_the_reason_from_the_registry():
    produced = generate(write=False)
    body = produced.get("skills/smart_money", "")

    assert "token prices" in body, body[:200]


# ==============================================================================
# GENERATION IS DETERMINISTIC
# ==============================================================================

def test_regenerating_changes_nothing():
    """
    A generator whose output drifts run to run turns every regeneration into a
    diff nobody reads.
    """
    first = generate(write=False)
    second = generate(write=False)

    assert first == second


def test_generated_files_on_disk_match_what_the_table_would_write():
    """The tree is in sync with the table; nobody hand-edited a pointer."""
    stale = []
    for relative_path, expected in generate(write=False).items():
        on_disk = ROOT / relative_path / "README.md"
        if not on_disk.is_file() or on_disk.read_text(encoding="utf-8") != expected:
            stale.append(relative_path)

    assert not stale, (
        f"{len(stale)} pointer(s) differ from the table; "
        f"run `python -m tools.placement --write`: {stale[:5]}"
    )


def test_every_generated_file_carries_the_marker():
    """Without it, regeneration could not tell its own output from a real doc."""
    for relative_path, body in generate(write=False).items():
        assert body.startswith(GENERATED_MARKER), relative_path


# ==============================================================================
# THE TABLE ITSELF
# ==============================================================================

def test_implemented_rules_declare_a_target():
    for entry in PLACEMENT:
        if entry.state is State.IMPLEMENTED:
            assert entry.target, f"{entry.pattern} claims implemented with no target"


def test_the_most_specific_rule_wins():
    """`security/retrieval` must not be captured by the `security` rule."""
    specific = resolve("security/retrieval")

    assert specific is not None
    assert specific.target == "memory/retrieval"


# ==============================================================================
# SANDBOX IS NEVER IMPORTED
# ==============================================================================

def test_sandbox_is_marked_never():
    entry = resolve("sandbox")

    assert entry is not None
    assert entry.state is State.NEVER


def test_nothing_imports_from_sandbox():
    """
    README calls it "never shipped, never imported". An import would ship it.
    """
    offenders = []
    for path in ROOT.rglob("*.py"):
        if SKIP_PARTS & set(path.relative_to(ROOT).parts):
            continue
        if path.name == "test_placement.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "import sandbox" in text or "from sandbox" in text:
            offenders.append(path.relative_to(ROOT).as_posix())

    assert not offenders, f"sandbox is imported by: {offenders}"


# ==============================================================================
# THE EXAMPLES ACTUALLY RUN
# ==============================================================================

EXAMPLES = sorted((ROOT / "examples").glob("*.py"))


def test_examples_exist():
    assert len(EXAMPLES) >= 4, "the examples README documents four walkthroughs"


@pytest.mark.parametrize("script", EXAMPLES, ids=lambda p: p.stem)
def test_each_example_runs(script, tmp_path):
    """
    Documentation that cannot run rots into documentation that is wrong. These
    are offline — fixtures only — so they work with no network and no key.
    """
    args = [sys.executable, str(script)]
    if script.stem.startswith("04"):
        args.append(str(tmp_path / "dashboard.html"))

    result = subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, timeout=180
    )

    assert result.returncode == 0, (
        f"{script.name} exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-1500:]}\nstderr:\n{result.stderr[-1500:]}"
    )
    assert result.stdout.strip(), f"{script.name} printed nothing"
