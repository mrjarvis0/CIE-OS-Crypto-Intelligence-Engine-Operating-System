# CIE-OS / A01 Blockchain Intelligence Agent — Agent Instructions

## Project Overview
**A01** is a blockchain intelligence agent with a strict **13-layer architecture** (Identity → Interfaces). Currently ~30% implemented — configuration, memory, tools/adapters, and planning are substantial; intelligence engines, skills, data pipeline, and API server are mostly scaffolded/empty.

**Root:** `F:\CIE-OS (crypto intelligence engine-opreting system\`
**Agent code:** `agents/A01_Blockchain_Intelligence/`

---

## Key Commands

### Test (no pytest config — run modules directly)
```bash
# Adapter tests (root)
python tests/test_adapters.py

# Planning engine (352 assertions, complete suite)
python agents/A01_Blockchain_Intelligence/planning/tests/test_core.py
python agents/A01_Blockchain_Intelligence/planning/tests/test_goals.py
python agents/A01_Blockchain_Intelligence/planning/tests/test_tasks.py
python agents/A01_Blockchain_Intelligence/planning/tests/test_routing.py
python agents/A01_Blockchain_Intelligence/planning/tests/test_execution.py
python agents/A01_Blockchain_Intelligence/planning/tests/test_reasoning.py
python agents/A01_Blockchain_Intelligence/planning/tests/test_monitoring.py
python agents/A01_Blockchain_Intelligence/planning/tests/test_utils.py
python agents/A01_Blockchain_Intelligence/planning/tests/test_schemas.py

# Blockchain transport tests
python agents/A01_Blockchain_Intelligence/blockchain/tests/test_transport.py
python agents/A01_Blockchain_Intelligence/blockchain/tests/test_providers.py
python agents/A01_Blockchain_Intelligence/blockchain/tests/test_reorg.py

# CLI (working)
python -m agents.A01_Blockchain_Intelligence.cli doctor
python -m agents/A01_Blockchain_Intelligence.cli investigate --address 0x123...
python -m agents/A01_Blockchain_Intelligence.cli detectors
```

### No build/lint/typecheck configured
- No `pyproject.toml`, `ruff`, `mypy`, `black`, `pytest.ini`
- Dependencies in `requirements.txt` (Pydantic v2, aiosqlite, asyncpg, redis)

---

## Architecture (Must-Know)

### 13-Layer Dependency Order (enforced)
```
Identity → Configuration → Core → Memory → Sensors → Ingestion → Validation
→ Normalization → Database → Skills → Intelligence → Decision → Interfaces
```
**Rule:** Code in layer N may only import from layers < N. Violations break architecture.

### Package Layout (502 files, ~93k lines)
| Package | Status | Notes |
|---------|--------|-------|
| `config/` | ✅ Complete | Pydantic v2 settings, 9-chain RPC registry, feature flags |
| `core/` | ⚠️ Partial | `agent.py`=2,338 lines (needs split), duplicate `AgentRuntime` class |
| `memory/` | ✅ Substantial | Short/long-term, vector (Chroma), SQLite/PostgreSQL/Redis backends |
| `tools/` | ✅ Substantial | 155 files: REST, RPC, WS, MCP, gRPC, CLI, Docker adapters — all tested |
| `planning/` | ✅ Complete | Goals, tasks, routing, execution, reasoning — full test coverage |
| `intelligence/` | 🟦 Scaffold | 146 files, 69 lines/file avg — only 2 analyzers (whale, dormant) |
| `skills/` | ❌ Empty | 18 skill dirs created, zero implementation |
| `sensors/`, `ingestion/`, `validation/`, `normalization/`, `database/` | ❌ Empty | No data pipeline yet |
| `blockchain/` | 🟦 Scaffold | Full domain structure, minimal implementation |
| `api/`, `cli/`, `monitoring/`, `security/`, `evaluation/`, `reasoning/`, `reporting/`, `knowledge/`, `prompts/`, `workflows/` | ❌ Empty | Delete duplicate dirs at `A01_Blockchain_Intelligence/{api,cli,monitoring,security,blockchain}` |

### Entry Points
- **CLI:** `agents/A01_Blockchain_Intelligence/cli/main.py` → `investigate`, `detectors`, `doctor`
- **No API server** — `api/` is empty
- **Runtime:** `core/runtime.py` (AgentRuntime), `core/agent.py` (BaseAgent), `core/lifecycle.py` (FSM)

---

## What's Done vs Missing

### ✅ Working
- Configuration (env-driven, secret-safe, multi-env)
- RPC management (9 chains, fallback, health, rate limiting)
- Memory system (multi-backend, vector search)
- All adapter transports (tested)
- Planning engine (complete + tested)
- CLI commands

### ❌ Critical Gaps (block "runnable agent")
1. **No data pipeline** — sensors → ingestion → validation → normalization → database all empty
2. **No skills implemented** — 18 dirs, zero code
3. **Intelligence engines scaffolded** — only behavior/anomaly/risk engines have partial code; 2 analyzers total
4. **No API server** — cannot serve requests
5. **No evaluation framework** — cannot validate detector maturity
6. **Core structural debt** — `agent.py` too large, duplicate `AgentRuntime`

---

## Development Workflow (Per Architecture Docs)

Follow **vertical slice** build order (`agents/A01_Blockchain_Intelligence/README.md`):
1. ✅ Identity → Config → Knowledge → Core (mostly done)
2. 🔄 **ONE sensor** → ingestion (dedup + reorg handling) → normalization → database
3. **ONE skill** → full pipeline validation
4. Expand to remaining chains/skills/intelligence engines

### Key Files to Reference
- Architecture: `agents/A01_Blockchain_Intelligence/docs/architecture/layered-architecture.md`
- Data flow: `agents/A01_Blockchain_Intelligence/docs/architecture/data-flow.md`
- Component specs: each subpackage has `README.md` with design spec
- Intelligence: `agents/A01_Blockchain_Intelligence/docs/intelligence/evidence-standard.md`, `detection-catalog.md`

---

## Gotchas

- **No CI/CD, no lint, no typecheck** — verify manually
- **Optional deps guarded** — Chroma, gRPC, msgpack, YAML, OpenTelemetry imported conditionally
- **SQLite DB at** `data/long_term_global.db` (created at runtime)
- **Empty `.env`** — copy `.env.example` if it exists, or set `A01_*` vars manually
- **Duplicate top-level dirs** — delete `agents/A01_Blockchain_Intelligence/{api,cli,monitoring,security,blockchain}` (empty, shadow real packages)
- **Import style** — absolute from `agents.A01_Blockchain_Intelligence.*`; relative within package
- **Async-first** — all I/O is async; sync helpers marked explicitly

---

## References
- Identity docs: `agents/A01_Blockchain_Intelligence/docs/identity/*.md`
- Architecture docs: `agents/A01_Blockchain_Intelligence/docs/architecture/*.md`
- Intelligence docs: `agents/A01_Blockchain_Intelligence/docs/intelligence/*.md`

---

# CIE-OS / A02 News Intelligence Agent

**A02** is the fake-news/rumor intelligence agent (stocks, crypto, forex). Built in 15 phases under a **minimal structure** (config/, core/, intelligence/, models/, data/, cli/) — deliberately small vs A01's 40 folders.

**Root:** `agents/A02_News_Intelligence/`

## Key Commands
```bash
# Doctor (validate foundation) / live ingestion + narrative cycle / narratives view / market impact
python -m agents.A02_News_Intelligence.cli doctor
python -m agents.A02_News_Intelligence.cli scan
python -m agents.A02_News_Intelligence.cli narratives
python -m agents.A02_News_Intelligence.cli impact <narrative_id>
python -m agents.A02_News_Intelligence.cli resolve --all   # learning loop: resolve predictions vs live price
python -m agents.A02_News_Intelligence.cli metrics         # accuracy, Brier, calibration, drift
python -m agents.A02_News_Intelligence.cli backtest        # replay resolved predictions
python -m agents.A02_News_Intelligence.cli output <id>     # flagship 12-point report

# Offline tests
python agents/A02_News_Intelligence/tests/test_core.py       # Phase 1 (38 assertions)
python agents/A02_News_Intelligence/tests/test_narrative.py  # Phase 2 (33 assertions)
python agents/A02_News_Intelligence/tests/test_verification.py  # Phase 3 (28 assertions)
python agents/A02_News_Intelligence/tests/test_impact.py     # Phase 4 (34 assertions)
python agents/A02_News_Intelligence/tests/test_learning.py   # Phase 5 (35 assertions)
python agents/A02_News_Intelligence/tests/test_phase6.py     # Phase 6 (31 assertions)
python agents/A02_News_Intelligence/tests/test_phase7.py     # Phase 7 (13 assertions)
```

## Phase Plan (current)
- Phase 0 ✅ Foundation (config, paths, sources registry, CLI stub, doctor OK)
- Phase 1 ✅ Ingestion vertical slice: RSS (keyless) + Tiingo/NewsAPI (keyed) connectors, normalization, dedup (url/title/content fp), rule-based entity extraction, SQLite storage (`data/processed/a02.db`) — `scan` command live-tested (137 items, dedup verified)
- Phase 2 ✅ Narrative intelligence: claim extraction (entity sentence + time hints), clustering (title-jaccard + entity overlap; no-shared-entity titles penalized 0.5x to stop pattern-headline false merges), stance (support/deny/neutral/question), propagation (mention/source/platform counts, velocity), FOMO score (velocity/sources/platforms/urgency) + lifecycle status (emerging→spreading→peak_hype→verifying→resolved). `narratives` command live-tested.
- Phase 3 ✅ Verification + manipulation: credibility tiers (official 1 → anonymous 6 by domain + source), source-level dedup for confirmations (identical content fp = 1 underlying source), epistemic status 7-tier verdict + confidence 0-1 (denies outrank confirms; official deny = confirmed_false; satire markers = fabricated), coordination score 0-100 (identical text, timing burst, author/platform concentration) — separate from FOMO & truth. DB auto-migrates new columns.
- Phase 4 ✅ Market impact + prediction: Binance klines (keyless crypto) + Alpha Vantage (keyed) price data, event-study returns (1h/6h/24h) + volatility + volume surge, category classification (etf/hack/delisting/regulatory/fraud/earnings/partnership/macro), historical correlation engine (similar past events → expected range + confidence), prediction = measured move + historical analog + verification → direction/probability/range/risk. `impact <id>` command live-tested with real BTC data (learning loop: each query stores an impact event).
- Phase 5 ✅ Learning + backtest: prediction snapshot stored per impact (direction/probability/mean), `resolve` captures realized outcome vs live price, `metrics` computes accuracy + multi-class Brier + calibration bins (overconfident flagged) + verification truth agreement + scan drift snapshots, `backtest` replays resolved events vs naive baseline, `output <id>` = flagship 12-point consumer report (claim → next signal). All 5 suites green (168 assertions).
- Phase 6 ✅ ML models + extended categories + new connectors: sklearn TF-IDF+LogReg classifiers for category/stance/verification with rule fallback (models/ml_models.py); 21 impact categories including product_launch, executive_change, merger_acquisition, guidance_change, dividend, stock_split, bankruptcy, clinical_trial, patent, contract_win, investigation, sanctions; Telegram (bot API) and X/Twitter (API v2) connectors; ML verification signal integrated into verdict; source tiers for new connectors. All 6 suites green (199 assertions).
- Phase 7 ✅ Reddit connector + transformer fake detector + multi-asset correlation + retraining: Reddit public API connector; Hugging Face transformer pipeline with rule fallback; cross-asset Pearson correlation + prediction propagation; export/retrain utilities for ML models. All 7 suites green (212 assertions). A02 phase plan complete (7/7).
- Phase 8+ (optional stretch): Reddit OAuth for private subreddits, fine-tuned FinFakeBERT, multi-horizon impact modeling, portfolio-level risk integration

## A02 Gotchas
- **Env prefix `A02_`** — read from repo-root `.env`; all keys optional (degraded mode)
- **Minimal structure rule** — do NOT expand folders like A01; add files only when a phase needs them
- **No binary FAKE/REAL output** — epistemic status + confidence + impact range + uncertainty
- **FOMO ≠ Truth ≠ Coordination** — three separate scores
- Source-level dedup mandatory: 10 articles copying 1 tweet = 1 underlying source, not 10 confirmations
- Python 3.14, pydantic 2.13; async-first I/O