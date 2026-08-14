# ADR-001 – Grandfathering of LOC Limit Violations in `memory/base`

**Status:** Accepted

**Date:** 2026-08-02

**Deciders:** A01 Agent Owner, A01 Agent Implementation

---

## 1. Context

`identity/coding_standards.md` §4 (File Standards) defines maximum file size:

* Preferred: ≤300 LOC
* Warning: >500 LOC
* Refactor Required: >800 LOC

Seven legacy engine modules in `memory/base/` were authored before this
standard was established and exceed the 800 LOC "Refactor Required"
threshold:

| File                    | LOC   | Threshold Exceeded |
| ----------------------- | ----- | ------------------ |
| `long_term.py`          | 4357  | Yes                |
| `manager.py`            | 2852  | Yes                |
| `short_term.py`         | 2272  | Yes                |
| `summarizer.py`         | 1901  | Yes                |
| `vector_memory.py`      | 1775  | Yes                |
| `conversation.py`       | 1729  | Yes                |
| `memory.py`             | 1094  | Yes                |

Per `identity/constraints.md` AC-05, every architectural exception
requires an Architecture Decision Record (ADR). This ADR records the
exception.

## 2. Decision

1. The seven `memory/base/` engine modules listed above are
   **grandfathered** and may retain their current size. They are exempt
   from the 800 LOC "Refactor Required" threshold in
   `identity/coding_standards.md` §4.

2. **No new code is added to these files.** They are frozen as-is.
   New functionality is implemented in new `memory/` sub-packages
   (`retrieval`, `storage`, `schemas`, `conversation`, `vector`,
   `summarization`, `sync`, `monitoring`, `utils`).

3. Any future *modification* of an existing function within these files
   must not increase its size beyond its current footprint. Additive
   refactors that reduce size are welcome but not required.

4. **Decommissioning:** the stale duplicate `long_term.bak.py` was
   removed as part of this decision. It was an older copy of
   `long_term.py` (same class surface, shorter implementation) and was
   referenced by no import anywhere in the project.

5. New files created after this ADR **must** comply with
   `identity/coding_standards.md` §4 (≤800 LOC, prefer ≤300).

## 3. Consequences

### Positive

* The working memory subsystem is not destabilized by large refactors.
* Frozen `base/` acts as a stable contract surface for new layers.
* New sub-packages follow the LOC standard and single-responsibility
  rule from day one.

### Negative

* Legacy modules remain large and harder to review.
* Knowledge of `base/` internals remains necessary to use its contracts.

### Risks

* The frozen surface makes `base/` harder to evolve. Mitigation: new
  capabilities land in new sub-packages; `base/` is only a bridgehead.

## 4. Compliance

* `memory/base/` files are grandfathered per this ADR and do not
  require LOC reduction.
* All files outside `memory/base/` are bound by
  `identity/coding_standards.md` §4 without exception.

## 5. Related Documents

* `identity/coding_standards.md` §4 – File Standards
* `identity/constraints.md` AC-05 – ADR required for exceptions
* `identity/design_rules.md` – Rule hierarchy; ADR-authorized exceptions
* `identity/architecture.md` §16 – Architecture Governance
* `identity/changelog.md` – ADR references
