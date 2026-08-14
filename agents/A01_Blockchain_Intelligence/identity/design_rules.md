# Design Rules Document

## A01 Blockchain Intelligence Agent

**Project:** CIE-OS (Crypto Intelligence Engine Operating System)

**Agent:** A01 Blockchain Intelligence Agent

**Document Type:** Design Rules

**Version:** 1.0.0

**Status:** Approved (Foundation)

---

# 1. Purpose

This document defines the mandatory design rules that govern the architecture, implementation, extension, and maintenance of the A01 Blockchain Intelligence Agent.

These rules are non-negotiable unless an approved Architecture Decision Record (ADR) explicitly authorizes an exception.

---

# 2. Golden Rule

> **Every design decision must improve maintainability, reliability, explainability, or scalability.**

If a design increases complexity without providing measurable value, it must be rejected.

---

# 3. Architecture Rules

## DR-01 — Layered Architecture Only

All processing must follow the official pipeline.

```
Sensors
    ↓
Ingestion
    ↓
Normalization
    ↓
Database
    ↓
Memory
    ↓
Skills
    ↓
Intelligence
    ↓
Decision
    ↓
Interfaces
```

No layer may bypass another.

---

## DR-02 — One Responsibility Per Module

Every module owns one responsibility.

Never combine:

* Data Collection
* Data Processing
* AI Reasoning
* Database Logic
* User Interface

inside the same module.

---

## DR-03 — Single Source of Truth

Every piece of information has one authoritative owner.

Examples:

* Configuration → config/
* Schemas → schemas/
* Knowledge → knowledge/
* State → memory/
* Database Models → database/

No duplicate ownership.

---

# 4. Dependency Rules

## DR-04

Dependencies always point downward.

Allowed:

```
interfaces
↓

decision
↓

intelligence
↓

skills
↓

database
↓

normalization
↓

ingestion
↓

sensors
```

Forbidden:

* Upward imports
* Circular imports
* Sideways dependencies

---

## DR-05

Shared functionality belongs only in:

* core/
* shared/
* utils/

Never duplicate helper logic.

---

# 5. Module Rules

Every module must contain:

* README.md
* Clear responsibility
* Public interface
* Internal implementation
* Tests
* Logging
* Error handling

No anonymous modules.

---

# 6. Naming Rules

Folders:

snake_case

Files:

snake_case.py

Classes:

PascalCase

Functions:

snake_case()

Constants:

UPPER_CASE

Variables:

snake_case

No abbreviations unless universally accepted.

---

# 7. Configuration Rules

Configuration must never be hardcoded.

Allowed:

* YAML
* TOML
* Environment Variables
* Pydantic Settings

Forbidden:

```
API_KEY = "..."
CHAIN_ID = 1
```

inside source code.

---

# 8. Data Rules

All external data must pass through:

1. Validation
2. Normalization
3. Deduplication

before storage.

Raw external data must never be trusted.

---

# 9. Database Rules

* Atomic writes only.
* Idempotent operations.
* Immutable historical records.
* No direct SQL outside repositories.
* Repository pattern mandatory.

---

# 10. State Rules

Runtime state belongs only in:

memory/

Persistent state belongs only in:

database/

State ownership must never be ambiguous.

---

# 11. Blockchain Rules

The system must always support:

* Chain reorganizations
* Duplicate events
* Delayed confirmations
* Replay processing
* Historical backfill

These are normal blockchain events—not exceptions.

---

# 12. Plugin Rules

Plugins must:

* Follow published interfaces.
* Register themselves.
* Be independently removable.
* Never modify core logic.
* Never directly access another plugin.

Core must remain plugin-independent.

---

# 13. AI Rules

AI modules may:

* Explain
* Summarize
* Classify
* Reason
* Estimate confidence

AI modules must never:

* Invent blockchain facts.
* Skip evidence.
* Bypass validation.
* Modify stored blockchain data.

---

# 14. Error Handling Rules

Every failure must:

* Be logged.
* Be classified.
* Be recoverable when possible.
* Preserve system consistency.

Silent failures are prohibited.

---

# 15. Logging Rules

Every important operation must log:

* Timestamp
* Module
* Operation
* Result
* Duration
* Error (if any)

Logs must never contain secrets.

---

# 16. Security Rules

Forbidden:

* Private key storage
* Transaction signing
* Secret hardcoding
* Unsafe deserialization
* Arbitrary code execution

Security is mandatory, not optional.

---

# 17. Performance Rules

Optimize only after correctness.

Priority:

1. Correctness
2. Reliability
3. Explainability
4. Maintainability
5. Performance

---

# 18. Testing Rules

Every module requires:

* Unit Tests
* Integration Tests
* Schema Validation Tests
* Error Path Tests

Critical modules additionally require replay tests using historical blockchain data.

---

# 19. Documentation Rules

Every public module must include:

* Purpose
* Inputs
* Outputs
* Dependencies
* Examples
* Limitations

Documentation must be updated with implementation changes.

---

# 20. Forbidden Design Patterns

The following are prohibited:

* Circular dependencies
* God classes
* God modules
* Hidden global state
* Hardcoded chain logic
* Duplicate business logic
* Direct database access outside repositories
* Business logic inside interfaces
* AI-generated conclusions without evidence

---

# 21. Design Review Checklist

Before merging any feature:

* Does it follow the architecture?
* Does it introduce unnecessary dependencies?
* Does it duplicate existing functionality?
* Is it modular?
* Is it testable?
* Is it documented?
* Is it explainable?
* Is it observable?

If any answer is "No", redesign before implementation.

---

# 22. Rule Hierarchy

If rules conflict:

1. Security
2. Data Integrity
3. Architecture
4. Explainability
5. Reliability
6. Maintainability
7. Performance
8. Developer Convenience

---

# 23. Design Rule Statement

These rules define the engineering contract of the A01 Blockchain Intelligence Agent.

Every future component, plugin, module, and contributor must comply with this document.

Approved exceptions must be documented through Architecture Decision Records (ADRs).

---

**End of Design Rules Document**
