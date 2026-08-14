# BUILD_LOG.md — CIE-OS A01 Blockchain Intelligence Agent

> Append-only history. Never overwritten. Current snapshot lives in
> `PROJECT_STATE.md`.

---

## Session 2026-08-11

### Goal for this session

1. Establish the Section 4 continuity system, which did not exist.
2. Run the mandatory Section 3 codebase audit and produce a Reuse Map backed by
   executed commands rather than assumption.
3. Migrate `F:\Agents\.env.local` into the CIE-OS tree.

### Audit findings (delta from last session)

No previous session recorded — `PROJECT_STATE.md` and `BUILD_LOG.md` were both
absent. This is session zero **for the continuity system only**; the codebase
itself is substantial and largely working (692 Python files, ~128,614 LOC).

Findings established by execution:

- `python -m pytest -q` at the agent root: **831 passed, 0 failed**, 45.28s.
  Two `ResourceWarning`s from `aiosqlite` in `memory/storage/tests/test_storage.py`
  (connections deleted before close). Not failures; not fixed this session.
- `python -m cli doctor`: 13/13 checks `ok`, exit 0.
- `python -m cli metrics`: ethereum has 45 blocks and 14,457 transactions
  stored, 0 withdrawn by reorg.
- `python -m cli providers`: 21 endpoints configured, 8 usable, 13 dormant.
  **0 keyed providers active.**

Priority Stack position: **Tier 0 is `DONE` for ethereum** (verified, not
assumed). **Tier 1 is `PARTIAL`** — the code exists and its unit tests pass,
but it has never run against a data window wide enough to emit anything.
`a01_coverage_supports_absence{chain="ethereum"} 0` and
`a01_detectors_alerting 0` are the system correctly declining to speak, not a
defect.

Two Section 6 invariant problems found and **not** silently absorbed:

1. **`no_trade_execution=True` does not exist in the codebase.**
   `grep -rni "trade" --include=*.py` returns only incidental matches — a
   durability comment in `database/connection.py:64`, prose in
   `intelligence/analysis/`, a BIP-39 wordlist in `tools/blockchain/wallet.py`,
   and an intent-router keyword list. The actual behaviour is correct (the CLI
   help states A01 holds no keys, signs nothing, and never submits a
   transaction; there is no signing or exchange-write path), but the hardcoded
   flag the invariant names is unimplemented. The guarantee is implicit rather
   than enforced. Recorded as VIOLATED-AS-SPECIFIED.
2. **Import direction is `UNVERIFIED`.** No mechanical enforcement of the
   downward-only rule was found. Not claimed as holding.

One Section 14 concern: `except Exception: pass` at
`memory/base/conversation.py:1523` and `:1538`. Off the A01 data path, but
unclassified suppression. Not fixed this session.

### Files touched

| File | Tag | Note |
|---|---|---|
| `agents/A01_Blockchain_Intelligence/.env.local` | **BUILD-NEW** | Migration target. Did not exist |
| `PROJECT_STATE.md` | **BUILD-NEW** | Section 4 continuity |
| `BUILD_LOG.md` | **BUILD-NEW** | Section 4 continuity |

**No source code was modified.** 831 tests passed before the session's changes
and nothing on a code path was altered, so the suite's meaning is unchanged.

### The `.env.local` migration

Source `F:\Agents\.env.local` (445 bytes) contained:

- `A01_PYTHON=F:\CIE-OS (crypto intelligence engine-opreting system\.venv\Scripts\python.exe`
- three commented, empty provider keys (`ALCHEMY_API_KEY`, `ETHERSCAN_API_KEY`,
  `INFURA_API_KEY`)

**No live credentials were present**, so this migration did not handle any
secret and the Section 18 escalation trigger did not fire.

Three decisions, with reasons:

1. **Target = agent root, not repo root.** `config/dotenv.py` searches
   `.env.local` then `.env` across four directories, nearest first, and returns
   on the **first file found**. The repo root already holds an empty `F:\CIE-OS\.env`,
   which was being found and yielding zero variables — the exact silent failure
   `config/dotenv.py`'s own module docstring was written to prevent. Placing the
   file at the agent root shadows it. It also keeps the file agent-scoped, so
   A02 does not inherit A01's configuration (Section 0: no shared state).

2. **`A01_PYTHON` corrected — MINOR-FIX.** The migrated path pointed at
   `F:\CIE-OS (crypto intelligence engine-opreting system\...`, which **does not
   exist on this machine** (`ls` confirms). Migrating it verbatim would have
   carried a dead path forward. `a01.bat` checks `if exist` before using it, so
   a dead value falls through to the upward `.venv` search and then to system
   Python — which lacks `pydantic-settings` and `aiosqlite`, and makes a working
   agent look broken. Corrected to `F:\CIE-OS\.venv\Scripts\python.exe`,
   verified present.

3. **File written ASCII-only, no BOM — deliberate.** It is parsed by two
   fragile readers. `config/dotenv.py:137` skips any name that is not
   alphanumeric-plus-underscore, so a UTF-8 BOM would turn `A01_PYTHON` into
   `\ufeffA01_PYTHON` and **silently drop the first variable**. `scripts/a01.bat`
   reads the same file with `for /f delims==` under the console codepage.
   Verified: first bytes are `# C I E - O S` (no BOM) and
   `grep '[^ -~]'` finds nothing.

The commented key list was expanded from 3 names to the 9 the provider catalog
actually reports, so the file matches what `python -m cli providers` tells the
operator to set. All remain commented and empty — no behaviour changed, no
false activation.

### Tests run / passed / failed

| Command | Result |
|---|---|
| `python -m pytest -q --timeout=300` | **error** — `unrecognized arguments: --timeout=300`; `pytest-timeout` is not installed. Re-run without it |
| `python -m pytest -q` | **831 passed**, 0 failed, 2 warnings, 45.28s |
| `python -m cli doctor` | 13/13 `ok`, exit 0 |
| `python -m cli metrics --db data/a01.db` | ethereum 45 blocks / 14,457 tx |
| `python -m cli providers` | 21 endpoints, 8 usable, 13 dormant |

Post-migration verification:

| Check | Result |
|---|---|
| `dotenv.parse()` on the new file | `{'A01_PYTHON': 'F:\\CIE-OS\\.venv\\Scripts\\python.exe'}` — exactly one variable |
| BOM / non-ASCII scan | Clean |
| `cli doctor` credentials line | `ok — 0 keyed provider(s) active; 1 variable(s) from F:\CIE-OS\agents\A01_Blockchain_Intelligence\.env.local` |
| `cli providers` env line | `1 variable(s) from F:\CIE-OS\agents\A01_Blockchain_Intelligence\.env.local` |
| `a01.bat` resolution block, replicated in a scratch `.bat` | `RESOLVED: F:\CIE-OS\.venv\Scripts\python.exe` |

Before the migration both commands reported `0 variable(s) from F:\CIE-OS\.env`.
The batch block was replicated rather than running `scripts/a01.bat` directly,
because that script performs a live 25-block ingest and ends in `pause`.

### Decisions made and why

- **Everything got `REUSE`.** Nothing was replaced. Section 3.2 requires failing
  tests, an invariant violation risking correctness, or a structural block — and
  the suite is fully green. The two invariant problems found are *missing
  enforcement*, which is a gap to close, not grounds to replace working code.
- **The nine empty top-level directories were left alone.** They contradict
  Section 8's vertical-slice discipline, but they are inert and removing them is
  a preference, not a justification. Logged below instead.
- **`no_trade_execution` was not added this session.** Section 18 requires
  stopping and asking before touching a trade-execution boundary. Reported to
  the operator rather than implemented unilaterally.

### Proposed improvements (not acted on)

- `PROPOSED-IMPROVEMENT`: add `no_trade_execution=True` as a real constant in
  `config/constants.py`, asserted at agent startup and surfaced by
  `cli doctor`, turning the read-only guarantee from implicit into enforced.
- `PROPOSED-IMPROVEMENT`: add mechanical enforcement of the downward-only
  import rule (e.g. `import-linter`), so that invariant can move from
  `UNVERIFIED` to `HOLDS`.
- `PROPOSED-IMPROVEMENT`: classify or narrow the two `except Exception: pass`
  sites in `memory/base/conversation.py`.
- `PROPOSED-IMPROVEMENT`: close the two `aiosqlite` connections in
  `memory/storage/tests/test_storage.py` with `async with` to clear the
  `ResourceWarning`s.
- `PROPOSED-IMPROVEMENT`: add `pytest-timeout` to the dev requirements so a
  hung test cannot stall a suite run.
- `PROPOSED-IMPROVEMENT`: delete the nine empty top-level directories, or add a
  one-line README to each stating the owning module, so an audit is not
  misled by them.
- `PROPOSED-IMPROVEMENT`: remove the now-redundant empty `F:\CIE-OS\.env`, which
  exists only to be shadowed.

### Self-critique — what is fragile, assumed, untested

- **Fragile:** the migrated file's usefulness depends on `F:\CIE-OS\.venv`
  staying put. If the venv moves, `A01_PYTHON` is dead again and the failure is
  a silent fallback to system Python, not an error.
- **Fragile:** `config/dotenv.py` returns on the **first** file found, so
  creating a `.env` in the agent directory later would shadow this `.env.local`
  and quietly drop `A01_PYTHON`.
- **Assumed:** that `memory/`, `planning/` and `tools/` are healthy. Their tests
  pass, but they were not read — 74,702 LOC across 330 files was assessed by
  test result and structure only. Their invariant column is `UNVERIFIED` and
  should stay that way until someone reads them.
- **Assumed:** that `Tier 0 = DONE` generalises beyond ethereum. It does not.
  Only ethereum has ingested data; the other eight chains are registry entries
  with readable sensors and nothing more.
- **Untested this session:** ingestion against a live chain, the REST interface,
  the visualize/dashboard path, backup/restore, and every Tier 1 intelligence
  module against real data rather than fixtures.
- **Not verified:** whether `F:\A01_Blockchain_Intelligence\` at the drive root
  is a stale duplicate of the agent. It was noticed and not investigated.

### Open questions for the operator

1. Delete the source `F:\Agents\.env.local` now that its contents are migrated
   and verified? It was left in place — the contents are copied and the one real
   value was corrected, so nothing is lost either way.
2. Add `no_trade_execution=True` as a real enforced constant? Section 18 says a
   trade-execution boundary is an escalation, so this is the operator's call.
3. Is `F:\A01_Blockchain_Intelligence\` (drive root) a stale duplicate that
   should be removed, or a deliberate second checkout?
4. Should provider keys be obtained? 13 of 21 endpoints are dormant. Not
   required for correctness, but it bounds throughput and historical depth.

### Next session should start at

**Tier 1, the first real vertical slice.** Widen the ethereum coverage window
(`python -m cli ingest --chain ethereum --blocks N --tokens`) until
`a01_coverage_supports_absence{chain="ethereum"}` reads 1 and at least one
detector is licensed to alert, then trace a single intelligence output from
terminal alert back to raw ingestion with its provenance intact — the Section 19
end-to-end scenario, on one chain.

Do **not** start Tier 2 (additional chains) before that passes.

> **Correction, appended 2026-08-11 (session 2):** the clause "and at least one
> detector is licensed to alert" was wrong. Alerting is gated on `VALIDATED`
> maturity, which requires a measured error rate from `evaluation/` against a
> labelled window — not on data volume. No amount of ingestion moves it. See
> session 2 below.

---

## Session 2026-08-11 (second session)

### Goal for this session

Operator chose: close the two Section 6 invariant gaps first, then attempt the
Tier 1 vertical slice. Also approved adding the `no_trade_execution` constant
(Section 18 escalation) and deleting the migrated source env file.

### Audit findings (delta from session 1)

**Correction to session 1.** Session 1 recorded the read-only guarantee as
"implicit, not enforced". That was too strong, and reading
`tests/test_security.py` disproved it: `test_no_signing_primitive_exists_in_the_source`,
`test_every_rest_route_is_read_only` and `test_the_service_exposes_no_write_operation`
already enforce it by scanning the source and the public surface. What was
genuinely missing was only the *named constant* Section 6 specifies. Step 1
shrank accordingly.

**Correction to session 1.** Session 1 said alerting was blocked by a narrow
coverage window. Wrong. `decision/maturity.py` gates alerting on `VALIDATED`
maturity via a measured error rate; coverage is a separate gate governing
*negative* claims. The two are independent and were conflated.

**Import direction, previously `UNVERIFIED`, is now measured:** exactly **2**
upward imports across the 11 ranked layers, plus **1** resulting cycle. Far
better than feared for a 128k-LOC codebase.

### ACTIVE BLOCKER discovered — log completeness is not recorded

Found while running the Step 3a backfill. A 25-block ingest with `--tokens`
reported `tokens: 0 transfer(s)` — impossible on ethereum mainnet, where the
same run stored 8,623 transactions.

Root cause, verified by direct call rather than inference:

```
sensor.logs(from_height=25723761, to_height=25723761)
  -> determined: False, reason: "3 endpoint(s) tried, none answered"
```

The open endpoints refuse `eth_getLogs`. The poller's handling is correct and
deliberate — it counts `logs_undetermined` and keeps the block. But the
shortfall never reached the stored row (`complete` is set from the block's own
quality, `database/writer.py:177`), `supports_absence` never consults
completeness (`skills/base.py:85`), and nothing was printed.

This **blocks Step 3**: backfilling 3,600 blocks this way would flip
`supports_absence` to 1 and license negative claims over a window whose
transfers were never fetched. The backfill was therefore **not run** — at the
measured 7.6 s/block it would have cost ~7.5 hours to produce a poisoned window.

### Files touched

| File | Tag | Note |
|---|---|---|
| `config/constants.py` | **MINOR-FIX** | Added `NO_TRADE_EXECUTION` + `__all__` entry |
| `cli/main.py` | **MINOR-FIX** | Added `trade execution` doctor check; added `logs` line + shortfall warning to `ingest` |
| `tests/test_security.py` | **MINOR-FIX** | Added `test_trade_execution_is_disabled_and_cannot_be_switched_off` |
| `tests/test_architecture.py` | **BUILD-NEW** | Layer direction + cycle ratchet, 7 tests |
| `F:\Agents\.env.local` | **deleted** | Migration source, approved by operator |
| `PROJECT_STATE.md` | overwritten | |
| `BUILD_LOG.md` | appended | |

### Tests run / passed / failed

| Command | Result |
|---|---|
| `python -m pytest -q tests/test_security.py` | 17 passed |
| `python -m pytest -q tests/test_architecture.py` | **1 failed, 5 passed** — the cycle test found `intelligence <-> skills` |
| `python -m pytest -q tests/test_architecture.py` (after ratchet) | 7 passed |
| `python -m pytest -q` (full) | **839 passed, 0 failed**, 42.51s — up from 831 |
| `python -m cli doctor` | **14/14 ok**, exit 0; new line `trade execution ok — disabled; 6 route(s) read-only` |
| `python -m cli ingest --blocks 3 --tokens` | Now prints `logs: 0 captured, 3 undetermined, 0 dropped` + WARNING |

The architecture cycle test failing on first run is recorded deliberately: it
was written before the violation was known to exist, and it found one.

### Decisions made and why

- **`NO_TRADE_EXECUTION` is not configurable and not read from the
  environment.** A boundary a deployment can switch off is a default, not a
  boundary — the same reasoning `decision.maturity` applies to
  `ALERT_MATURITY`. The doctor check pairs the constant with a live surface
  scan, because a flag reporting "ok" beside an exposed write route would be
  exactly the reassuring lie the check exists to prevent.
- **Enforced 2 of the 3 documented layer rules.** `layered-architecture.md` §5
  also says "no skipped layers"; that is stricter than the Section 6 invariant,
  the codebase has never met it, and asserting it would produce a test that
  fails on arrival and gets deleted. Only downward-direction and no-cycles are
  asserted. The omission is documented in the test module itself.
- **The 2 upward imports and 1 cycle were allowlisted, not fixed.** Both fixes
  mean relocating a shared name to a lower layer, which changes a package's
  public surface — scoped work, not a side effect of adding a test. The
  allowlist is a two-way ratchet: a new violation fails, and so does an entry
  that has been fixed but left behind.
- **The `ingest` visibility fix was made; the deeper completeness fix was
  not.** Printing the shortfall is unambiguously right and touches nothing.
  Making `complete` reflect log completeness, and `supports_absence` require
  it, changes stored-data semantics and the meaning of an existing column —
  that needs the operator.
- **The backfill was not run.** Building a 7.5-hour window on a known-poisoned
  path would have been the expensive way to produce a wrong answer.
- **The 28 tainted blocks were left in place.** Deleting stored observations is
  irreversible; the operator decides.

### Proposed improvements (not acted on)

- `PROPOSED-IMPROVEMENT`: record log completeness on the block row — either a
  `logs_complete` column or by folding the log shortfall into `complete` — and
  make `Coverage.supports_absence` require it. This is the blocker's real fix.
- `PROPOSED-IMPROVEMENT`: have `cli ingest` exit `EXIT_DEGRADED` when logs are
  undetermined, as it already does for rejections. Not done unilaterally: it
  changes an exit-code contract the scheduled task reads.
- `PROPOSED-IMPROVEMENT`: relocate `DEFAULT_PERCENTILE` and `Stance` downward to
  clear the allowlist and break the cycle.
- Carried forward, unchanged: `pytest-timeout` missing; two
  `except Exception: pass` sites in `memory/base/conversation.py`; two
  `aiosqlite` `ResourceWarning`s; nine empty top-level directories; the
  redundant empty `F:\CIE-OS\.env`.

### Self-critique — what is fragile, assumed, untested

- **Fragile:** the architecture test ranks only the 11 packages the doc names.
  Twelve others are explicitly `UNRANKED` and therefore unchecked — including
  `tools/`, `planning/` and `blockchain/`. Coverage of the invariant is real
  but partial, and the module says so.
- **Fragile:** the cycle check is package-level. A cycle *within* one package
  passes it.
- **Assumed:** that `eth_getLogs` failure is provider-side and not a bug in
  A01's log request. Evidence points at the provider — the identical code path
  captured 26,987 transfers on 2026-08-10 — but no keyed endpoint was tried, so
  this is `PROBABLE`, not `VERIFIED`.
- **Untested:** whether the 45 older blocks are themselves fully log-complete,
  or merely got more logs than the newer ones. They were not audited per-block
  against an independent source.
- **Untested this session:** the REST interface, `visualize`, backup/restore,
  and every Tier 1 module against real data. Unchanged from session 1.
- **Not verified:** `F:\A01_Blockchain_Intelligence\` at the drive root. Noticed
  in session 1, still not investigated.

### Open questions for the operator

1. **The blocker fix.** Add a `logs_complete` column, or fold the log shortfall
   into the existing `complete` flag? The second is less schema churn but
   overloads a column whose current meaning is "the block record was complete".
2. **The 28 tainted blocks** (25723761–25723788) — delete and rewind the
   checkpoint to 25723760, or keep and let the completeness fix reclassify them?
3. **Provider keys.** This has stopped being only a throughput question: a keyed
   endpoint that serves `eth_getLogs` is the difference between a usable Tier 1
   window and none. 7.5 hours for 3,600 blocks on open endpoints is also
   impractical on its own.
4. Still open from session 1: is `F:\A01_Blockchain_Intelligence\` a stale
   duplicate?

### Next session should start at

**The blocker, not the slice.** Decide question 1, implement it with a
regression test that a log-incomplete block cannot license a negative claim,
then re-attempt the Tier 1 slice. The slice's success criterion remains
`supports_absence 1` plus one traced end-to-end output — **not** an alert, which
is gated on evidence that does not exist yet.

---

## Session 2026-08-11 (third session)

### Goal for this session

Fix the blocker recorded above. The operator delegated open question 1 (new
column vs. reuse the existing flag) rather than answering it, so the choice is
made and justified below.

### Decision on the blocker's shape

**Reuse `blocks.complete`. No schema migration.**

Reading `normalization/quality.py` settled it. That module already describes the
exact failure, in its own docstring, as the reason it exists:

> "a thin record reaching a detector unlabelled is read as complete, and 'no
> large transfers in this block' is then asserted from a record that never
> contained transfers at all."

And `Severity.INCOMPLETE` is already defined as *"Usable, but narrower than it
looks. A consumer must not infer absence."* That is precisely the claim a
log-refused block needs to carry. A `logs_complete` column would have added a
second, parallel vocabulary for a distinction the codebase had already drawn —
and left `complete` still lying.

The bug was never a missing concept. It was that the shortfall had no route from
the poller, which knew, to the row, which reported.

### Files touched

| File | Tag | Change |
|---|---|---|
| `sensors/envelope.py` | **MINOR-FIX** | New `CaptureGap` enum; `RawRecord.capture_gaps` |
| `sensors/__init__.py` | **MINOR-FIX** | Export `CaptureGap` |
| `ingestion/poller.py` | **REFACTOR** | `_queue_logs` → `_read_logs`; logs read before the block is queued, queued after it |
| `normalization/quality.py` | **MINOR-FIX** | `assess_block(..., capture_gaps=)` + `logs_captured` finding |
| `normalization/normalizer.py` | **MINOR-FIX** | Pass `record.capture_gaps` through |
| `database/analytics.py` | **MINOR-FIX** | `HeightWindow.complete_blocks/.incomplete_blocks/.all_complete`; window query counts complete rows |
| `skills/base.py` | **MINOR-FIX** | `supports_absence` requires completeness; `limitation` explains |
| `ingestion/backfill.py` | **REFACTOR** | Gained `include_logs` and log counters; had **no log handling at all** |
| `cli/main.py` | **MINOR-FIX** | Backfill branch passes `include_logs`; log reporting shared by both capture paths |
| `ingestion/tests/test_ingestion.py` | **MINOR-FIX** | `FakeChain.logs()` + `serves_logs`; 7 new tests |
| `normalization/tests/test_normalization.py` | **MINOR-FIX** | 2 new tests |
| `skills/tests/test_skills.py` | **MINOR-FIX** | 1 new test |
| `data/a01.db` | **data correction** | 28 rows `complete=1` → `0` |

### The second half of the blocker, found by the self-critique

The first pass fixed only the poller. Writing the self-critique surfaced the
obvious question — *what about the other capture path?* — and checking it found
the same defect, worse:

`ingestion/backfill.py` had **no log handling whatsoever**. No `include_logs`
parameter, not one mention of logs in the file. `cmd_ingest` accepted `--tokens`
in backfill mode, configured a token repository, printed `tokens: 0 transfer(s)`
— and never asked for a log anywhere. Every block a backfill captured was stored
looking whole.

This was the more dangerous of the two, because a historical range is precisely
what a deep coverage window gets built from. Fixed by mirroring the poller:
`_read_logs`, read-before-queue, gap on failure, counters on `BackfillProgress`.

Two smaller corrections came with it, both in the backfill branch of
`cmd_ingest`: `job.run()` used the default batch of 50 regardless of `--blocks`,
so `--backfill --blocks 500` silently fetched 50; and `writer.drain` was sized
for blocks alone, which is half of what a run now produces.

### The ordering change in the poller

The one subtle piece. Logs must be **queued after** the block (token transfers
reference their block by foreign key), but the outcome must be known **before**
the block is queued (so it can be stamped on it). Those are not in conflict —
read and queue are separate steps — but the original code fused them.

One edge case had to be handled explicitly: logs fetched successfully but no
room left in the queue for them. Queueing the block anyway would store it
claiming completeness while discarding logs already in hand. The poller now
checks for room for **both** records before committing, and marks the gap if it
cannot have both. That failure is recoverable; the silent one was not.

### Tests run / passed / failed

| Command | Result |
|---|---|
| `python -m pytest -q` (after the source change, before new tests) | 839 passed — **nothing broke, and nothing covered the new behaviour** |
| `python -m cli ingest --blocks 2 --tokens` (live) | `logs: 0 captured, 2 undetermined`; blocks 25723789/90 stored **`complete=0`** where the same path produced `complete=1` before |
| `Coverage` over the live window | `supports_absence: False`, limitation names the incomplete count |
| `python -m pytest -q ingestion/ normalization/ skills/ tests` | 118 passed |
| `python -m cli ingest --backfill --start 25723714 --blocks 2 --tokens` (live) | `logs: 0 captured, 2 undetermined`; both blocks stored **`complete=0`** |
| `python -m pytest -q` (full, final) | **849 passed, 0 failed** |
| `python -m cli doctor` | 14/14 ok, exit 0 |

The 839-pass run after the source change is recorded deliberately: a green suite
that proves nothing is the reason Section 14 requires the regression test, not
the fix.

### The data correction

28 blocks (25723761–25723788) were stored `complete=1` with zero transfers by
the pre-fix code. The fix does not reach existing rows, so the window would have
kept counting them as whole.

Corrected with a scoped `UPDATE`: ethereum, canonical, `complete = 1`, zero
token transfers, and inside the range where log refusal was directly verified.
The 45 blocks holding real transfers were untouched. A verified snapshot was
taken first via the existing `cli backup`:
`data/a01-ethereum-20260811T102050Z.db`.

This is a correction, not a deletion, and it fails safe: if the judgement were
wrong, the effect is a window that refuses to license an absence it could have
supported. The opposite error is the one that produces confident falsehoods.

### Decisions made and why

- **Reused the existing flag** rather than adding a column — see above.
- **`capture_gaps` excluded from `record_id`.** Two captures of one block are
  the same observation whether or not one also obtained that block's logs.
  Folding the gap into the identity would break the dedup the record exists to
  provide. Asserted by a test.
- **`assess_block` takes the gaps as a parameter** rather than reading them off
  a new `CanonicalBlock` field. Everything else it checks is derivable from the
  block; log capture is not, and is not a property of the block at all. The
  function stays pure, which its own design goals require.
- **The correction was applied rather than escalated.** Section 18 reserves
  escalation for weak-justification replacements, architecture-level source
  conflicts, and trade/secrets boundaries. This was none of those, the evidence
  was direct, a backup existed, and the error direction is conservative.

### Proposed improvements (not acted on)

- `PROPOSED-IMPROVEMENT`: `cli ingest` should exit `EXIT_DEGRADED` when logs are
  undetermined, as it already does for rejections. Still not done: it changes an
  exit-code contract the scheduled task reads.
- `PROPOSED-IMPROVEMENT`: a `cli` repair path for retro-correcting completeness,
  so the next occurrence does not need a hand-written `UPDATE`.
- `PROPOSED-IMPROVEMENT`: relocate `DEFAULT_PERCENTILE` and `Stance` downward to
  clear the architecture allowlist and break the `intelligence <-> skills` cycle.
- Carried forward: `pytest-timeout` missing; two `except Exception: pass` sites
  in `memory/base/conversation.py`; two `aiosqlite` `ResourceWarning`s; nine
  empty top-level directories; the redundant empty `F:\CIE-OS\.env`.

### Self-critique — what is fragile, assumed, untested

- **Assumed, and this is the weakest link:** that all 28 corrected blocks were
  log-refused rather than genuinely transfer-free. The evidence is strong —
  ethereum blocks with 95–711 transactions each, ingested with `--tokens`, in a
  range where `sensor.logs()` was directly observed returning `determined:
  False` — but it is inference over a range, not a per-block observation. Rated
  `PROBABLE`, not `VERIFIED`. The error direction is conservative.
- **Both capture paths are now covered**, but only because the self-critique
  asked where else the bug could live. The first pass fixed the poller and
  declared the blocker resolved; it was resolved on one of two paths, and the
  unfixed one was the more important. Worth remembering as a process note: the
  fix felt finished before it was.
- **Untested:** the queue-full branch that drops fetched logs and marks the gap.
  It is guarded by a capacity check and marked `pragma: no cover`, so it is
  reasoned-about, not exercised.
- **Untested:** whether the 45 "complete" blocks are genuinely log-complete.
  They hold 26,987 transfers, which is strong evidence they were served — but no
  per-block reconciliation against an independent source was done.
- **Unchanged from earlier sessions:** REST interface, `visualize`,
  backup/restore round-trip, and every Tier 1 module against real data remain
  untested. `memory/`, `planning/`, `tools/` remain unread.

### Open questions for the operator

1. **A provider key is now the critical path.** Not a throughput question any
   more: without an endpoint that serves `eth_getLogs`, no window can ever
   support a negative claim, so Tier 1 cannot be validated at all. Which
   provider?
2. The 45 blocks captured on 2026-08-10 are still marked complete on the
   strength of holding 26,987 transfers. Should they be reconciled against an
   independent source before a window is built on them?
3. Still open: is `F:\A01_Blockchain_Intelligence\` (drive root) a stale
   duplicate?

### Late additions — the Tier 1 slice actually ran, and a claim was wrong

Two things were established after the blocker fix was written up.

**1. The Tier 1 vertical slice works end to end, today.** The absence gate needs
logs; *positive* claims do not — the whale and wallet skills read native value
transfers from the `transactions` table. Run against a real stored address:

```
cli investigate --db data/a01.db --address 0x5fa36dfe10ce3ee46479790076afe328bef7e2e2
  Signal 40.0/100   Confidence 0.60 (moderate)
  [affirmed]     likely: whale-scale transfer activity observed
                 retracted by: the transfer resolving to an internal rebalance ...
                 caveat: alerting requires validated maturity; never backtested
  [undetermined] cannot be determined: whether a dormant wallet reactivated
                 caveat: 32 of 77 stored blocks are incomplete ...
```

The Section 9 provenance chain was then closed by hand, all the way down:
conclusion → evidence artifact → `tx_hash 0xc8093c1e...` → stored transaction
(668.56 ETH) → block 25723775 → `parent_hash` linkage → `source_provider
publicnode` → `source_record_id block-068f054f...` → `observed_at`. That is the
Section 19 end-to-end scenario, minus the alert — which is correctly withheld.

Worth noting: **this session's own fix appears in that output**, and on the right
conclusion. The incomplete-window caveat attached to the *undetermined* dormancy
finding — a negative claim — and not to the affirmed whale finding.

Also verified: `cli visualize` renders a dashboard, and `cli serve` answers on
`/coverage`, `/investigate`, `/detectors`, `/skills`, `/health`, `/metrics`, with
the new completeness fields exposed over the API.

**2. "A provider key is the critical path" was wrong.** It was concluded from
ethereum alone. Base's open endpoints *do* serve `eth_getLogs`:

```
cli ingest --db data/base.db --chain base --blocks 10 --tokens
  logs   : 10 captured, 0 undetermined, 0 dropped
  tokens : 740 transfer(s), 133 NFT transfer(s)
  window : 15 blocks, 15 complete, contiguous True, all_complete True
```

The base window's only limitation is now depth — "only 15 blocks stored, 3600
needed" — which is the failure mode that ingestion alone fixes. Measured:
**base ~3.2 s/block** against **ethereum ~7.6 s/block**, so a 3,600-block base
window is ~3.2 hours, resumable, no key required.

A generalisation from one chain, in a codebase whose Section 10 exists
specifically to forbid that. Recorded rather than quietly edited.

### Next session should start at

**Build the 3,600-block base window.** Nothing blocks it:

```
python -m cli ingest --db data/base.db --chain base --blocks 500 --tokens
```

Repeated, or scheduled via `scripts/install-task.ps1`; the checkpoint makes it
resumable. Confirm `supports_absence` reads 1 *and* `all_complete` stays true,
then re-run the investigate → provenance trace on base with a licensed negative
claim included. That closes the Tier 1 gate.

Detector promotion to `VALIDATED` remains out of scope — it needs a labelled
window and `evaluation/backtest.py`, which is its own project.

---

## Session 2026-08-11 (fourth session)

### Goal

Continue building. Verify the Section 11 multi-agent claim left `UNVERIFIED`,
then build the anomaly engine — the one Tier 1 module Section 19 requires that
did not exist.

### Section 11 — verified, and it holds

Checked rather than assumed:

- `intelligence/engines/composition.py:194-203` records conflicting fields
  instead of overwriting them, with the reason stated in the code: *"Overwriting
  would hide a genuine disagreement behind a plausible value."* Covered by
  `test_conflicts_are_recorded_not_resolved`.
- `_weakest(coverages)` takes the weakest coverage, not the mean.
- `FinalScoreEngine` weights score *values* but sets
  `confidence = min(...)` and preserves the component breakdown. Section 11's
  prohibition is on averaging child conclusions; a numeric aggregate that keeps
  its components visible and takes worst-case confidence is not that.
- `EvidenceValidator` recomputes the content hash for chain-of-custody and
  enforces the tier ceiling.

Status moves from `UNVERIFIED` to `HOLDS`. No gap found.

### A serious bug found while building — `consume()` dropped records silently

Caught by watching the base window build, not by a test.

`cli ingest --blocks 100 --tokens` reported `logs: 100 captured` but
`stored: 32 block(s)`, and the window went non-contiguous. Cause:
`RecordWriter.consume()` drained **one** batch of `DEFAULT_BATCH = 64` records
and returned. A 100-block run with tokens queues 200 records, 64 of them were
written — 32 blocks — and the remaining 136 died with the process.

The checkpoint had already advanced to height 100, because the poller commits
the position when a record is *queued*, not when it is written. Heights 33-100
were therefore recorded as done and never fetched again.

Confirmed in the data before fixing: two gaps in `data/base.db`, of **68 heights
each** — exactly 100 − 32.

This never showed earlier because every previous run was under 32 blocks.

Fixed in `database/writer.py`: `consume` now drains until the queue is empty,
using `batch` as the commit size it was always documented to be. Regression test
`test_consume_drains_the_whole_queue_not_one_batch` fails on the old behaviour.

### The anomaly engine

Audited before building, per Section 3. `intelligence/scoring/anomaly.py`
already existed but consumed `subject["anomalies"]`, and **nothing produced it** —
an orphaned scorer. What was missing was the analyzer.

Built `intelligence/analysis/anomaly.py` (DET-ANOMALY-01), wired into
`DEFAULT_ANALYZERS`, the `score` stage, `_CLAIM_SPECS`, and the maturity
registry at `IMPLEMENTED` with the same `blocked_by` as its peers.

Design constraints taken from Section 12 and Section 13:

- Reports **deviation only**. Never bullish, bearish, manipulation, wash
  trading, or smart money — asserted by a test that scans the rendered output.
- Grades on the evidence standard's vocabulary: `NORMAL / UNUSUAL / SUSPICIOUS
  / HIGH_RISK_PATTERN / INSUFFICIENT_EVIDENCE`.
- `NORMAL` is a negative claim, so it requires `absence_meaningful`. Without
  coverage the verdict is `INSUFFICIENT_EVIDENCE`, not `NORMAL`.
- Under 20 observations, or a population with no spread, is
  `INSUFFICIENT_EVIDENCE` rather than a verdict.

### A bug I introduced, and caught before it shipped

The first version computed the modified z-score on **raw** transfer values. Run
against real data it produced:

```
HIGH_RISK_PATTERN — 1581 outlier(s) in a population of 5000 (max z=88104.08)
```

31.6% of ordinary ethereum traffic flagged as anomalous, and it had already
added 30 points to the signal score of a live investigation.

Measured both ways on the same 5,000 transfers:

| scale | outliers | share | max z |
|---|---|---|---|
| raw | 1,581 | 31.6% | 88,104 |
| log10 | 0 | 0.0% | 2.5 |

The estimator assumes approximate normality around the centre. Transfer values
are log-normal across eight orders of magnitude, so on the raw scale the MAD is
negligible against the spread and nearly everything clears the cutoff. A robust
estimator on the wrong scale is still wrong.

Fixed by transforming to log10 first, and the `SUSPICIOUS`/`HIGH_RISK` bands
retuned from 10/50 to 5/8, which were meaningless on the raw scale.

Regression test `test_a_log_normal_population_is_not_flagged_wholesale` was
verified to actually catch it: **40% flagged without the transform, 0% with**,
against an asserted ceiling of 2%.

Note for the record: this does not contradict the whale detector flagging the
largest of those transfers. Percentile rank and distributional outlier are
different questions — the largest sample from a log-normal population is
expected to be the largest, and being so is not a departure from the
distribution.

### One more wiring gap, found by reading the live output

The report stage listed findings from a hardcoded `("whale", "dormant")` tuple.
The new detector was therefore scoring and reaching the decision gate while
never appearing in the findings a reader sees. Now derived from whichever
analyzer findings carry a summary.

### Files touched

| File | Tag | Change |
|---|---|---|
| `database/writer.py` | **MINOR-FIX** | `consume` drains the whole queue |
| `intelligence/analysis/anomaly.py` | **BUILD-NEW** | DET-ANOMALY-01 |
| `intelligence/analysis/__init__.py` | **MINOR-FIX** | Export |
| `intelligence/core/stages.py` | **MINOR-FIX** | Register analyzer, score contribution, derive the findings list |
| `decision/conclusions.py` | **MINOR-FIX** | `_CLAIM_SPECS["anomaly"]` |
| `decision/maturity.py` | **MINOR-FIX** | DET-ANOMALY-01 at `IMPLEMENTED` |
| `database/tests/test_database.py` | **MINOR-FIX** | 1 regression test |
| `intelligence/analysis/tests/test_analyzers.py` | **MINOR-FIX** | 12 new tests |

### Tests run / passed / failed

| Command | Result |
|---|---|
| `python -m pytest -q database/tests/test_database.py` | 29 passed |
| `python -m pytest -q intelligence/analysis/tests/test_analyzers.py` | 33 passed |
| `python -m pytest -q` (full) | **862 passed, 0 failed** (was 850) |
| `python -m cli detectors` | 3 detectors, all `implemented`, **0 may alert** |
| Live `cli investigate` after the log fix | `anomaly not determinable (no deviation found, but the window cannot license an absence)` |
| Base window build, chunk 2 | `200 blocks, 200 complete, contiguous=True` — was 32/100 before the `consume` fix |

The full-suite run took 205s rather than the usual ~50s; the base window build
was competing for disk and network at the time. Not a code regression.

### Self-critique

- **Two of this session's three bugs were found by watching real output, not by
  the suite.** The `consume` truncation and the raw-scale anomaly both passed
  every test that existed. Unit tests confirm what a component does with data
  you thought to give it; neither would have surfaced without running the thing
  against a real chain.
- **The anomaly detector has never been validated against labelled data.** Its
  thresholds (3.5 / 5 / 8, min population 20) are principled and sourced, but
  unmeasured. It sits at `IMPLEMENTED` for exactly that reason.
- **Untested:** the `HIGH_RISK_PATTERN` and `SUSPICIOUS` bands have unit
  coverage but have never fired on real chain data, because the one real
  population tested had no genuine outlier.
- **Assumed:** that log10 is the right transform for every chain's value
  distribution. Verified on ethereum only. Base may differ, and no test asserts
  the assumption holds per-chain.
- **Base window still building** — 200 of 3,600 blocks at the time of writing.

### Next session should start at

Finish the base window, then re-run the investigate trace on base where
`supports_absence` will be true — the first time A01 will be able to issue a
licensed *negative* claim, and the first real exercise of the anomaly detector's
`NORMAL` verdict.

Then: exchange flow intelligence (needs an address label source) and terminal
depth. Detector promotion to `VALIDATED` remains its own project.

---

## Session 2026-08-11 (fifth session) — selective capture

### Goal

The operator reported that a previous project mirrored every blockchain
transaction locally and computed over the copy, which became heavy and buggy.
**That anti-pattern was in A01**, and the first job was to measure it rather
than accept or dismiss the report.

### Measured, before changing anything

| chain | blocks | size | per block |
|---|---|---|---|
| ethereum | 77 | 54.2 MB | **0.70 MB** |
| base | 437 | 175 MB | **0.40 MB** |

Ethereum at 7,200 blocks/day → **~5 GB/day, ~150 GB/month, one chain**. Across
fifteen chains, 30–50 GB/day. The operator's diagnosis was correct.

334 transactions per ethereum block were being stored so that a handful could
later be counted. The counting can happen once, at capture.

### What was built

**Schema v3** (`database/migrations.py`, forward-only, verified against an
existing v2 database with data preserved):
`block_aggregates`, `hourly_aggregates`, `entities`, `labels`.

**`tiers/`** — where data lives and for how long:

| Tier | Window | Holds |
|---|---|---|
| CACHE | seconds | raw provider responses, in memory only |
| HOT | 7 days | per-block aggregates + material transactions |
| WARM | 90 days | hourly aggregates — the anomaly baseline |
| LEDGER | forever | entities, track records, labels |

`tiers/retention.py` states the policy as data, not behaviour, so it can be
reported rather than inferred. 90 days for WARM because institutional and
smart-money patterns are measured in months.

**`pipeline/`** — `materiality.py` (percentile-based gate, never a fixed
currency amount) and `aggregate.py` (the counters that make dropping honest).

### Correction to the approved plan

The plan said to reuse `memory/storage/cache.py` for the cache tier. **Reading
it showed that was wrong** — it is async and `MemoryEntry`-shaped, built for
conversational agent memory, and the ingestion path is synchronous.

The correct reuse was already in the codebase: `blockchain/rpc/clients/cache.py`
(`ResponseCache`), which is sync, bounded, never caches failures, and derives
lifetimes from finality rather than a fixed clock — an immutable block is held
indefinitely while a head-dependent read is barely held at all. It is already
wired through `ChainDispatcher` into every sensor read. **Tier C needed no work.**

### A bug in my own code, caught before it shipped

`BlockAggregateRepository.totals_between` first summed value columns with
`SUM(CAST(value AS INTEGER))`. Amount columns are zero-padded TEXT precisely
because SQLite's INTEGER is signed 64-bit, ceiling ~9.22e18 — about nine ether
in wei.

Verified rather than reasoned about: SQLite does not truncate here, it **raises
`integer overflow`**. Any window summing more than ~9.2 ETH — which is nearly
every window — would have failed outright. Counts are now summed in SQL; values
are summed in Python, whose integers are unbounded.

Regression test `test_large_totals_are_exact` uses 150 ETH deliberately.

### Result — measured on real ethereum data

Filter, over the 77 stored blocks (25,743 real transactions):

```
derived floor    : 13.03 ETH  (99.5th percentile of the chain's own distribution)
transactions seen: 25,743
kept (material)  : 66   (0.26%)
dropped          : 25,677
```

Disk, same blocks written the new way:

| | old | new |
|---|---|---|
| per block | 720.8 KB | **2,926 bytes** |
| ethereum/day | ~5 GB | **20.1 MB** |
| 90 days | ~450 GB | **1.77 GB** |

**252× reduction.** The plan's target was under 5 KB/block.

Caveat stated: this figure covers aggregates only. The 66 material transactions
add roughly 0.3 KB/block at typical row size — still inside the target, but not
included in the 2,926.

### Tests

| Command | Result |
|---|---|
| `pytest -q database/` | 50 passed (v2→v3 migration preserves data) |
| `pytest -q tiers/ tests/test_architecture.py` | 18 passed |
| `pytest -q pipeline/ tiers/ tests/test_architecture.py` | 35 passed |
| `pytest -q` (full) | **890 passed, 0 failed** (was 862) |
| `cli doctor` | 14/14 ok, exit 0 |

`tiers` and `pipeline` added to the architecture test's layer order and to
`pytest.ini` testpaths — without the second, the new tests would have been
written and never run.

### Self-critique

- **The 252× figure is a replay, not a live run.** Real transactions, real
  values, but read from the existing store rather than streamed from a live
  block. The live path is not yet wired to the new pipeline.
- **The materiality gate's label rule is inert.** No label source is
  configured, so exchange and bridge flows below the value floor are invisible.
  The gate reports this through `limitation()` rather than failing quietly, but
  it is a real coverage hole and it is the operator's stated Tier-1 signal.
- **Tier W and Tier L have schema but no repositories yet.** The baseline
  rollup and entity ledger are designed and migrated, not implemented.
- **Untested:** the floor rising under budget pressure. The mechanism exists
  (`with_floor`) and nothing exercises it.
- **The old full-copy path is still the one `cli ingest` uses.** Nothing has
  been switched over; both exist side by side.

### Next session should start at

Wire the live capture path to the new pipeline and re-measure against a real
ingest rather than a replay. Then Tier W rollup and Tier L entity ledger, which
is what smart-money detection needs to start accumulating at all.


---

## Session 2026-08-11 (fifth) — selective pipeline wired to live capture

### Goal

Wire the new selective pipeline into the real capture path and measure it
against live chain data, not a replay.

### Result — the duplication anti-pattern is fixed and measured

| | old (full copy) | new (selective) |
|---|---|---|
| marginal cost | 536,986 B/block | **1,502 B/block** |
| base @2s | 21.60 GB/day | **61.9 MB/day** |
| ethereum @12s | 3.60 GB/day | **10.3 MB/day** |
| 15 chains × 90 days | ~28 TB | **~82 GB** |

**358× reduction.** The plan's target was <5 KB/block; actual is 1.5 KB.

The plan text said "roughly 700×" — that was an estimate written before
measurement. The measured figure is 358×, and the plan should be corrected
rather than left to look achieved.

Live run, base chain, 30 blocks: `5,003 transactions seen, 6 stored (0.12%)`.
The 168 KB of fixed schema is paid once and excluded from the marginal figure;
an earlier 30-block sample reported 6.67 KB/block because that overhead was
still being amortised, which overstated the cost.

### Files touched

| File | Tag | Change |
|---|---|---|
| `pipeline/writer.py` | **BUILD-NEW** | `SelectiveWriter` — wraps `RecordWriter`, filters `block.transactions` before storage |
| `normalization/quality.py` | **MINOR-FIX** | `capture_floor` param + `selective_capture` finding |
| `cli/main.py` | **MINOR-FIX** | `--selective` / `--floor` flags, both capture paths, backfill head fix |

### Two bugs found by running it, not by reading it

1. **Backfill demanded a head read it never used.** `cmd_ingest` called
   `sensor.head()` before checking `--start`, and returned `EXIT_DEGRADED` when
   it failed. When base's endpoints stopped answering head reads, a backfill
   over a fixed historical range — every height settled and fetchable — refused
   to run. This is why the overnight 3,600-block job stalled at 700 contiguous
   blocks and then burned every remaining chunk doing nothing. Fixed: the head
   is read only when the caller did not supply a start.

2. **`--selective` was ignored by the backfill path.** Only the poller branch
   used it, so `--selective --backfill` would have stored every transaction of a
   historical range while reporting itself selective — and a historical range is
   exactly where the volume is. Both paths now honour it.

### Design note: selective capture vs "incomplete"

Writing only material transactions makes `len(block.transactions) <
block.transaction_count`, which fired the existing `transactions_complete`
finding: *"N of M transactions could not be normalized"*. That is factually
wrong — they normalized fine and were dropped on purpose — and would have sent
someone hunting a parser bug that does not exist.

`assess_block` now takes `capture_floor` and emits `selective_capture` instead,
with an exact boundary: *"do not infer that no transfer below <floor> occurred;
transfers at or above it were all captured."* Still INCOMPLETE, correctly — but
a consumer can now tell which side of the floor its question falls on.

`transaction_count` is deliberately left at the chain's own figure. Lowering it
to the material count would make a busy block read as a quiet one — the exact
misreading the aggregate exists to prevent.

### Tests

| Command | Result |
|---|---|
| `pytest -q` | **893 passed, 0 failed** |
| `cli doctor` | 14/14 ok, exit 0 |
| live `--selective` (poller) | 30 blocks, 5,003 seen, 6 kept (0.12%) |
| live `--selective --backfill --start` | 20 blocks, 3,085 seen, 4 kept — head never read |

### Open

- **Rate limits are now the binding constraint, not code.** Base's free
  endpoints stopped answering head reads under sustained load. This is exactly
  what the per-day/month budget ledger is for; it is the next task and is no
  longer optional.
- The 3,600-block absence window still has not been built. Two attempts failed
  for two different reasons, both now fixed.
- `supports_absence` should become floor-aware: a selectively captured window
  can license absence claims *above* the floor and not below. Currently any
  selective block counts as incomplete, so the gate stays shut.

### Next session should start at

The call-budget ledger (`pipeline/budget.py`), then rebuild the 3,600-block base
window with both fixes in place.

---

## Session 2026-08-11 (sixth) — persistent call-budget ledger

### Goal

Build the per-day / per-month call budget the free tiers actually meter on.
Rate limits became the binding constraint last session: base's endpoints stopped
answering head reads under sustained load, which is what stalled the 3,600-block
window.

### What was built

`pipeline/budget.py` + schema **v4** (`call_ledger` table).

`blockchain/rpc/rate_limit/bucket.py` already handles the per-minute dimension
and stays untouched. What it cannot do is remember: its state is a dict in
memory, so every restart hands the process a fresh minute. That is fine for a
minute and useless for a month, and the scheduled task runs every ten minutes
as a new process.

Design decisions, each with a reason:

- **Attempts are counted, not successes.** A provider counts the request when
  it arrives. Recording only successful calls undercounts precisely during
  retries, timeouts and 429 storms — the periods that burn the most allowance.
  So the ledger is written before the call goes out, and a failed call costs.
- **Day and month tracked separately; the worse one binds.** A provider can be
  comfortable today and out of allowance for the month. Tracking only the day
  walks into a wall it could have seen coming.
- **UTC windows.** A ledger on local time double-counts or skips an hour twice
  a year, and the provider is not resetting on the operator's timezone.
- **A ceiling is a belief, not a fact.** A 429 observed while the ledger still
  shows headroom is the provider stating its real limit;
  `observe_rejection()` records it and every later decision uses the lower
  figure. **The spend is never rewritten** — what was used is history, what is
  allowed is an estimate, and conflating them destroys the evidence that the
  estimate was wrong.
- **A provider with no known ceiling is never throttled.** Unmetered and
  undocumented providers are real; inventing a number produces confident
  throttling with no basis.
- **Conserve at 85%, do not stop at 100%.** A chain that goes dark at 23:00
  every day is worse than one that stays coarse from 20:00. `TIGHT` recommends
  degradation; it never applies it silently.

### Tests

| Command | Result |
|---|---|
| `pytest -q pipeline/tests/test_budget.py` | 15 passed |
| `pytest -q` (full) | **908 passed, 0 failed** |
| `cli doctor` | 14/14 ok, `storage ok — schema v4`, exit 0 |

Verified by execution, not reasoning: day resets while month carries; the worse
window binds; a 429 drops a believed ceiling from 5,000 to the 300 actually
spent and flips pressure to `EXHAUSTED`; an unmetered provider stays `UNKNOWN`
after 50,000 calls.

### Stopped deliberately short of wiring

The ledger is built and tested but **nothing writes to it yet on the real call
path**. That was a choice, not an omission.

Wiring it properly means aggregating `CallResult.attempts` per provider inside
`blockchain/rpc/clients/dispatch.py`, which is where the calls actually happen.
The approximation available at the CLI level — the poller's step count — is a
*lower bound* on calls made, and a budget that quietly undercounts is worse than
no budget: it reports headroom that does not exist. That is the same class of
false confidence this project keeps finding and fixing, and it was not worth
introducing to close a task.

Also noted: the transport layer should not grow a storage dependency. The
budget belongs to the caller, consulted around the call, not inside the
dispatcher.

### Next session should start at

1. Aggregate `CallResult.attempts` per provider and record spends through
   `CallBudget.spend()` — the seam is `ChainDispatcher.call`'s return path.
2. Then rebuild the 3,600-block base window with all three fixes in place
   (`consume` drain, backfill head, budget).

---

## Session 2026-08-12 — coverage learns *why* a block is incomplete

### Goal

Fix the incompleteness reason. Selective capture had shut the absence gate on
itself: every block it writes is incomplete, `complete` is one bit, and one bit
cannot separate a block that was filtered from a block that was never fetched.

### The bug, stated exactly

Two failures were stored identically and read as the worse one.

| | logs refused | filtered at a floor |
|---|---|---|
| what is missing | transfers nobody can describe | everything below a written-down number |
| what it licenses | no negative claim at all | "nothing at or above the floor happened" |
| what was stored | `complete = 0` | `complete = 0` |

So `Coverage.limitation` told an operator that selectively captured blocks
*"are incomplete; their transfers were never fetched"* — false, and false in the
direction that sends someone hunting a transport bug that does not exist. And
`supports_absence` stayed shut forever on any selective window, which threw away
the entire point of capturing selectively: the drop is bounded and the bound was
known at capture time.

### What changed

| File | Tag | Change |
|---|---|---|
| `normalization/quality.py` | **MINOR-FIX** | `QualityReport.incomplete_reason` + `.bounded`; `BOUNDED_CHECKS` |
| `database/migrations.py` | **BUILD-NEW** | schema **v5** — `blocks.incomplete_reason`, `blocks.capture_floor` |
| `database/repositories.py` | **MINOR-FIX** | `save()` takes and stores both |
| `database/writer.py`, `pipeline/writer.py` | **MINOR-FIX** | both capture paths pass the reason; selective passes the floor |
| `database/analytics.py` | **MINOR-FIX** | `HeightWindow.selective_blocks` / `unfetched_blocks` / `capture_floor` / `all_captured` |
| `skills/base.py` | **MINOR-FIX** | `supports_bounded_absence`, `absence_floor`, `supports_absence_above()`; corrected `limitation` |

### Decisions, each with its reason

- **The reason is stored, not derived.** A block whose transactions were all
  dropped at a floor is indistinguishable, by inspection, from one fetched
  without expansion. Only the capture knows, so if it does not say, nothing
  later can.
- **Stored as the check names themselves**, comma-separated
  (`"logs_captured,selective_capture"`). A second vocabulary for the same facts
  is a translation layer that drifts, and the names are already stable
  identifiers.
- **`BOUNDED_CHECKS` is deliberately narrow** — `selective_capture` alone.
  Being wrong in that direction licenses a claim the data cannot carry.
  `provenance` was left out: a block that cannot be cited is a weaker record
  whatever else it contains.
- **An empty reason on an incomplete block is *not* bounded.** That is every row
  written before v5, and the truthful reading is "incomplete, and nobody
  recorded why" — exactly the case a negative claim must not rest on. Old data
  therefore gains nothing, which is correct.
- **The floor is padded text and the window takes `MAX()`.** Unpadded, `MAX()`
  returns the longest string, so a floor of 9 wei would outrank one of 10 ether
  and the window would claim a *stronger* absence than it holds. Highest, not
  mean or latest: one hour of raised floor under budget pressure bounds the
  whole window.
- **An empty block is never stamped with a floor.** Nothing was filtered, so
  nothing was dropped. Stamping it would let an empty block raise a window's
  floor and narrow every claim drawn from it.
- **`supports_absence` stays strict and stays the default.** The bounded form
  needs a value named to use it. A bounded claim read as unbounded is the
  failure; the reverse costs only a claim that could have been made.
- **Classification is in Python, not SQL.** `window()` groups by reason — a
  handful of rows whatever the chain's height — and buckets them against
  `BOUNDED_CHECKS`. Policy written into a `CASE` expression is policy nobody
  can find.

### One existing test had to change

`test_a_v1_database_upgrades_without_losing_blocks` staged its "old" database by
writing through today's `RecordWriter`, which now names v5 columns against a v1
schema. The staging insert is now v1's own column list. The test's subject is
the migration, and it was breaking on the wrong thing.

### Verified by execution

| Check | Result |
|---|---|
| `pytest -q` | **924 passed, 0 failed** (was 908; 16 new) |
| `cli doctor` | 14/14 ok, `storage ok — schema v5`, exit 0 |
| live `ingest --selective`, base, 12 blocks | 1,700 tx seen, 1 kept (0.06%) |
| migration on a copy of `a01.db` (v2, 77 eth blocks) | → v5, 45/32 split intact |
| migration on a copy of `live_selective.db` (v3, 230 base blocks) | → v5, no data lost |

The live 12-block window, read back through `Coverage`:

```
selective_blocks         : 12      unfetched_blocks: 0
supports_absence         : False   <- unchanged, and correct
supports_bounded_absence : True    <- new
absence_floor            : 1000000000000000000
limitation: 12 of 12 blocks were captured selectively at a floor of
            1000000000000000000; an absence is evidence at or above that
            floor, not below it
```

Before this change the same window reported *"12 of 12 stored blocks are
incomplete; their transfers were never fetched"* and licensed nothing.

### Self-critique

- **No consumer reads the bounded form yet.** `wallet_lookup/profile.py`,
  `SubjectComposer`, `decision/recommendations.py`, the dashboard card and
  `telemetry/metrics.py` all still ask `supports_absence` and still get False.
  They inherit the corrected *message* immediately and the corrected *gate* not
  at all. That was scoped deliberately — the gate change is one decision per
  consumer about what a floor means for its own question — but until it lands,
  the practical win is honesty in the limitation line, not a detector that
  answers more.
- **Only new captures benefit.** The 230 selectively captured blocks already in
  `live_selective.db` carry no reason and stay classified as unfetched. That
  window also fails contiguity (230 blocks across a span of 18,578), so nothing
  is lost today, but the general point stands: this is a forward fix.
- **`logs_captured` is treated as unbounded, which is stricter than the truth.**
  A refused log read costs token and NFT transfers; the native transfers in that
  block were still captured whole. A finer model would bound the claim per
  record kind rather than per block. Erring strict here is the safe direction,
  but it is an approximation and it is now the reason a `--tokens` run with one
  refused fetch closes a window that could still answer for native value.

### Next session should start at

1. Decide, per consumer, what a bounded absence means for its question — the
   dormancy skill is the clear first one ("no material movement above X"), and
   it is where the corrected gate actually changes an answer.
2. Then the original queue: aggregate `CallResult.attempts` into
   `CallBudget.spend()` at `ChainDispatcher.call`'s return path, and rebuild the
   3,600-block base window.

---

## Session 2026-08-12 (later) — the call ledger gets a writer

### Goal

Step 2 of the queue above, first half: wire `CallBudget` to the real call path.
The ledger has been built, tested and unwritten-to since the sixth session. A
budget nothing writes to is a table, not a budget.

### The seam

The two constraints were already recorded and they point in opposite
directions. The count only exists in `blockchain/rpc/clients/dispatch.py` —
that is where requests actually leave the process. The ledger only exists in
`pipeline/budget.py` — that is storage, and the transport must not grow a
storage dependency to reach it.

So the transport now *reports* rather than records:

```
SpendSink = Callable[[str, str, int], None]     # (chain, provider, calls)
```

Three primitives, deliberately. The type is what keeps the layers apart, and a
signature made of strings and an int cannot quietly acquire an import later.
`CallBudget.recorder()` builds the other end.

### What changed

| File | Tag | Change |
|---|---|---|
| `blockchain/rpc/clients/dispatch.py` | **BUILD-NEW** | `SpendSink`; `ChainDispatcher(on_spend=...)`; `_report_spend()` |
| `blockchain/rpc/clients/dispatch.py` | **MINOR-FIX** | `CallResult.provider_attempts` — requests that actually went out, per provider |
| `blockchain/rpc/clients/__init__.py`, `rpc/__init__.py` | **MINOR-FIX** | export `SpendSink` |
| `pipeline/budget.py` | **BUILD-NEW** | `CallBudget.recorder()` |
| `pipeline/budget.py` | **MINOR-FIX** | `spend()` docstring now states where it is actually called from |
| `cli/main.py` | **MINOR-FIX** | `ingest` opens the database first, builds the dispatcher with the sink, prints the ledger |

### Decisions, each with its reason

- **`provider_attempts` is a new field, not a read of `failures`.** `failures`
  also holds candidates the local limiter refused, and a request that never
  left the process cost the provider nothing. Charging for those would make
  throttling look like usage and close a budget on a chain that was never read.
  `BUDGET_EXHAUSTED` is therefore the one outcome that reports an empty tuple.
- **Counted before the response, reported after the read.** The increment sits
  immediately before `_execute`, so a call that then times out is still spent —
  the sixth session's "attempts, not successes" survives intact. The *report*
  happens once per provider on `call`'s return path, so one logical read is one
  ledger write instead of one per retry. What that costs is a process killed
  mid-read: those requests reached the provider and go uncounted. The
  alternative costs a database write on the hot path of every retry, in exactly
  the 429 storms this ledger exists to survive. The undercount is bounded by
  one read; the alternative's cost is not bounded at all.
- **A sink that raises does not lose the answer.** The chain read is already in
  hand when the sink runs. It is logged at `exception` level rather than
  swallowed, because a ledger that silently stops recording reports headroom
  that does not exist — which is the failure mode the whole module is built
  against.
- **The database opens before the transport in `cli ingest`.** It has to: the
  ledger lives in the capture database and the dispatcher takes its sink at
  construction. A sink installed after the first call is a sink that missed a
  call, and the first call of a run is the head read — the one most likely to
  be the call that runs a free tier out.
- **No ceilings were configured.** Nothing in the provider catalog carries a
  per-day or per-month figure, and alchemy's free tier meters compute units,
  not calls. Inventing a number here would produce confident throttling with no
  basis — the sixth session's own decision. So every provider reads `UNKNOWN`
  and none is throttled. What the wiring buys today is the *measurement*, which
  is the thing that has to exist before any ceiling can be believed.
- **`check()` is still not consulted before a call.** With no ceiling known,
  every verdict is `allowed`, so consulting it would add a code path that
  cannot fail and cannot be tested against a real refusal.

### Verified by execution

| Check | Result |
|---|---|
| `pytest -q` | **937 passed, 0 failed** (was 924; 13 new) |
| `cli doctor` | 14/14 ok, schema v5, exit 0 |
| live `ingest --selective`, base, 5 blocks | 7 calls each to alchemy and base-official, ledgered |
| the same command again, 3 blocks, new process | 7 → **12** each; the ledger survived the process |

```
budget     : alchemy 12 call(s) today, 12 this month (no ceiling known)
budget     : base-official 12 call(s) today, 12 this month (no ceiling known)
```

Fourteen calls for five blocks, split across two providers — which is also the
first time the per-block call cost of selective capture has been visible at all.

### Self-critique

- **Only `cli ingest` is wired.** Every other entry point — the API routes, the
  skills, `cli investigate`, `cli wallet` — builds its dispatcher through
  `SensorRegistry()` with no sink and spends silently. The ledger therefore
  undercounts A01's real usage by however much those paths read. `ingest` is
  the path that spends at volume, so this is the right first one, but the
  budget's own honesty rule says an undercount must be named: it is named here.
- **The 429 signal is still not connected.** `_dispatch` already detects a
  provider's 429 and penalises the local limiter, and `observe_rejection()`
  exists to turn that same event into a lowered ceiling. They are not joined,
  because a 429 from a per-second burst and a 429 from an exhausted daily quota
  are indistinguishable at this seam, and reading the first as the second would
  permanently cripple a believed daily ceiling on a burst that the limiter
  already handled. Joining them needs a discriminator that does not exist yet.
- **Nothing reads the ledger except a print.** It accumulates and it is
  displayed. No capture decision consults it, which is the correct state while
  every ceiling is unknown, and the wrong state the moment one is not.

### Next session should start at

1. The bounded-absence consumer decision, still item 1 from the previous
   session — the dormancy skill first.
2. Rebuild the 3,600-block base window. Not an implementation task: it is a
   sustained live capture, and rate limits, not code, are what stopped the last
   two attempts. The ledger now measures what it costs while it runs.

---

## Session 2026-08-14 — 15-chain restructure + terminal depth (Step 5)

### Goal for this session

Complete Step 5 of the handoff plan: create a `chains/` directory structure with
one numbered directory per chain (01–15), each containing `README.md`,
`endpoints.yaml`, `limits.yaml`, and `adapter.py`. Bitcoin gets its own UTXO
adapter shape. This is the final implementation step; Steps 1–4 were already
DONE.

### What was built

**Base adapter module** (`chains/__init__.py`, `chains/base.py`):

- `ChainAdapter` (abstract base) with properties: `chain`, `chain_type`,
  `sensor_family`, `is_account_based`, `is_utxo`, `has_sensor`.
- `EvmAdapter(ChainAdapter)` — for 13 EVM chains. `is_account_based=True`,
  `has_sensor=True`, `sensor_family="evm"`.
- `UtxoAdapter(ChainAdapter)` — for Bitcoin. `is_account_based=False`,
  `is_utxo=True`, `has_sensor=False`, `sensor_family="utxo"`. Docstring
  explains five concrete reasons the EVM account model produces wrong output
  on UTXO chains.
- `SolanaAdapter(ChainAdapter)` — for Solana. `has_sensor=False`,
  `sensor_family="solana"`. Notes slots-vs-blocks difference.

**15 numbered directories** (`chains/01_ethereum/` through `chains/15_bitcoin/`),
each containing:

| File | Contents |
|---|---|
| `__init__.py` | empty (package marker) |
| `adapter.py` | imports from `chains.base`, creates adapter instance |
| `endpoints.yaml` | all providers from catalog; access level, archive, logs, rate_limit; API key fields **empty** with `env_var` naming convention |
| `limits.yaml` | chain_type, has_sensor, finality, reorg_depth, block_time, constraints list — sourced from `knowledge/chains.py` |
| `README.md` | chain properties table, what A01 can do on this chain, provider count, known limits |

60 files in chain directories + 2 in `chains/` root = 62 new files.

**Terminal depth** — `cli chains` updated to reference the per-chain directory
structure: `"Per-chain details: chains/<number>_<chain>/ (README.md,
endpoints.yaml, limits.yaml, adapter.py)"`.

**17 new tests** (`chains/tests/test_chains.py`):

- All 15 directories exist with the four required files
- Chain order matches `ChainName` registry
- Endpoints/limits YAML have required fields and providers
- All adapters importable as `ChainAdapter` instances
- EVM chains use `EvmAdapter` with correct properties
- Solana uses `SolanaAdapter`, `has_sensor=False`
- Bitcoin uses `UtxoAdapter`, `is_utxo=True`, `is_account_based=False`,
  `has_sensor=False`
- Chain names match between YAML, adapters, and directories
- No API keys in endpoint files
- READMEs exist and mention observability

`pytest.ini` updated to include `chains` in testpaths.
`test_architecture.py` updated to include `"chains"` in the `UNRANKED` set.

### Design decisions

1. **The 15 chains are the existing 15 in the registry.** TRON, Sui, TON,
   Aptos, NEAR, Cosmos are not in the registry — they are aspirational, not
   part of Step 5.
2. **Thin per-chain adapters that import from the base.** The existing sensor
   registry and dispatcher handle actual chain interaction; adapters are the
   structured metadata and type-safety layer.
3. **Bitcoin gets `UtxoAdapter`, not `EvmAdapter`.** No accounts with balances,
   no event logs, common-input-ownership is probabilistic. The adapter and
   README document why EVM assumptions produce wrong output.
4. **Solana gets `SolanaAdapter`.** Slots differ from blocks, RPC dialect is
   different. No sensor exists yet — `has_sensor=False`.
5. **endpoints.yaml uses `env_var` references.** No credential appears in any
   tracked file. `.env.local` remains the only place for keys.

### Bugs found and fixed

1. **PyYAML not installed.** `ModuleNotFoundError: No module named 'yaml'`
   when running tests. Fixed by rewriting `test_chains.py` to use regex-based
   YAML parsing (`_read_yaml_field`, `_yaml_has_field`, `_count_providers`)
   instead of `yaml.safe_load`. Zero new dependencies.
2. **YAML comment in parsed value.** `_read_yaml_field` returned
   `"bitcoin_like  # UTXO, NOT account-based"` instead of `"bitcoin_like"`.
   Fixed by stripping inline comments: `if "#" in val: val = val[:val.index("#")].strip()`.

### Verified by execution

| Check | Result |
|---|---|
| `pytest -q` | **1,101 passed, 0 failed** (was 937; 164 new across Steps 3–5) |
| `cli doctor` | **14/14 ok**, schema **v7**, exit 0 |
| `cli chains` | **15** chains registered, 13 observable, 13 token-capable |

### Self-critique

- **Adapters carry no runtime behaviour.** They are structured metadata — the
  sensor registry and dispatcher still do the actual RPC work. This is correct
  for now (a `UtxoAdapter.fetch_utxos()` with no Bitcoin sensor to back it would
  be dishonest), but it means `adapter.py` adds type safety and documentation,
  not functionality.
- **`has_sensor=False` for Solana and Bitcoin is stated, not enforced.** If
  someone later writes a Solana sensor and forgets to update the adapter, the
  adapter's claim that no sensor exists becomes a lie. No test guards against
  this because the sensor registry is dynamic and chain-sensor mapping is
  convention, not registration.
- **The YAML files are not machine-validated beyond regex.** Without PyYAML in
  the dependency tree, the tests check field presence and basic structure but
  cannot validate full YAML schema. A malformed YAML file that happens to match
  the regexes would pass.

### Next session should start at

1. Run PROMPT 2 (final audit) — 7 checks with evidence, plus Section 19
   criteria assessment.
2. Three decisions left on purpose: wire labels to whale skill, attribute
   token transfers, connect exchange flow to a detector.
