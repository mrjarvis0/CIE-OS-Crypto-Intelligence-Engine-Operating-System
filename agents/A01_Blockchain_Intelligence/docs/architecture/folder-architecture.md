# Folder Architecture

## A01 Blockchain Intelligence Agent

**Project:** CIE-OS (Crypto Intelligence Engine Operating System)
**Document Type:** Structural Reference — Descriptive
**Version:** 1.0.0
**Status:** Authoritative
**Measured against:** working tree, verified by line count

---

# 1. Purpose

This document describes the **actual** on-disk structure of A01, with measured
sizes. It is descriptive, not aspirational: where a directory is empty or a
package is a scaffold, this document says so.

That honesty is the point. `identity/capabilities.md` describes intent;
`docs/architecture/component-architecture.md` describes design. This document
describes **what exists**, so a reader can tell the three apart.

> All line counts exclude `__pycache__` and are current as of v1.0.0 of this
> document. Regenerate rather than hand-edit them.

---

# 2. Top-Level Layout

```
A01_Blockchain_Intelligence/
├── core/            Runtime foundation — agent, lifecycle, context, runtime
├── config/          Configuration, RPC registry, provider config, secrets
├── intelligence/    Cognitive layer — the blockchain analysis itself
├── memory/          Persistence, retrieval, vector store, summarisation
├── planning/        Goal decomposition, task graph, execution, routing
├── tools/           Capability layer — adapters, blockchain tools, security
├── docs/            Architecture and tradecraft documentation
├── identity/        Mission, scope, principles, constraints
│
├── api/             (empty)
├── blockchain/      (empty)
├── cli/             (empty)
├── evaluation/      (empty)
├── knowledge/       (empty)
├── monitoring/      (empty)
├── prompts/         (empty)
├── reasoning/       (empty)
├── reporting/       (empty)
├── security/        (empty)
├── tests/           (empty)
└── workflows/       (empty)
```

## 2.1 Implemented packages, measured

| Package | Files | Lines | Avg/file | Assessment |
| --- | ---: | ---: | ---: | --- |
| `memory` | 94 | 34,488 | 366 | Substantial |
| `tools` | 155 | 22,291 | 143 | Substantial, uneven |
| `planning` | 78 | 16,973 | 217 | Substantial |
| `intelligence` | 146 | 10,185 | **69** | **Scaffold** |
| `core` | 7 | 4,871 | 695 | Dense, partially wired |
| `config` | 22 | 4,699 | 213 | Complete |
| **Total** | **502** | **93,507** | 186 | |

## 2.2 The structural finding

**A01's infrastructure is well developed. Its blockchain intelligence is not.**

`intelligence/` — the package that gives the agent its name and purpose — has
the most files (146) and the lowest density (69 lines/file). 71 of its 146
files are under 60 lines. By contrast `memory/` averages 366 and `core/` 695.

This is an inverted investment profile. The agent has an elaborate capacity to
remember, plan, and call tools, and comparatively little to *analyse*. Any
roadmap that does not correct this is building more scaffolding around an empty
centre.

The twelve empty directories are also structurally significant: they include
`api/` and `cli/`, which means **A01 currently has no entry point**. It cannot
be started, queried, or operated as a program.

---

# 3. Layer Responsibilities

The four substantive layers separate on a single axis — *what kind of decision
each one makes*:

| Layer | Decides | Must not |
| --- | --- | --- |
| `tools/` | **How** to obtain data | Interpret meaning |
| `intelligence/` | **What the data means** | Fetch data or choose objectives |
| `planning/` | **What to do next** | Interpret data |
| `memory/` | **What to retain and recall** | Decide or interpret |

`core/` hosts the runtime these four execute inside. `config/` supplies their
settings. Neither contains domain logic.

**Enforcement:** a `tools/` module that scores risk, or an `intelligence/`
module that opens a socket, is an architectural violation regardless of whether
it works. Dependency direction is `core → config`, and
`planning → intelligence → tools`, with `memory` accessible to all and
depending on none of them.

---

# 4. `core/` — Runtime Foundation

7 files, 4,871 lines. Unusually dense (695 lines/file).

| File | Lines | Role |
| --- | ---: | --- |
| `agent.py` | 2,341 | `BaseAgent`, config, identity, health, hooks, snapshots |
| `context.py` | 931 | `AgentContext` and context-var propagation |
| `lifecycle.py` | 700 | Lifecycle FSM, `AgentLifecycle` transition engine |
| `runtime.py` | 583 | `AgentRuntime` — services, startup, shutdown, workers |
| `exceptions.py` | 119 | Core exception hierarchy |
| `types.py` | 99 | Shared enums, `ExecutionResult` |
| `__init__.py` | 98 | Public API |

**Known structural debt.** `agent.py` and `runtime.py` were written in
sequential "parts", leaving artefacts: `runtime.py` defines `AgentRuntime`
twice, the second subclassing the first (`class AgentRuntime(AgentRuntime)`).
This is legal Python and it works, but it is confusing and defeats static
analysis. `agent.py` at 2,338 lines should be decomposed.

`core/agent.py` also redefines `AgentStatus` and `ExecutionMode`, which
`core/types.py` defines too, with different members (`agent.py:327` and
`types.py:32`). This divergence is a latent bug source and should be collapsed
to one definition.

---

# 5. `config/` — Configuration

22 files, 4,699 lines. The most complete package relative to its scope.

```
config/
├── settings.py       Pydantic settings, env-driven, SecretStr for secrets
├── constants.py      Environment enum, chain enum, defaults
├── paths.py          Project paths, per-environment .env file locations
├── environment.py    Environment detection
├── feature_flags.py  Runtime toggles
├── logging.py        Structured logging, optional OTel trace correlation
├── cache.py          Cache configuration
├── providers/        Etherscan, CoinGecko, DefiLlama, generic blockchain
├── rpc/    (1,509)   Chain registry, endpoint config, fallback, manager
├── security/ (1,044) API keys, secret resolution, input validation
└── templates/        Per-environment .env examples
```

`config/rpc/chains.py` currently hardcodes nine chains. Per
`docs/intelligence/future-problems.md` §4, this is the seam that must become
configuration-driven rather than code-driven as chain count grows.

---

# 6. `intelligence/` — Cognitive Layer

146 files, 10,185 lines. **This is the scaffold.**

| Subpackage | Files | Lines | Purpose | State |
| --- | ---: | ---: | --- | --- |
| `analysis` | 16 | 1,138 | Domain analyzers (wallet, whale, token, contract…) | Stub |
| `core` | 9 | 1,117 | Engine, pipeline, manager, session, state | Partial |
| `reasoning` | 11 | 967 | ReAct, CoT, ToT, reflection | Partial |
| `schemas` | 9 | 828 | Canonical intelligence models | Partial |
| `utils` | 8 | 784 | Normalisation, hashing, formatting | Partial |
| `correlation` | 10 | 618 | Cross-source linking, bridges, clusters | Stub |
| `scoring` | 12 | 608 | Risk, trust, fraud, anomaly scores | Stub |
| `evidence` | 9 | 599 | Provenance, chains, confidence, graph | Stub |
| `attribution` | 7 | 564 | Identity, labels, ownership, heuristics | Stub |
| `graph` | 8 | 533 | Flow graphs, clustering, pathfinding | Stub |
| `prediction` | 7 | 421 | Trend/scenario forecasting | Stub |
| `timeline` | 6 | 371 | Event reconstruction | Stub |
| `verification` | 8 | 346 | Cross-checking claims | Stub |
| `monitoring` | 6 | 344 | Metrics, diagnostics, health | Stub |
| `reporting` | 8 | 315 | Report rendering | Stub |
| `hypothesis` | 6 | 296 | Generation, testing, elimination | Stub |
| `alerts` | 5 | 253 | Triggers, notifications, subscriptions | Stub |

The three packages that carry A01's core promises — `evidence` (599 lines),
`attribution` (564), and `verification` (346) — are among the smallest. The
normative requirements for all three are specified in
`docs/intelligence/attribution-doctrine.md` and
`docs/intelligence/evidence-standard.md`, each with an implementation-status
table serving as the backlog.

---

# 7. `memory/` — Persistence and Recall

94 files, 34,488 lines. The largest package by a wide margin.

| Subpackage | Files | Lines | Purpose |
| --- | ---: | ---: | --- |
| `base` | 8 | 18,962 | Short/long-term memory, summarizer, vector memory |
| `vector` | 16 | 3,388 | Embeddings, index, search, maintenance |
| `storage` | 12 | 2,097 | sqlite, postgres, redis, filesystem, cache, backup |
| `retrieval` | 11 | 2,206 | Filters, ranking, reranking |
| `schemas` | 12 | 1,982 | Memory, entity, message, session models |
| `summarization` | 6 | 1,845 | Compression and summarisation |
| `conversation` | 11 | 1,807 | Session, messages, replay, timeline |
| `utils` | 9 | 981 | Shared helpers |
| `sync` | 4 | 623 | Synchronisation |
| `monitoring` | 4 | 591 | Memory metrics |

`memory/base/` at 18,962 lines across 8 files (avg 2,370) is the densest
directory in A01 and warrants decomposition.

**Forward-looking note.** `docs/intelligence/future-problems.md` §6 argues this
package must evolve from a cache into an **archive of record** as chain history
expiry makes deep history non-retrievable. That is a design decision to make
while the package is still malleable.

---

# 8. `planning/` — Goal and Task Orchestration

78 files, 16,973 lines. The only package with a real test suite.

| Subpackage | Files | Lines |
| --- | ---: | ---: |
| `utils` | 10 | 5,444 |
| `tests` | 10 | 2,034 |
| `tasks` | 9 | 1,790 |
| `reasoning` | 8 | 1,296 |
| `goals` | 6 | 1,245 |
| `core` | 9 | 1,220 |
| `execution` | 6 | 1,045 |
| `monitoring` | 7 | 973 |
| `schemas` | 7 | 950 |
| `routing` | 5 | 875 |

---

# 9. `tools/` — Capability Layer

155 files, 22,291 lines.

| Subpackage | Files | Lines | Notes |
| --- | ---: | ---: | --- |
| `adapters` | 10 | 3,323 | REST, RPC, WebSocket, gRPC, MCP, subprocess |
| `blockchain` | 11 | 2,810 | Chain-specific tooling |
| `core` | 17 | 2,065 | Tool base, registry, invocation |
| `ai` | 8 | 1,716 | Model interaction |
| `utils` | 9 | 1,674 | Shared helpers |
| `routing` | 17 | 1,646 | Tool selection and dispatch |
| `security` | 10 | 1,416 | Sandbox, auth, permissions, rate limit, encryption |
| `web` | 8 | 1,129 | Web retrieval |
| `marketplace` | 10 | 1,028 | Tool distribution |
| `governance` | 10 | 995 | Policy |
| `lifecycle` | 10 | 973 | Tool lifecycle |
| `monitoring` | 8 | 890 | Tool metrics |
| `schemas` | 8 | 897 | Tool models |
| `discovery` | 7 | 850 | Tool discovery |
| `plugins` | 11 | 839 | Plugin system |

`tools/adapters/` and `tools/security/` are the packages with the largest
security surface; `docs/intelligence/threat-model.md` §3.3 audits them and
lists the outstanding gaps (SSRF allowlist, redirect revalidation, response
limits).

---

# 10. Empty Directories

Twelve directories exist with no implementation:

| Directory | Intended role | Impact of absence |
| --- | --- | --- |
| `api/` | REST/WebSocket surface | **No programmatic entry point** |
| `cli/` | Command-line interface | **Agent cannot be run** |
| `tests/` | Agent-level test suite | No integration coverage |
| `evaluation/` | Backtesting, calibration | **Blocks `maturity: validated`** for every detector |
| `reporting/` | Output rendering | Duplicate of `intelligence/reporting/` — resolve |
| `reasoning/` | — | Duplicate of `intelligence/reasoning/` — resolve |
| `monitoring/` | — | Duplicate of `intelligence/monitoring/` — resolve |
| `security/` | — | Duplicate of `tools/security/` — resolve |
| `blockchain/` | — | Duplicate of `tools/blockchain/` — resolve |
| `knowledge/` | Knowledge graph | Future capability |
| `prompts/` | Prompt templates | Currently inline |
| `workflows/` | Workflow definitions | Future capability |

**Two actions follow.** First, `api/`, `cli/`, and `evaluation/` are genuine
gaps that block operation and validation respectively. Second, five of these
duplicate a subpackage that already exists elsewhere; they should be deleted
rather than left as ambiguous placeholders, because an empty directory named
`security/` invites code to be written in the wrong place.

---

# 11. Naming and Placement Rules

1. A subpackage name that appears at two levels (`reasoning`, `monitoring`,
   `security`, `reporting`) must have exactly one implementation. The
   layer-level one wins; the top-level duplicate is removed.
2. Every package has an `__init__.py` that exports its public API and nothing
   else — no logic, no heavy imports. `config/__init__.py` follows this
   deliberately, because config modules read the environment at import time.
3. Tests live beside the package they test (`<package>/tests/`), matching the
   existing convention in `memory/` and `planning/`.
4. A file exceeding ~800 lines is a decomposition candidate. `core/agent.py`
   (2,338) and the `memory/base/` files (avg 2,370) currently violate this.

---

# 12. Regenerating This Document

The measurements here go stale. Regenerate with:

```bash
find . -name "*.py" -not -path "*__pycache__*" -exec wc -l {} + | tail -1
```

Per-package, from the agent root:

```bash
for d in config core intelligence memory planning tools; do n=$(find $d -name "*.py" -not -path "*__pycache__*" | wc -l); l=$(find $d -name "*.py" -not -path "*__pycache__*" -exec cat {} + | wc -l); echo "$d: $n files, $l lines"; done
```

---

**End of Folder Architecture**
