# A01 Blockchain Intelligence Agent

**Project:** CIE-OS (Crypto Intelligence Engine Operating System)
**Status:** Core pipeline complete — all 16 analyzers, 19 skills, full scoring engine

---

## 1. Master Structure

```
A01_Blockchain_Intelligence/
│
├── identity/         Mission, scope, principles, constraints
├── config/           Configuration, chains, RPC registry, secrets
├── knowledge/        Knowledge graph, scope, glossary, chain knowledge
├── core/             Runtime foundation — orchestrator, lifecycle, context
│
├── sensors/          Data source clients (RPC, WS, explorers, third-party)
├── ingestion/        Data collection orchestration — timing, streams, backfill
├── normalization/    Canonical blockchain data — dedup, validation
├── schemas/          Canonical data models (chain, block, tx, entity...)
├── database/         Permanent system of record — repositories, atomic upserts
├── memory/           Persistence, retrieval, vector store, summarisation
│
├── contracts/        ABI, events, decoders, selectors, signatures
├── skills/           Capability layer — one skill = one responsibility
├── intelligence/     Higher-order engines combining skills into intelligence
├── decision/         Scoring, evidence, confidence, alerts
│
├── interfaces/       API / WebSocket / CLI / dashboard / exports
├── models/           LLM, prompts, rules, embeddings, templates (cross-cutting)
├── plugins/          Multi-chain and third-party plugin system
├── telemetry/        Metrics, logs, traces, health
├── security/         Permissions, secrets, audit, validation, sandbox
│
├── fixtures/         Replay / mock / test data
├── examples/         Usage examples and end-to-end walkthroughs
├── assets/           Static assets (icons, diagrams, brand)
├── tests/            Agent-level test suite (unit, integration, benchmark)
├── docs/             Architecture and tradecraft documentation
├── tools/            Developer and validation tooling (validators, generators)
└── sandbox/          Experimental area — never shipped, never imported
```

## 2. Pipeline (mandatory dependency direction)

```
knowledge → identity/config → core → sensors → ingestion → normalization
        → database → memory → skills → intelligence → decision → interfaces
```

`models/` and `security/` are **cross-cutting** — every layer may use them;
nothing may depend on a higher pipeline stage.

## 3. Layer Responsibilities

| Layer | Decides | Must not |
| --- | --- | --- |
| `sensors/` + `ingestion/` + `normalization/` + `database/` | **How data is captured and stored** | Interpret meaning |
| `skills/` | **What one capability can do** | Combine capabilities |
| `intelligence/` | **What the data means** (combines skills) | Fetch data or choose objectives |
| `decision/` | **What to conclude / alert** | Interpret data |
| `interfaces/` | **How to expose results** | Decide or interpret |

**Rule:** a `sensors/` module that scores risk, or an `intelligence/` module
that opens a socket, is an architectural violation. Sub-package names must not
duplicate across levels — the layer-level implementation wins.

## 4. Build Order (Vertical Slices)

Per the architecture doctrine, do **not** scaffold every folder with code.
Build one vertical slice end-to-end, then repeat:

```
1. identity → 2. config → 3. knowledge → 4. core
5. ONE sensor → 6. ingestion (dedup + reorg) → 7. normalization → 8. database
9. ONE skill → 10. full pipeline validation
11. next sensor → 12. next skill → 13. intelligence engine
14. decision → 15. interfaces
```

## 5. Structure Status (v1)

| Folder | Status |
| --- | --- |
| `identity/`, `docs/` | Documented — 48 files, foundation and tradecraft complete |
| `memory/`, `tools/`, `planning/` | Implemented — the three largest packages |
| `config/`, `core/` | Implemented (some structural debt; `core/agent.py` incomplete) |
| `cli/`, `evaluation/`, `prompts/` | Implemented — entry point, backtest harness, injection defence |
| `intelligence/` | Complete — 16 analyzers (4 primary + 12 supplementary), scoring engine, correlation, graph analysis |
| `blockchain/` | RPC dispatch, provider catalog, and reorg tracking — consumed by `sensors/` and `ingestion/` |
| `sensors/` | Implemented — EVM JSON-RPC capture for 7 chains, provenance attached at read |
| `ingestion/` | Implemented — reorg-safe head polling, checkpoints, dedup, bounded queue, backfill |
| `schemas/` | Implemented — canonical block/transaction/token/NFT, exact 256-bit amounts, folded addresses |
| `contracts/` | Implemented — ERC-20 and ERC-721 event decoding, discriminated by log shape |
| `normalization/` | Implemented — validation that refuses, quality checks that annotate |
| `database/` | Implemented — SQLite system of record, atomic idempotent writes, soft withdrawal |
| `skills/` | 19 of 19 implemented — all skills built with LIMITED readiness where data sources are pending |
| `intelligence/engines/` | Implemented — skill composition feeding the detectors from storage |
| `decision/` | Implemented — maturity gate, confidence vocabulary, alert budgets, recommendations |
| `interfaces/` | Implemented — service facade plus a read-only loopback REST API |
| `intelligence/narrative/` | Implemented — deterministic composer, grounding check, model seam |
| `telemetry/` | Implemented — metrics with bounded cardinality, verified backup and restore |
| `fixtures/`, `tests/` | Implemented — recorded mainnet replay, integration, regression, performance, security |
| `knowledge/` | Implemented — what A01 can and cannot learn per chain, measured and re-measurable |
| `examples/` | Implemented — four offline walkthroughs, run by the test suite |
| `assets/` | Implemented — self-contained pipeline diagram |
| `api/`, `models/`, `monitoring/`, `plugins/`, `reasoning/`, `reporting/`, `security/`, `workflows/` | Pointers — each names the package that actually implements it |
| `sandbox/` | Deliberately empty; never shipped, never imported |

> **No directory is empty.** Each one without code carries a generated README
> naming either the package that implements the concept or the capability its
> implementation waits on. The pointers come from one table in
> `tools/placement.py`, and a test asserts every target still exists — so a
> rename fails the suite instead of stranding 140 readers. Regenerate with
> `python -m tools.placement --write`.

**All thirteen roadmap phases are built**, and the token layer on top of them.
`blockchain/rpc` → `sensors/` → `ingestion/` → `normalization/` → `database/` →
`skills/` → `intelligence/` → `decision/` → `interfaces/` runs end to end
against seven live EVM chains, with an AI layer that cannot fabricate,
telemetry that reports honesty as well as throughput, and verified backup and
restore.

**Tokens are why this matters on layer 2.** Measured on live Arbitrum blocks,
the largest *native* transfer was `0.0000` — every real movement was an ERC-20
transfer in an event log. Three Ethereum blocks carry 1,067 native transactions
and **1,594 token transfers**. Without `contracts/` decoding those logs, A01
saw almost nothing on an L2 and roughly half of Ethereum.

**A01 raises no alerts, deliberately.** Alerting requires `validated` maturity,
which requires a measured error rate from `evaluation/`. Neither detector has
one, so `decision.MaturityGate` suppresses every alert and says why. The gate
has no override parameter — one that can be bypassed per call is documentation,
not a gate.

**What bounds it now**, each stated in the output rather than left to be
discovered:

* **No measured error rate.** The highest-leverage gap by a distance. Every
  conclusion is capped at 0.60 confidence and no alert can fire until
  `evaluation/` runs against a labelled window. The harness exists; the labelled
  data does not.
* **Coverage.** A shallow database cannot support a negative claim. Below 3,600
  contiguous blocks a negative degrades to `undetermined`, which is a different
  claim and the true one.
* **Token decimals unresolved.** ERC-20 and ERC-721 transfers are now decoded
  and stored, but a token's exponent lives in its `decimals()`, reachable only
  by `eth_call`. Amounts are therefore raw base units, comparable **within one
  token** and never across tokens. Assuming 18 would render a 140 USDC transfer
  as 140 trillion, and it would look ordinary.
* **Missing sensors.** No balance state and no price feed — so materiality and
  USD floors are unavailable. `python -m cli skills` lists what each blocks.
* **Labels are an external claim.** Exchange direction is now available, from an
  address list loaded with `a01 labels --load`. It is somebody else's assertion
  about an address, so every label stores its source and confidence and every
  flow figure inherits them. An unverified community list is evidence of care,
  not of correctness, and no exchange list is complete — an address it does not
  name is invisible to the flow figures rather than counted as unrelated.
* **Bounded aggregates.** Address totals are summed over at most 50,000 rows and
  reported as floors (`totals_are_floors`); the unbounded version was measured
  at 428ms per 100,000 transfers and grows forever.

Operations are documented in
[docs/architecture/deployment-runbook.md](docs/architecture/deployment-runbook.md).

## 6. Running

### On Windows, the short way

```
scripts\a01.bat
```

Double-clickable. It resolves the interpreter, self-checks, captures recent
blocks with tokens, and reports what A01 holds. It **refuses to ingest if
`doctor` fails**, because capturing into a system that fails its own checks
stores data nobody should trust.

For a recurring background capture:

```
powershell -ExecutionPolicy Bypass -File scripts\install-task.ps1
```

Every 10 minutes by default, logging to `logs/ingest.log` with rotation at
5 MB. Runs only while you are logged on — running regardless needs stored
credentials, which a read-only agent should not ask for. Remove it with
`scripts\uninstall-task.ps1`; that leaves the database alone.

### Configuration and API keys

Put a `.env.local` (or `.env`) beside the agent, or up to three directories
above it:

```ini
# Interpreter used by the launcher and the scheduled task.
A01_PYTHON=C:\path\to\.venv\Scripts\python.exe

# Provider keys. Uncomment to activate — see `python -m cli providers`.
# ALCHEMY_API_KEY=...
# ETHERSCAN_API_KEY=...
```

**This file is loaded into the process environment at startup**, which is where
provider keys are read from. An exported variable always wins over the file, so
a stale checked-out `.env` cannot defeat a deliberate export. Values are never
logged — only variable names.

```bash
python -m cli providers      # which providers are usable, keyed, or dormant
```

### Running the CLI directly

The interpreter must be the one with `pydantic-settings` and `aiosqlite`. The
system Python usually is not, and the symptom is a `settings load` failure that
looks like a broken agent rather than a wrong PATH:

```bash
"F:/CIE-OS (crypto intelligence engine-opreting system/.venv/Scripts/python.exe" -m cli doctor
```

Shortest path from nothing to an investigation:

```bash
python -m cli ingest --db a01.db --blocks 50 --tokens && python -m cli investigate --db a01.db --address 0x…
```

| Command | Purpose |
| --- | --- |
| `scripts\a01.bat` | **Windows one-click**: check, capture, report |
| `python -m cli doctor` | Self-check every subsystem — 13 checks |
| `python -m cli providers` | Which providers are usable, keyed, or dormant, and the variable each needs |
| `python -m cli ingest --db a01.db --blocks 50 --tokens` | **Capture live chain data into storage.** Bounded and resumable; start here. `--tokens` adds ERC-20/721 transfers |
| `python -m cli labels --db a01.db --load data/labels` | **Load address labels** from a CSV, TSV, JSON or text list. Without them no transfer can be attributed to an exchange. Re-running is free |
| `python -m cli flows --db a01.db --chain ethereum` | Exchange deposits and withdrawals per operator; `--rollup` persists the hourly rows a baseline is later measured against |
| `python -m cli skills` | List skills, their readiness, and what each missing data source blocks |
| `python -m cli detectors` | List detectors, their confidence ceiling, and whether they may alert |
| `python -m cli serve --db a01.db` | Run the read-only REST API on 127.0.0.1:8801 |
| `python -m cli metrics --db a01.db` | Print metrics in Prometheus text format |
| `python -m cli backup --db a01.db` | Take a verified snapshot (never use `cp` on a WAL database) |
| `python -m cli restore --backup snap.db --db a01.db --overwrite` | Restore; the incumbent is moved aside, not deleted |
| `python -m cli investigate --db a01.db --address 0x…` | Compose the subject from stored history and investigate |
| `python -m cli investigate --address 0x… --subject file.json` | Investigate a hand-supplied subject |
| `python -m pytest -q` | 782 tests, config in `pytest.ini` |

Dependencies are declared in `pyproject.toml`. Install with:

```bash
pip install ".[dev]"        # core + dev tools
pip install ".[all,dev]"    # everything including postgres, redis, chromadb
```
