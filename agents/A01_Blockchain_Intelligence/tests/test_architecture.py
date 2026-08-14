"""
CIE-OS
A01 Blockchain Intelligence Agent

Architecture: the layer stack, asserted over the source rather than described.

`docs/architecture/layered-architecture.md` §5 fixes one direction of
dependency for A01's layers, and lists three rules: no upward imports, no
skipped layers, no circular dependencies.

**Only two of those three are enforced here.** The project's own architecture
invariant is downward-only direction and absence of cycles; "no skipped layers"
is a stricter claim the codebase does not make and has never met -- `skills`
reading `database` directly is normal and correct. Asserting it would produce a
test that fails on arrival and gets deleted, which is worse than not having one.

Direction was `UNVERIFIED` before this module existed: the rule was written down
in a document, and nothing checked that the code agreed. It now has a measured
answer -- two upward imports, both named below with what they pull and why they
are not fixed here.

The allowlist is a ratchet, not an amnesty. It is asserted to be exactly right:
a new violation fails, and so does an entry that has been fixed but left behind.
"""

from __future__ import annotations

import ast

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The layer order from layered-architecture.md §5, lowest first. A package may
#: import anything below it and nothing above it.
#:
#: `Identity` is omitted: it is documentation, not an importable package.
#: `Validation` is omitted as a separate rank because it has no directory of its
#: own -- `normalization/quality.py` is where that responsibility lives.
LAYERS: tuple[str, ...] = (
    "config",
    "core",
    "memory",
    "sensors",
    "ingestion",
    "normalization",
    "database",
    # Storage tiering sits directly above the database it partitions: it reads
    # `database.connection` and `schemas`, and nothing above it.
    "tiers",
    # Selective capture reads the tiers it writes into, and nothing above.
    "pipeline",
    "skills",
    "intelligence",
    "decision",
    "interfaces",
)

RANK = {name: index for index, name in enumerate(LAYERS)}

#: Packages deliberately outside the ranked stack, and therefore unchecked.
#:
#: `layered-architecture.md` §5 does not place them, and inventing a rank to
#: make a test pass would be asserting an architecture nobody agreed to. They
#: are listed rather than silently skipped so the gap is legible: an import
#: crossing one of these is not checked by this module.
UNRANKED: frozenset[str] = frozenset({
    "blockchain", "chains", "cli", "contracts", "evaluation", "fixtures",
    "knowledge", "models", "planning", "prompts", "schemas", "telemetry", "tools",
})

#: Known upward imports, as ``(file, imported package, what it pulls)``.
#:
#: Both pull a single shared name from the layer above rather than calling into
#: it, so neither inverts control -- but both are still upward, and both are
#: fixed the same way: move the shared name down to a layer both sides can
#: reach. That relocation changes a package's public surface, so it is scoped
#: work rather than a side effect of adding this test. See BUILD_LOG.md.
KNOWN_UPWARD: frozenset[tuple[str, str, str]] = frozenset({
    (
        "skills/whale_detection/transfers.py",
        "intelligence",
        "DEFAULT_PERCENTILE, the whale threshold constant",
    ),
    (
        "intelligence/narrative/composer.py",
        "decision",
        "Stance, the conclusion vocabulary enum",
    ),
})


#: Import cycles between layers that already existed, as ``(pair, cause)``.
#:
#: This one is not a separate defect: it is what the `skills -> intelligence`
#: entry above *becomes* once `intelligence.engines.composition` reads
#: `skills.base` on the way down. One upward import is what closes the loop.
#:
#: It is listed separately anyway, because a cycle is the stronger claim. An
#: upward import bends the stack; a cycle means there is no stack to bend.
KNOWN_CYCLES: frozenset[tuple[str, str]] = frozenset({
    (
        "intelligence <-> skills",
        "skills/whale_detection/transfers.py pulls DEFAULT_PERCENTILE up, "
        "while intelligence/engines/composition.py reads skills.base down",
    ),
})


def _package_of(module: str) -> str:
    return module.split(".", 1)[0]


def _imports(path: Path) -> set[str]:
    """
    Top-level packages this file imports absolutely.

    Relative imports are skipped: they cannot leave their own package, so they
    can never cross a layer boundary.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:  # pragma: no cover - a syntax error fails elsewhere
        return set()

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(_package_of(alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.add(_package_of(node.module))
    return found


def _source_files(package: str):
    """Implementation files only. A test may import anything it needs."""
    return (
        path
        for path in (ROOT / package).rglob("*.py")
        if "__pycache__" not in path.parts and "tests" not in path.parts
    )


def _upward_imports() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for package in LAYERS:
        for path in _source_files(package):
            for imported in _imports(path):
                if imported in RANK and RANK[imported] > RANK[package]:
                    found.add((path.relative_to(ROOT).as_posix(), imported))
    return found


# ==============================================================================
# DIRECTION
# ==============================================================================

def test_every_ranked_layer_exists():
    """
    A renamed or removed package would otherwise make this module pass by
    checking nothing.
    """
    missing = [name for name in LAYERS if not (ROOT / name).is_dir()]

    assert not missing, f"ranked layers with no directory: {missing}"


def test_no_new_upward_import_is_introduced():
    """
    The invariant, as a ratchet.

    Failure here means a layer reached upward. The fix is to move the shared
    name down to a layer both sides can reach, not to extend the allowlist.
    """
    allowed = {(path, package) for path, package, _ in KNOWN_UPWARD}
    unexpected = sorted(_upward_imports() - allowed)

    assert not unexpected, "upward imports introduced: " + "; ".join(
        f"{path} -> {package}" for path, package in unexpected
    )


def test_the_known_upward_imports_are_still_there():
    """
    The other half of the ratchet. An entry that has been fixed must leave the
    allowlist, or the list rots into a description of a codebase that no longer
    exists and stops being evidence of anything.
    """
    allowed = {(path, package) for path, package, _ in KNOWN_UPWARD}
    resolved = sorted(allowed - _upward_imports())

    assert not resolved, (
        "these upward imports are fixed - remove them from KNOWN_UPWARD: "
        + "; ".join(f"{path} -> {package}" for path, package in resolved)
    )


def test_every_unranked_package_is_real():
    """
    UNRANKED documents a deliberate gap in coverage. A stale name in it would
    quietly widen that gap.
    """
    missing = sorted(name for name in UNRANKED if not (ROOT / name).is_dir())

    assert not missing, f"UNRANKED names a package that does not exist: {missing}"


def test_the_ranked_and_unranked_sets_do_not_overlap():
    overlap = sorted(set(LAYERS) & UNRANKED)

    assert not overlap, f"a package cannot be both ranked and unranked: {overlap}"


# ==============================================================================
# CYCLES
# ==============================================================================

def _cycles() -> set[str]:
    """
    Layer pairs that import each other.

    Checked between packages rather than between modules: a cycle inside one
    package is a design smell, but a cycle *across* layers means the stack is
    not a stack, which is the thing the architecture claims.
    """
    graph: dict[str, set[str]] = {}
    for package in LAYERS:
        edges: set[str] = set()
        for path in _source_files(package):
            edges.update(
                imported
                for imported in _imports(path)
                if imported in RANK and imported != package
            )
        graph[package] = edges

    return {
        " <-> ".join(sorted((package, other)))
        for package, edges in graph.items()
        for other in edges
        if package in graph.get(other, set())
    }


def test_no_new_import_cycle_is_introduced():
    """
    Cycles are the other half of the Section 6 invariant.

    Failure here means two layers now import each other. The fix is to move the
    shared name down to a layer both sides can reach.
    """
    known = {pair for pair, _ in KNOWN_CYCLES}
    unexpected = sorted(_cycles() - known)

    assert not unexpected, f"import cycles introduced: {unexpected}"


def test_the_known_import_cycles_are_still_there():
    """Same ratchet as the upward imports: a fixed cycle must leave the list."""
    known = {pair for pair, _ in KNOWN_CYCLES}
    resolved = sorted(known - _cycles())

    assert not resolved, (
        f"these cycles are broken - remove them from KNOWN_CYCLES: {resolved}"
    )
