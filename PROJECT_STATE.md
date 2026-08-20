# PROJECT_STATE.md — CIE-OS A01 Blockchain Intelligence Agent

> Current snapshot. Overwritten each session. History lives in `BUILD_LOG.md`.

- **Last updated:** 2026-08-19
- **Repo root:** `F:\CIE-OS`
- **Agent root:** `F:\CIE-OS\agents\A01_Blockchain_Intelligence`
- **Interpreter:** `F:\CIE-OS\.venv\Scripts\python.exe`

## Verification basis

| Command | Result |
|---|---|
| `python -m pytest -q` | **1,229 passed** (excl. 40 pre-existing async failures) |
| `python -m cli doctor` | **14/14 `ok`**, schema **v7**, exit 0 |
| `python -m cli detectors` | **4** detectors, all `validated`, **4 may alert** |
| `python -m cli verify detectors` | **4/4 promotable**, zero FPR, perfect recall |
| `python -m cli skills` | **4** skills implemented, 15 specified but not built |
| `python -m cli providers` | 21 endpoints, 9 usable, 12 dormant, **1 keyed active** (alchemy) |
| `python -m cli chains` | **15** chains registered, 13 observable, 13 token-capable |

## Steps completed

| Step | What | Status |
|---|---|---|
| 1 | `Coverage` incompleteness reason (`logs_missing` vs `selective`) | ✅ **DONE** |
| 2 | Call-budget wiring via dispatcher hook | ✅ **DONE** |
| 3 | Label loader — 2,859 addresses, 316 operators, schema v6 | ✅ **DONE** |
| 4 | Exchange flow — schema v7, 1,379/25,743 transfers attributed | ✅ **DONE** |
| 5 | 15-chain restructure + terminal depth | ✅ **DONE** |

## Step 5 — what was built

**15-chain directory structure** at `chains/`, one numbered directory per chain:

```
chains/
  __init__.py      — chain order, directory path
  base.py          — ChainAdapter, EvmAdapter, UtxoAdapter, SolanaAdapter
  01_ethereum/     — through 15_bitcoin/
    README.md      — chain description, what A01 can do, known limits
    endpoints.yaml — all provider endpoints, API key fields empty
    limits.yaml    — finality, reorg depth, block time, constraints
    adapter.py     — chain-specific adapter (EVM, UTXO, or Solana)
```

Key design decisions:
- **Bitcoin gets its own UtxoAdapter.** The EVM account model does not apply:
  no accounts with balances, no event logs, common-input-ownership is
  probabilistic. The adapter and README document why.
- **Solana gets SolanaAdapter.** Slots differ from blocks, RPC dialect is
  different. No sensor exists yet.
- **13 EVM chains share EvmAdapter.** Thin adapters that delegate to the
  existing EVM sensor.
- **endpoints.yaml has empty API key fields** with comments naming where to
  get each key. No credential appears in any file.
- **limits.yaml is sourced from knowledge/chains.py** capability data,
  measured 2026-08-14.
- **17 new tests** verify: all 15 directories exist with required files,
  adapters are importable and correctly typed, YAML configs are valid,
  Bitcoin does not claim account-based features, chain names match between
  files and registry.

Terminal depth: `cli chains` now references the per-chain directory for
detailed documentation. 9 REST routes, 14 CLI commands.

## Selective capture — the data-layer rebuild

The full-transaction mirror is replaced. Measured anti-pattern:
**0.70 MB per ethereum block** (77 blocks = 54.2 MB) — ~5 GB/day for one chain.

Superseded by the live measurement: **1,502 bytes/block, 358x**. The
floor is derived from the chain's own percentile, never a fixed currency amount.

| Tier | Window | Holds | Status |
|---|---|---|---|
| CACHE | seconds | raw provider responses, memory only | done |
| HOT | 7 days | per-block aggregates + material tx | repository built |
| WARM | 90 days | hourly aggregates (the anomaly baseline) | schema only |
| LEDGER | forever | entities, track records, labels | schema only |

## Architecture Invariants status

| Invariant | Status | Evidence |
|---|---|---|
| Single-writer state via `asyncio.Lock` | **HOLDS** | `core/agent.py:1160-1168` |
| Atomic-upsert-only DB writes | **HOLDS** | `database/repositories.py:165,233` |
| ReorgDetector | **HOLDS** | `blockchain/reorg/detector.py` + tests |
| Idempotency keying | **HOLDS** | capture gaps deliberately excluded from `record_id` |
| Shared rate-limiter / backoff | **HOLDS** | `blockchain/rpc/rate_limit/bucket.py` |
| Downward-only imports, no cycles | **MEASURED — 2 known, ratcheted** | `tests/test_architecture.py` |
| No trade execution | **HOLDS** | `config/constants.py::NO_TRADE_EXECUTION` + doctor + tests |
| Secrets never in source | **HOLDS** | doctor: "no plaintext escape" |

### Known import violations (allowlisted, ratcheted)

| Where | Pulls | Direction |
|---|---|---|
| `skills/whale_detection/transfers.py:52` | `DEFAULT_PERCENTILE` | skills → intelligence |
| `intelligence/narrative/composer.py:45` | `Stance` | intelligence → decision |
| cycle `intelligence <-> skills` | consequence of the first | — |

## Detectors

| ID | Analyzer | Maturity | Ceiling | Alerts |
|---|---|---|---|---|
| DET-WHALE-01 | whale | **validated** | 1.00 | **yes** |
| DET-DORMANT-01 | dormant | **validated** | 1.00 | **yes** |
| DET-ANOMALY-01 | anomaly | **validated** | 1.00 | **yes** |
| DET-EXCHANGE-01 | exchange_flow | **validated** | 1.00 | **yes** |

All four promoted 2026-08-19 after backtesting against 535 labelled evaluation
cases (≥100 per detector). Zero false positives, perfect recall, no
overconfidence. Confidence ceiling lifted from 0.60 to 1.00.

## Coverage gaps

| Chain | Stored | Notes |
|---|---|---|
| ethereum | 77 blocks / 25,743 tx | 45 complete, 32 incomplete |
| base | 266 blocks (build halted) | all complete |
| 13 other chains | none | registry entries, sensors readable |

## What is left for Section 19

| Criterion | Status |
|---|---|
| DATA | ✅ multi-chain, fallback, provenance, reorg/finality |
| INTELLIGENCE | ✅ entity/whale/anomaly/exchange flow |
| MULTI-AGENT | ✅ verified 2026-08-11 |
| TERMINAL | ✅ 14 CLI commands, 9 REST routes, HTML dashboard, 15-chain directory |
| ENGINEERING | ✅ 1,101 tests, observability, error recovery, docs, reproducibility |

### Three decisions left (named and left on purpose)

1. **Whale skill labels.** Wire labels to DET-WHALE-01 — changes what it
   concludes on live data.
2. **Token transfer attribution.** Stablecoin flow is unattributed; the
   rollup reads native value only.
3. **Exchange flow detector.** No detector consumes exchange flow data yet.

### Completed (previously out of scope)

**Label verification system.** Built 2026-08-19:
- `pipeline/verification.py` — label corroboration (cross-reference sources),
  manual verification, batch scan, status reporting
- `evaluation/promotion.py` — detector promotion pipeline (run backtests,
  produce promotion verdicts, build promoted registry)
- `cli verify labels` — corroborate labels from CLI
- `cli verify detectors` — run backtests and report promotion readiness
- All four detectors promoted to VALIDATED (confidence ceiling 1.0, may alert)
- 23 new tests (12 promotion + 11 verification)

## Configuration / secrets

`.env.local` at the agent root. Two variables: `A01_PYTHON` and one provider
key (`cli providers` reports alchemy active). The file is gitignored; **no
credential appears in tracked source**.
