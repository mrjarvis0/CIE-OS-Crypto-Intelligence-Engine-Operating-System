# Capabilities Document

## A01 Blockchain Intelligence Agent

**Project:** CIE-OS (Crypto Intelligence Engine Operating System)

**Agent:** A01 Blockchain Intelligence Agent

**Document Type:** Capability Catalog

**Version:** 2.7.0

**Status:** Authoritative — grounded against the working tree

---

# 1. Purpose

This document defines every capability the A01 Blockchain Intelligence Agent is
designed to provide, **and states honestly where each one currently stands**.

A capability represents *what the agent can do*, independent of how it is
implemented. Capabilities remain stable even if the architecture, language,
models, or infrastructure change.

## 1.1 What changed in v2.0.0

v1.0.0 of this document marked most capabilities `MVP`. Measured against the
code, that was aspirational rather than accurate: the `intelligence/` package
averages 69 lines per file and its analysis, attribution, evidence, and
verification subpackages are scaffolds (see
`docs/architecture/folder-architecture.md` §6).

Publishing a capability the system does not have is not a documentation
problem — it is a correctness problem. Downstream CIE-OS agents make routing
and trust decisions from this catalog. v2.0.0 therefore replaces intent-based
maturity with **evidence-based maturity**, and separates *designed*, *built*,
and *validated*.

## 1.2 What changed in v2.1.0

Four claims in v2.0.0 had gone stale in the other direction — the catalog
under-reported what had since been built. Understating a capability is a
smaller failure than overstating one, but it is the same failure: the catalog
stopped matching the tree.

Corrected against the working tree:

* `cli/` is no longer empty. A01 has a working entry point (§9).
* `evaluation/` is no longer empty. The backtesting harness exists; what
  blocks `Validated` promotion is now labelled data, not code (§3).
* DET-WHALE-01 and DET-DORMANT-01 are `Implemented`, not `Scaffold` — both are
  registered in the pipeline and reachable via `python -m cli detectors` (§5).
* Evidence DAG invariants are implemented in `evidence_graph.py` (§6).

v2.1.0 also names the gap that actually limits the agent today, which no
previous version stated: `blockchain/` and `intelligence/` are **not
connected** (§9).

## 1.3 What changed in v2.2.0

Roadmap phases 1–3 landed. `sensors/` and `ingestion/` exist, and the capture
half of the gap named in v2.1.0 is closed: A01 reads live chains, in order,
reorg-safe and resumable (§4, C-01 and C-02).

The gap is now the storage half — `normalization/`, `schemas/` and `database/`
remain empty, so captured records reach a queue and stop there. §9 states the
current boundary precisely.

## 1.4 What changed in v2.3.0

Roadmap phases 4 and 5 landed. `schemas/`, `normalization/` and `database/`
exist, and the capture-to-storage path is complete end to end against live
Ethereum (§4, C-03 to C-06).

The gap moves again, and this is the last time it moves before A01 becomes
useful: the data is on disk and nothing reads it. §9 states the boundary.

## 1.5 What changed in v2.4.0

Roadmap phases 6 and 7 landed, and the pipeline closed. `skills/` reads
stored history, `intelligence/engines` composes skills into the subject the
detectors consume, and DET-WHALE-01 has fired on live Ethereum data A01
captured itself -- no hand-written subject anywhere in the path.

Three of eighteen skills are implemented. The remaining fifteen are recorded
in `skills.registry.PLANNED_SKILLS` with the data source each is waiting on,
so an absence is explained rather than merely absent.

The new honesty primitive is **coverage**. An answer from storage is a
statement about storage, and asked of a shallow database "no activity found"
is true of the database and false of the chain. Every skill result therefore
carries the window it used and whether that window licenses a negative claim;
composition reduces those by minimum, so the subject is only as trustworthy as
its thinnest input.

## 1.6 What changed in v2.5.0

Roadmap phases 8 and 9 landed. `decision/` decides what may be said;
`interfaces/` exposes it through one service facade behind both the CLI and
a read-only REST API (§4, C-09 to C-11).

The change that matters most is what A01 now refuses to do. `decision/`
enforces §3's privileges in code rather than in prose: `Implemented` caps
confidence at 0.60, and **only `Validated` may alert**. Both detectors are
`Implemented`, so the gate currently suppresses every alert and reports the
reason. That is the specified behaviour, not a gap -- and building the gate
before the first alert ships is the only moment it can be built without an
override flag.

The vocabulary table from `evidence-standard.md` §7 also moved into
`decision.vocabulary`. It was assigned to `intelligence/reporting`, which was
right when there was one renderer; with a CLI and a REST API, a rule enforced
in each renderer is enforced in none, so the verb is now bound where a
conclusion is *formed*.

## 1.7 What changed in v2.6.0

Roadmap phases 10–13 landed, completing the thirteen-phase plan (§4, C-12 to
C-14).

Phase 10 is the AI layer, and its deliverable is a **refusal**, not a feature.
`intelligence/narrative` composes explanations deterministically — grounded by
construction, reproducible, usable as a regression baseline — and
`GroundingCheck` verifies every particular a narrative states against the
evidence, including the abbreviated `0xabcd…wxyz` form at both ends. No model is
configured; the seam exists now because the only moment to make the checked path
the *only* path is before anyone needs a narrative shipped.

Phase 11 added a replay harness over recorded mainnet blocks, which made three
paths testable that mainnet will not perform on request: a reorg, a deep fork,
and a provider failure mid-range.

Phase 12 measured before optimising, and the finding was a *shape* rather than a
constant: address totals were linear in an address's lifetime activity. They are
now bounded and reported as floors.

Phase 13 added telemetry that reports **whether A01 is lying** alongside whether
it is working — `coverage_supports_absence`, `conclusions_undetermined`,
`alerts_suppressed` — plus verified backup and restore.

## 1.8 What changed in v2.7.0

Token decoding landed. `contracts/` reads ERC-20 and ERC-721 `Transfer` events,
`schemas/token.py` and `normalization/logs.py` map them, and migration v2 stores
them (§4, C-15).

The audit that prompted it found two things. First, **A01 was nearly blind on
layer 2**: on live Arbitrum and Optimism blocks the largest *native* transfer was
`0.0000`, because everything real moves as tokens. Second, **the data was already
being fetched and discarded** — the sensor returned logs and the pipeline
rejected them with "no canonical mapping for record kind 'logs'".

The decoding rests on one fact worth stating in the catalog, because getting it
wrong is invisible: **ERC-20 and ERC-721 `Transfer` events share a topic0.**
Identity comes from log *shape* — three topics with 32 bytes of data is a token
amount, four topics with empty data is an NFT `tokenId`. A decoder keyed on the
signature alone reads every NFT movement as a transfer of `tokenId` units, which
is enormous, plausible and fabricated.

Decimals remain unresolved and are marked as such. That is a new honesty
primitive of the same kind as coverage: raw base units are comparable within one
token and never across tokens, and the repository enforces it by requiring a
token argument for any ordering by value.

---

# 2. Capability Principles

Every capability must satisfy:

* Modular
* Independent
* Testable
* Explainable
* Reusable
* Observable
* Versioned
* Extensible

Every capability must expose defined inputs, outputs, and measurable success
criteria.

**Added in v2.0.0:** every *analytical* capability must additionally declare a
documented error rate and an enumerated set of known false-positive sources.
A capability that cannot state how it fails is not ready to be trusted, and is
capped at `Scaffold` maturity regardless of how much code backs it.

---

# 3. Capability Maturity Levels

v2.0.0 replaces the MVP/Beta/Future scale, which mixed *intent* with *status*.

| Level | Definition | May emit |
| --- | --- | --- |
| **Spec** | Specified in a tradecraft document; no implementation | Nothing |
| **Scaffold** | Code exists but is incomplete or unvalidated | Indicators only |
| **Implemented** | Functionally complete; error rate unmeasured | Conclusions ≤ 0.60 confidence |
| **Validated** | Backtested with measured precision/recall | Conclusions at full confidence; may raise alerts |

**Target** indicates the intended level for v1 of the agent.

Promotion to `Validated` requires the `evaluation/` package. That package now
exists — `evaluation/backtest.py` runs a detector against a labelled window and
returns the measured `ErrorRate`; `evaluation/metrics.py` reports precision
alongside the posterior implied by a supplied base rate, so a detector cannot be
promoted on an accuracy figure that means nothing in deployment.

What is still missing is the **labelled historical data** to run it against.
Until that exists, **no capability in A01 can reach `Validated`**, and this
remains the single highest-leverage gap in the system — but it is now a data
problem, not a code problem.

---

# 4. Core Capabilities

| ID | Capability | Modules | Now | Target |
| --- | --- | --- | --- | --- |
| C-01 | Multi-chain observation | `sensors/`, `blockchain/rpc`, `config/rpc` | Implemented | Validated |
| C-02 | Data collection | `ingestion/`, `tools/adapters` | Implemented | Validated |
| C-03 | Data validation | `normalization/evm`, `normalization/quality` | Implemented | Validated |
| C-04 | Data normalization | `schemas/`, `normalization/normalizer` | Implemented | Validated |
| C-05 | Persistent intelligence storage | `memory/storage`, `memory/base` | Implemented | Validated |
| C-06 | Chain system of record | `database/` | Implemented | Validated |
| C-07 | Capability layer | `skills/` | Implemented | Validated |
| C-08 | Skill composition | `intelligence/engines` | Implemented | Validated |
| C-09 | Maturity and vocabulary enforcement | `decision/maturity`, `decision/vocabulary` | Implemented | Validated |
| C-10 | Alerting with budgets | `decision/alerts` | Implemented | Validated |
| C-11 | Service facade and REST API | `interfaces/` | Implemented | Validated |
| C-12 | Grounded narrative generation | `intelligence/narrative` | Implemented | Validated |
| C-13 | Deterministic replay and regression | `fixtures/`, `tests/` | Implemented | Validated |
| C-14 | Telemetry, backup and recovery | `telemetry/` | Implemented | Validated |
| C-15 | Token and NFT movement | `contracts/`, `schemas/token`, `database/tokens` | Implemented | Validated |

**C-01 note.** `config/rpc/chains.py` registers nine chains
(Ethereum, BNB, Polygon, Arbitrum, Optimism, Base, Avalanche, Solana, Bitcoin)
with fallback and health tracking. `sensors/evm` reads the seven EVM chains
over that transport; Solana and Bitcoin speak different RPC dialects and have
no sensor yet, so they remain registry-only.

**C-02 note.** `ingestion/` follows a chain head at its configured confirmation
depth, detects reorgs through parent linkage, withdraws orphaned segments,
deduplicates by content-addressed record id, and resumes from an atomically
written checkpoint. Verified end to end against live Ethereum mainnet; the
reorg, deep-fork, finality-violation, and crash-resume paths are covered by
scripted tests, since none of them can be arranged on a real chain.

**C-03/C-04 note.** Validation refuses; quality annotates. A payload that
cannot state which block it is, what it follows, or when it happened is
rejected whole — nothing is defaulted, because a substituted value turns "the
provider did not say" into a claim about the chain. Completeness findings
travel with accepted records instead, carrying an explicit `do_not_infer` so a
detector cannot read a block fetched without transactions as a block with none.

**C-05 note.** `memory/` is A01's most developed package (34,488 lines) with
sqlite, postgres, redis, filesystem, and cache backends plus snapshot, backup,
restore, and migration services. Per DR-10 it holds runtime recall; chain
history belongs to `database/`.

**C-15 note.** ERC-20 and ERC-721 transfers are decoded, stored and queryable;
approvals are recognised and deliberately excluded from flow analysis, and
ERC-1155 is recognised and declined pending its own schema. Token amounts carry
`decimals_known = False` until a `decimals()` source exists, so they are
comparable within one token only. Token transfers cascade from their block row,
so a reorg withdrawal removes them with the block that carried them.

**C-06 note.** Blocks are keyed by hash rather than height, so the two blocks a
reorg produces at one height coexist and the fork stays visible. Withdrawal
sets a flag and never deletes, and reads exclude withdrawn rows by default so a
forgotten filter fails safe. Amounts are stored as zero-padded decimal text:
`INTEGER` is 64-bit and silently truncates above roughly nine ether in wei,
which would corrupt precisely the transfers a whale detector exists to find.

**C-07 note.** Three of eighteen skills are implemented: `wallet_profile`,
`whale_transfers`, `token_flow`. Each is `limited` rather than plain
`implemented`, and declares what bounds it — no balance sensor, no price feed
or contract labels, no event-log decoding. The other fifteen are recorded with
the data source each needs; `smart_money` in particular stays unbuilt because a
ranking without prices or entity labels would order addresses by activity under
the name of an ordering by skill.

**C-08 note.** Composition is what closed the pipeline: the detectors now read
a subject assembled from stored history rather than one written by hand.
Coverage reduces by minimum across contributing skills, so a deep window on one
field cannot license an absence claim about a field that came from a shallow
one, and the report states outright whether negative claims are licensed at
all.

---

# 5. Intelligence Capabilities

These are the capabilities that make A01 a *blockchain intelligence* agent
rather than a data pipeline. Detection-level specifications — thresholds,
false-positive sources, evasion surface — are in
`docs/intelligence/detection-catalog.md`.

| Capability | Detector | Modules | Now | Target |
| --- | --- | --- | --- | --- |
| Wallet intelligence | — | `intelligence/analysis/wallet.py` | Scaffold | Validated |
| Whale detection | DET-WHALE-01 | `intelligence/analysis/whale.py` | Implemented | Validated |
| Dormant reactivation | DET-DORMANT-01 | `intelligence/analysis/dormant.py` | Implemented | Validated |
| Structuring detection | DET-STRUCT-01 | — | Spec | Implemented |
| Smart money tracking | — | `intelligence/scoring` | Scaffold | Implemented |
| Exchange flow intelligence | — | `intelligence/analysis/exchange.py` | Scaffold | Validated |
| Stablecoin intelligence | — | `intelligence/analysis/token.py` | Scaffold | Implemented |
| Token movement | — | `contracts/`, `database/tokens` | Implemented | Validated |
| Liquidity intelligence | — | `intelligence/analysis/liquidity.py` | Scaffold | Implemented |
| Token intelligence | — | `intelligence/analysis/token.py` | Scaffold | Validated |
| Governance intelligence | — | `intelligence/analysis/governance.py` | Scaffold | Implemented |
| Validator intelligence | — | — | Spec | Implemented |
| Cross-chain intelligence | DET-BRIDGE-01 | `intelligence/correlation/bridge_linking.py` | Scaffold | Implemented |
| Anomalous outflow | DET-EXPLOIT-02 | — | Spec | Validated |
| Flash-loan manipulation | DET-EXPLOIT-01 | `intelligence/analysis/contract.py` | Spec | Implemented |
| Rug-pull indicators | DET-RUG-01 | — | Spec | Implemented |
| MEV / sandwich detection | DET-MEV-01 | — | Spec | Implemented |
| Atomic arbitrage | DET-ARB-01 | — | Spec | Implemented |
| Developer intelligence | — | `intelligence/correlation/github_linking.py` | Scaffold | Implemented |

## 5.1 Two capabilities that must never be over-promised

**Rug-pull detection** alleges intent to defraud. A01 emits enumerated
`rug_risk_indicators`, never an `is_rug_pull` verdict. The determination
belongs to a human analyst. See `docs/intelligence/detection-catalog.md` §5.

**Identity attribution** is bounded at 0.40 confidence on on-chain evidence
alone. A01 attributes addresses to clusters with high confidence, clusters to
behaviours with moderate confidence, and clusters to real-world identities only
with recorded external corroboration. See
`docs/intelligence/attribution-doctrine.md` §2.

---

# 6. Attribution and Evidence Capabilities

Newly enumerated in v2.0.0. These are cross-cutting capabilities the previous
version left implicit, despite them being the foundation of everything in §5.

| Capability | Doctrine | Modules | Now | Target |
| --- | --- | --- | --- | --- |
| Layered attribution (L1/L2/L3) | Attribution §2 | `intelligence/attribution` | Spec | Validated |
| Co-ownership clustering | Attribution §3 | `intelligence/correlation/cluster.py` | Scaffold | Validated |
| Collaborative-tx exclusion (CoinJoin) | Attribution §3.1 | — | Spec | Validated |
| Cluster-collapse circuit breaker | Attribution §3.2 | — | Spec | Validated |
| Chain-model dispatch (UTXO vs account) | Attribution §3.3 | — | Spec | Validated |
| Base-rate correction | Attribution §4.2 | `intelligence/scoring` | Spec | Validated |
| Evidence chain with provenance | Evidence §4 | `intelligence/evidence` | Scaffold | Validated |
| Content-addressed evidence ids | Evidence §4.1 | — | Spec | Implemented |
| Evidence DAG invariants | Evidence §5 | `intelligence/evidence/evidence_graph.py` | Implemented | Validated |
| Confidence calibration | Evidence §2.1 | `evaluation/metrics.py` | Implemented | Validated |
| AI output grounding check | Evidence §6 | `intelligence/narrative/grounding.py` | Implemented | Validated |
| Confidence vocabulary enforcement | Evidence §7 | `intelligence/reporting` | Spec | Implemented |

**These twelve rows are the real backlog.** Every capability in §5 inherits its
trustworthiness from them. Building more analyzers before these exist produces
more unverifiable output, not more intelligence.

---

# 7. AI Capabilities

| Capability | Modules | Now | Target |
| --- | --- | --- | --- |
| Explainable reasoning | `intelligence/narrative` | Implemented | Validated |
| AI output grounding | `intelligence/narrative/grounding.py` | Implemented | Validated |
| Confidence scoring | `intelligence/scoring/confidence` | Scaffold | Validated |
| Risk scoring | `intelligence/scoring` | Scaffold | Validated |
| Pattern recognition | `intelligence/correlation/pattern_matching.py` | Scaffold | Implemented |
| Anomaly detection | `intelligence/scoring/anomaly` | Scaffold | Implemented |
| Hypothesis generation and elimination | `intelligence/hypothesis` | Scaffold | Implemented |
| Predictive intelligence | `intelligence/prediction` | Scaffold | Implemented |

## 7.1 The ML boundary

A01 permits machine learning for **triage and ranking**, never for
**conclusion**. A model may decide what a human or a deterministic pipeline
examines next; it may not be the component that asserts a fact.

This preserves the evidence standard while capturing most of the practical
benefit, since correctly prioritising the queue is most of the value in
intelligence work. Rationale in `docs/intelligence/future-problems.md` §9.

## 7.2 AI output is never a fact source

Model output is at best inferred evidence and never a leaf in the evidence
chain. Any factual assertion in AI output that does not map to an existing
`evidence_id` is a hallucination by definition and is stripped before
publication. See `docs/intelligence/evidence-standard.md` §6.

---

# 8. Infrastructure Capabilities

Verified present:

* Asynchronous processing — `core/runtime.py`, `core/lifecycle.py`
* Multi-source ingestion — `tools/adapters` (REST, RPC, WebSocket, gRPC, MCP, subprocess)
* Plugin architecture — `tools/plugins`, `tools/marketplace`
* Schema validation — `config/security/validation.py`, pydantic settings
* Historical and runtime memory — `memory/`
* Health monitoring — `core/runtime.py`, `tools/monitoring`
* Structured logging — `config/logging.py`, with optional OpenTelemetry trace correlation
* Configuration management — `config/`, environment-aware with `SecretStr`
* RPC failover — `config/rpc/fallback.py`, `config/rpc/rpc_manager.py`
* Sandboxed execution — `tools/security/sandbox.py`, argv-only with env scrubbing
* Backtesting harness — `evaluation/backtest.py`, `evaluation/metrics.py`
* Prompt-injection defence — `prompts/fencing.py`, `prompts/sanitize.py`
* Reorg-safe capture — `ingestion/poller.py`, `ingestion/recovery.py`
* Exact 256-bit quantities — `schemas/amount.py`, padded for SQL ordering
* Atomic idempotent storage — `database/repositories.py`, versioned migrations
* Resumable ingestion — `ingestion/checkpoint.py`, atomic writes, corruption refused
* Idempotent processing — `ingestion/dedup.py`, content-addressed record ids
* Backpressure — `ingestion/queue.py`, bounded with a reported overflow policy

* Telemetry and metrics export — `telemetry/metrics.py`, bounded cardinality
* Verified backup and restore — `telemetry/backup.py`, SQLite online backup
* Deterministic replay — `fixtures/replay.py` over recorded mainnet blocks

All infrastructure capabilities in the v1 plan are now present.

---

# 9. Communication Capabilities

| Channel | Status |
| --- | --- |
| CLI | ✅ `python -m cli` — `investigate`, `detectors`, `skills`, `serve`, `doctor` |
| Structured JSON | ✅ `--format json` on `investigate` and `detectors` |
| REST API | ✅ `interfaces/rest.py` — GET-only, loopback-bound, no dependency |
| WebSocket | ❌ No event source yet; ingestion is stepped, not resident |
| Dashboard | ❌ Not started |
| Internal CIE-OS messaging | ❌ Not started |

**A01 has an entry point.** `python -m cli doctor` self-checks the chain
registry, settings load, pipeline wiring, secret redaction, and runs a smoke
investigation; `python -m cli detectors` reports each detector's maturity so a
caller can tell a validated conclusion from a scaffold's guess before relying
on either.

The pipeline is closed. `blockchain/rpc` → `sensors/` → `ingestion/` →
`normalization/` → `database/` → `skills/` → `intelligence/` runs end to end,
and `python -m cli investigate --db a01.db --address 0x…` composes its subject
from stored history rather than from the caller. DET-WHALE-01 has fired on live
Ethereum data A01 captured itself.

What limits A01 now is not wiring but evidence quality, in three named forms:
**coverage** (a shallow window licenses no negative claim), **missing sensors**
(no balance state, prices, contract labels or event-log decoding), and **no
measured error rate** — `evaluation/` has still never run against a labelled
window, so every conclusion is capped at 0.60 confidence.

That last one is now the highest-leverage gap in the system. Every capability
below inherits its ceiling from it.

---

# 10. Plugin Capabilities

The architecture supports installable blockchain plugins. Chains registered in
`config/rpc/chains.py` today:

| Chain | Chain ID | Model | Coverage |
| --- | --- | --- | --- |
| Ethereum | 1 | EVM | Registry only |
| BNB Chain | 56 | EVM | Registry only |
| Polygon | 137 | EVM | Registry only |
| Arbitrum | 42161 | EVM | Registry only |
| Optimism | 10 | EVM | Registry only |
| Base | 8453 | EVM | Registry only |
| Avalanche C-Chain | 43114 | EVM | Registry only |
| Solana | — | Solana-like | Registry only |
| Bitcoin | — | Bitcoin-like | Registry only |

"Registry only" means endpoint configuration and failover exist; sustained
observation and analysis do not.

Planned: Sui, Hyperliquid, and additional rollups. Per
`docs/intelligence/future-problems.md` §4, adding chains must become a
configuration action rather than an implementation action before the list grows
much further.

---

# 11. Future Capabilities

Deliberately excluded from v1:

* Blockchain Digital Twin
* Blockchain DNA
* Autonomous investigation
* Multi-agent collaboration
* Knowledge graph intelligence
* Causal analysis
* AI-assisted research
* Autonomous learning
* Adaptive heuristics

**Constraint on all of them.** A01 is **read-only by architecture**: it holds
no signing keys, constructs no transactions, and has no write path to any
chain. Any future capability that implies on-chain action is a new system
requiring its own threat model and human-in-the-loop authorisation, not an
incremental feature. See `docs/intelligence/threat-model.md` §3.2.

---

# 12. Capability Governance

Every capability must have:

* Clear purpose
* Defined inputs and outputs
* Responsible modules
* Version history
* Test coverage
* Documentation
* Performance metrics

**Added in v2.0.0** — every analytical capability must also have:

* A declared base rate for its output class
* An error-rate state: `measured`, `stated`, or `unmeasured`
* Enumerated false-positive sources
* A documented evasion surface
* A `falsified_by` condition — what observation would retract the conclusion

Capabilities failing governance review must not be promoted, and must not be
advertised in reports or APIs at a maturity above their measured state.

---

# 13. Capability Statement

A01 is a **capability-driven intelligence system**. Capabilities define what the
agent can accomplish; implementation modules define how those capabilities are
delivered. This separation ensures long-term maintainability and compatibility
across CIE-OS versions.

v2.0.0 adds a second commitment: **the catalog reports measured state, not
intent.** A capability listed here at a given maturity can be relied on at that
maturity by any consumer, human or agent. Maintaining that property is more
important than the list looking complete.

---

## Related Documents

* `docs/intelligence/attribution-doctrine.md` — what A01 may claim, and on what basis
* `docs/intelligence/evidence-standard.md` — the evidentiary bar and provenance contract
* `docs/intelligence/detection-catalog.md` — per-detector specifications
* `docs/intelligence/threat-model.md` — adversarial analysis, both classes
* `docs/intelligence/future-problems.md` — what will break, and when
* `docs/architecture/folder-architecture.md` — measured structure

---

**End of Capabilities Document**
