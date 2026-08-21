# PROJECT_STATE.md — CIE-OS A01 Blockchain Intelligence Agent

> Current snapshot. Overwritten each session. History lives in `BUILD_LOG.md`.

- **Last updated:** 2026-08-21
- **Repo root:** `F:\CIE-OS`
- **Agent root:** `F:\CIE-OS\agents\A01_Blockchain_Intelligence`
- **Interpreter:** `F:\CIE-OS\.venv\Scripts\python.exe`

## Verification basis

| Command | Result |
|---|---|
| `python -m pytest -q` | **1,827 passed**, 1 skipped, **0 failed** |
| `python -m cli doctor` | **14/14 `ok`**, schema **v8**, exit 0 |
| `python -m cli detectors` | **5** detectors, 4 `validated` and alerting, 1 `implemented` and muted |
| `python -m cli verify detectors` | **4/4 promotable**, zero FPR, perfect recall |
| `python -m cli skills` | **19** skills implemented |
| `python -m cli providers` | 21 endpoints, 9 usable, 12 dormant, **1 keyed active** (alchemy) |
| `python -m cli chains` | **15** chains registered, 13 observable, 13 token-capable |

## 2026-08-21 -- triage + reconciliation

Health re-verified against the code, not the doc: **1,792 passed, 1 skipped, 0
failed**; `cli doctor` 14/14; no TODO/FIXME debt; every `NotImplementedError`
is a provider seam or abstract base method (e.g. `BaseAgent.execute`), not a
gap. `pytest-asyncio 1.4.0` is now installed, which is why the suite is green.

Reconciled stale claims below to match the code: WARM/LEDGER tiers are built and
tested (were "schema only"), whale-label wiring and the exchange-flow detector
are done (were "decisions left").

**Fixed:** `memory/storage/sqlite.py::connect()` leaked its live connection when
called twice (a caller connecting the storage and then the repository wrapping
it hit this) — aiosqlite reported it deleted-before-closed at GC. `connect()` is
now idempotent. Guarded by `test_storage.py -W error::ResourceWarning`.

**Still open (operator's call):** DET-EXPLOIT-02 stays muted until a labelled
drain corpus exists — deliberately, not for lack of code: promoting it on
synthetic cases would make it fire on legitimate unlocks/migrations, so it is
held at `implemented` until real announcement data and 90 days of reserve
history exist.

## 2026-08-22 -- stablecoin flow normalised to dollars

Token/stablecoin attribution (decision #2 below) is closed. The rollup still
reads native value only, but the stablecoin skill now resolves decimals from a
curated table and reports flow as a summable face-dollar figure — which raw
base units never could.

- **`knowledge/stablecoins.py`:** curated `(chain, address) -> Stablecoin(symbol,
  decimals, peg)` for USDC/USDT/DAI/BUSD/USDP across 7 EVM chains. No `eth_call`;
  decimals fixed at deployment. Keyed by the registry's own slugs — fixing a
  latent bug where the old symbol list keyed BNB as `bnb` and the decimals
  resolver keyed it as `bsc`, neither of which a `bnb_chain` lookup ever hit.
  BNB-chain USDC/USDT are recorded at 18 decimals, not 6.
- **`skills/stablecoin/analysis.py`:** rewritten to normalise every stablecoin to
  its face-dollar quantity and sum across them; per-token and net USD figures,
  sorted by dollar throughput. Bounds state the figure is dollars *at par* —
  decimals resolved, but no price read, so a de-pegged coin is still counted at $1.
- **20 tests** (`knowledge/tests/test_stablecoins.py`,
  `skills/tests/test_stablecoin.py`): registry-slug keys, the BNB 18-decimal
  guard, decimals agreeing with `contracts.decimals.WELL_KNOWN`, and a USDC+DAI
  flow summing into one dollar total.

## 2026-08-21 -- approval-risk wired to stored data

The approval-risk decoder and exposure replay (39 tests, complete since the
security pass) are now reachable from stored data. Additive only — a new table
and a new read path, nothing existing changed.

- **migrations v8:** `approvals` table + indexes, keyed on
  `chain:tx_hash:log_index` and cascaded from `blocks`, so a replayed block is
  idempotent and a reorg withdrawal removes its grants with it. `CURRENT_VERSION`
  is derived, so doctor now reports schema v8.
- **`normalization/approvals.py`:** `normalize_approvals()` binds each decoded
  grant to its own block hash (sibling of `normalize_logs`). `contracts/events.py`
  still refuses approvals as non-transfers; this is the separate path that keeps
  them.
- **`database/approvals.py`:** `SqliteApprovalRepository` — FK-safe, idempotent
  writes; `approvals_for_owner()` hydrates back to `DecodedApproval` so the proven
  replay consumes them unchanged. Canonical reads only.
- **`database/writer.py`:** optional approval repository, off by default — a
  writer without one behaves exactly as before. **`cli approvals --db --address`**
  replays the stored log into `exposure_for_owner` and prints breadth plus the
  three things it cannot determine.
- **20 tests** across `database/tests/test_approvals.py` and
  `cli/tests/test_cli.py`: round-trip into the screen, revocation replay,
  idempotency, reorg withdrawal, opt-in capture, and the CLI's limits.

## 2026-08-20 -- security pass

Four workstreams, all complete. Suite 1,466 -> **1,679 passing, 0 failing**.

### 1. Security audit of the existing modules

`config/security` (1,117 lines) and `tools/security` (1,416) read line by
line. **16 defects, 8 reproduced against the shipped code before the fix.**
Full record: `agents/A01_Blockchain_Intelligence/docs/architecture/security-audit-2026-08-20.md`.

The four that mattered most:

| Defect | Effect |
|---|---|
| `SecretsManager` path traversal | `resolve("../../pyproject.toml")` returned 2,220 bytes from outside `secrets_dir` |
| `Rule()` defaulted to allow-everything | a rule dict missing its `permission` key authorized every principal for everything |
| No MAC on `encrypt_text` | one flipped ciphertext byte turned `admin=0` into `admin=9`, no error raised |
| `guard()` passed rules the mapping | a payload with a script tag and DROP TABLE cleared a "hard security gateway" untouched |

Also: token expiry raised `ModuleNotFoundError` and was never enforced;
`ApiKeyManager()` recursed until the stack ran out; the sandbox env scrub was
a denylist that missed `ALCHEMY_URL` and `DATABASE_URL`; `block_hosts` let
`169.254.169.254` through; `PermissionError` subclassed the builtin so
`except OSError` swallowed denials; `allow_all()` allowed nothing.

**67 regression tests** in `tools/security/tests/test_hardening.py` and
`config/tests/test_security_hardening.py`, each named for the defect it
guards.

### 2. DET-EXPLOIT-02 -- anomalous outflow

| | |
|---|---|
| Measurement | `blockchain/security/exploit_detection/outflow.py` -- pure, no I/O |
| Judgement | `intelligence/analysis/exploit.py` -- `ExploitAnalyzer` |
| Maturity | **`implemented`**, ceiling 0.60, **may not alert** |
| Tests | 50 |

Gate is the catalog's: `outflow_fraction >= 0.30` in `<= 3` blocks **and**
`z >= 6`. The z is read against the **modified** z-score (MAD / 0.6745, with a
mean-absolute-deviation fallback), because the classical one is self-defeating
here -- measured, one prior drain in the baseline costs it 11.8x of its
separation against 4.1x for the robust estimator. Calibration: **0 false
positives on 1,998 simulated ordinary windows**, injected drain caught.

Deliberately **not** promoted. There is no labelled corpus of protocol drains,
so the error rate is `unmeasured`, and section 7.3 bars an unmeasured detector
from alerting. It is the first detector in the registry to sit below the
ceiling since promotion, which is a useful demonstration that the gate does
something.

### 3. Approval risk screening

| | |
|---|---|
| Decoder | `blockchain/security/approval_risk/approvals.py` -- ERC-20, ERC-721, `ApprovalForAll` |
| Exposure | `blockchain/security/approval_risk/exposure.py` -- replay to the live grant set |
| Tests | 39 |

`contracts/signatures.py` sent `ApprovalForAll` here by name; this is the
consumer that note pointed at. Three traps handled explicitly: ERC-20
`Approval` and `ApprovalForAll` share a layout and differ only by `topic0`;
each standard revokes differently; and the three key a grant differently --
ERC-20 by spender, ERC-721 by token id (approve *replaces*), `ApprovalForAll`
by operator.

**Complete and not reachable from stored data.** There is no approvals table
and `contracts/events.py` refuses approval logs as non-transfers, so nothing
feeds it. The decoder had to exist before capturing the logs was worth doing;
wiring it needs a migration, which is the operator's call. *(Wired 2026-08-21 —
see "approval-risk wired to stored data" above; schema v8.)*

### 4. The eight pointer directories now hold code

`api/`, `monitoring/`, `models/`, `plugins/`, `reasoning/`, `reporting/`,
`security/`, `workflows/` are **redirect packages**: each binds the canonical
module object itself and forwards every other name to it live through
`__getattr__`. `api.rest is interfaces.rest` -- identity, so drift is
impossible by construction rather than by instruction.

`security/` is the exception that proves it: it binds `config.security` and
`tools.security` under `configuration` and `runtime` and refuses to merge
them, because both define a secret wrapper with different hardening and a
merged `security.Secret` would hide the choice.

`sandbox/` stays empty. There is nothing to redirect it to, and code placed
there ships by accident. **56 tests** in `tools/tests/test_redirects.py`.

### Also fixed along the way

- **The venv was broken.** `pyvenv.cfg` pointed at another machine's user
  (`C:/Users/thaha/AppData/Roaming/uv/python/...`), which does not exist here.
  Repointed at the local CPython 3.14.7; backup at `.venv/pyvenv.cfg.bak`.
- `interfaces/service.py` told API callers "None has a measured error rate, so
  none alerts" -- false since the four promotions. Now derived.
- `cli detectors` said "Confidence ceiling is 1.0" unconditionally. Now
  derived, and reports what is muted.
- Three tests asserted the *snapshot* "all detectors are validated" rather
  than the invariant. Rewritten to assert that a detector reaches `validated`
  only if a backtest put it there, and that anything below it names its
  blocker.
- The `blockchain/security/*` placement note blamed "event decoding beyond
  transfers", which `contracts/` has done since the contracts layer landed.
  Corrected to the real blocker: bytecode analysis and an ABI source.

---

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
| WARM | 90 days | hourly aggregates (the anomaly baseline) | built + tested (`tiers/warm.py`) |
| LEDGER | forever | entities, track records, labels | built + tested (`tiers/ledger.py`) |

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

### Decisions — status reconciled 2026-08-21

1. **Whale skill labels.** ✅ **DONE.** `skills/whale_detection/transfers.py`
   reads the label ledger (`LabelRepository`/`LabelSet`); `counterparty_type`
   now answers from a sourced claim, `unlabelled` when the list is empty.
2. **Token transfer attribution.** ✅ **DONE (2026-08-22).** Stablecoin flow is
   now normalised to dollars via `knowledge/stablecoins.py` (curated decimals).
   The rollup (`tiers/hot.py`, `tiers/warm.py`) still reads native value only;
   attribution lives in the stablecoin skill, which is where a value with a
   resolved exponent belongs. See "stablecoin flow normalised to dollars" above.
3. **Exchange flow detector.** ✅ **DONE.** `DET-EXCHANGE-01` (exchange_flow)
   is validated and alerting.

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
