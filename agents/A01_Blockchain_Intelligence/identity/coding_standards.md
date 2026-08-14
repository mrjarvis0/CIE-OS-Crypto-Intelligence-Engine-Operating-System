# Coding Standards

## A01 Blockchain Intelligence Agent

**Project:** CIE-OS (Crypto Intelligence Engine Operating System)

**Agent:** A01 Blockchain Intelligence Agent

**Document Type:** Coding Standards

**Version:** 1.0.0

**Status:** Approved (Foundation)

---

# 1. Purpose

This document defines the official coding standards for every source file, module, package, plugin, script, test, and utility inside the A01 Blockchain Intelligence Agent.

Every contributor (human or AI) must follow these standards.

---

# 2. Golden Rule

> **Code is written once but read thousands of times. Optimize for readability first.**

---

# 3. Programming Language

Official Language

* Python 3.13+

Mandatory Features

* Type Hints
* AsyncIO
* Dataclasses / Pydantic Models
* Context Managers
* Exception Chaining

Avoid legacy Python syntax.

---

# 4. File Standards

Maximum file size

* Preferred: ≤300 LOC
* Warning: >500 LOC
* Refactor Required: >800 LOC

One primary responsibility per file.

---

# 5. Folder Standards

Each module must contain:

* README.md
* **init**.py
* Source files
* Tests
* Examples (if applicable)

No empty placeholder folders in production.

---

# 6. Naming Standards

Packages

snake_case

Files

snake_case.py

Classes

PascalCase

Functions

snake_case()

Variables

snake_case

Constants

UPPER_CASE

Private Members

_prefix

No unclear abbreviations.

---

# 7. Import Standards

Import order:

1. Python Standard Library
2. Third-party Libraries
3. Shared CIE-OS Modules
4. Local Modules

Rules:

* No wildcard imports.
* No circular imports.
* One import per line.
* Remove unused imports.

---

# 8. Type Hint Standards

Every public function must define:

* Parameter types
* Return type

Avoid untyped public APIs.

Example

```python
def analyze_wallet(address: str) -> WalletReport:
    ...
```

---

# 9. Docstring Standards

Every public module, class, and function requires a docstring.

Include:

* Purpose
* Parameters
* Returns
* Raises
* Examples (when useful)

Private helpers may use concise comments when appropriate.

---

# 10. Async Standards

Async is mandatory for:

* Network I/O
* API Requests
* RPC Calls
* Database I/O
* WebSocket Processing

Never block the event loop.

Avoid synchronous network operations.

---

# 11. Error Handling Standards

Never suppress exceptions silently.

Always:

* Catch expected exceptions.
* Add context.
* Log failures.
* Re-raise when appropriate.

Avoid:

```python
except:
    pass
```

---

# 12. Logging Standards

Every important operation must log:

* Timestamp
* Module
* Action
* Result
* Duration
* Error (if any)

Never log:

* API Keys
* Secrets
* Tokens
* Private Data

---

# 13. Configuration Standards

Never hardcode:

* API Keys
* RPC URLs
* Secrets
* Credentials
* Chain IDs

Use:

* Environment Variables
* TOML
* YAML
* Pydantic Settings

---

# 14. Database Standards

Database access only through repositories.

Rules:

* Atomic writes
* Transactions when required
* Parameterized queries
* No raw SQL in business logic

---

# 15. Schema Standards

Every external payload must:

1. Validate
2. Normalize
3. Convert into internal schemas

Business logic must never consume raw external payloads directly.

---

# 16. AI Coding Standards

AI-generated code must:

* Compile successfully.
* Follow project architecture.
* Include type hints.
* Include documentation.
* Include tests.
* Avoid hallucinated APIs.
* Never bypass validation layers.

Generated code must be reviewed before merge.

---

# 17. Blockchain Coding Standards

Always support:

* Reorg handling
* Replay safety
* Idempotency
* Rate-limit handling
* Retry logic
* Timeouts

Never assume blockchain finality immediately.

---

# 18. Security Standards

Forbidden:

* eval()
* exec()
* Hardcoded secrets
* Unsafe deserialization
* Arbitrary shell execution

Security checks are mandatory before merge.

---

# 19. Performance Standards

Optimize after correctness.

Guidelines:

* Avoid unnecessary allocations.
* Cache when justified.
* Prefer streaming over loading entire datasets.
* Use async concurrency for I/O-bound work.
* Measure before optimizing.

---

# 20. Testing Standards

Minimum requirements:

* Unit Tests
* Integration Tests
* Error Path Tests
* Schema Validation Tests

Critical blockchain logic additionally requires:

* Historical replay tests
* Reorg tests
* Duplicate event tests

---

# 21. Documentation Standards

Every module must document:

* Purpose
* Inputs
* Outputs
* Dependencies
* Limitations

Documentation must evolve with implementation.

---

# 22. Git Standards

Commit messages:

* feat:
* fix:
* refactor:
* docs:
* test:
* perf:
* chore:

One logical change per commit.

---

# 23. Code Review Standards

Every merge request must verify:

* Builds successfully
* Tests pass
* Type checks pass
* Lint passes
* Documentation updated
* No duplicated logic
* No architectural violations

---

# 24. Forbidden Practices

Never:

* Copy-paste business logic
* Mix UI with business logic
* Ignore exceptions
* Hardcode configuration
* Skip validation
* Commit commented-out code
* Leave unused code in production

---

# 25. Coding Standard Statement

These standards define the official coding practices of the A01 Blockchain Intelligence Agent.

Any code that violates these standards must be corrected before being accepted into the project.

---

**End of Coding Standards Document**
