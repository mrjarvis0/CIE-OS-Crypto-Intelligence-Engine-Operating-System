# Deployment Runbook

## A01 Blockchain Intelligence Agent

**Project:** CIE-OS (Crypto Intelligence Engine Operating System)
**Document Type:** Operations — Normative
**Version:** 1.0.0
**Status:** Authoritative — every command here is exercised by the test suite

---

# 1. What A01 Is, Operationally

A **read-only, operator-driven** intelligence agent. It holds no keys, signs
nothing, and has no write path to any chain. It does not run as a daemon: a
human or a scheduler drives ingestion, and everything else is a query over what
ingestion has stored.

That shape determines the whole runbook. There is no service to keep alive, no
queue to drain on shutdown, and no in-flight state to lose — the failure modes
are all about **data**: is it there, is it complete, and can it be recovered.

---

# 2. Prerequisites

| Requirement | Detail |
| --- | --- |
| Python | ≥ 3.12 (`StrEnum`, PEP 604 unions, `datetime.UTC`) |
| Schema | v2. A v1 database upgrades forward automatically, without data loss |
| Dependencies | `pydantic`, `pydantic-settings`, `aiosqlite`; see repo-root `requirements.txt` |
| Disk | ~200 KiB per Ethereum block with transactions expanded |
| Network | Outbound HTTPS to public RPC endpoints; no inbound required |

Running the system Python is the most common setup error: it reports a
`settings load` failure and three uncollectable memory test modules, which
looks like a broken agent rather than a wrong PATH.

Name the interpreter once, in a `.env.local` beside the agent:

```ini
A01_PYTHON=C:\path\to\.venv\Scripts\python.exe
```

`scripts/a01.bat` and `scripts/install-task.ps1` both read it. A virtualenv is
not always an ancestor of the agent — in the CIE-OS layout it is in a separate
tree — so an upward search alone cannot find it.

## 2.1 Credentials

Provider keys are read from the **process environment**, not from a settings
object. A `.env.local` or `.env` in the agent directory or up to three levels
above it is loaded into that environment at startup:

```ini
# ALCHEMY_API_KEY=...
# ETHERSCAN_API_KEY=...
```

An exported variable always wins over the file, so a stale checked-out `.env`
cannot silently defeat a deliberate export. Values never appear in logs or
diagnostics — only variable names.

```bash
python -m cli providers
```

Reports every provider as `usable`, `keyed`, or `dormant`, and names the
variable each dormant one needs. A01 runs on free endpoints without any key;
keys widen the pool and raise the rate limits.

---

# 3. Pre-Flight

Run before every deployment and after every configuration change:

```bash
python -m cli doctor
```

Thirteen checks must be `ok`. Three deserve reading rather than skimming:

| Check | What a pass means |
| --- | --- |
| `decision gate` | `0 may alert` is **correct**. No detector has a measured error rate, so none may alert. A non-zero count means a detector was promoted — verify it was backtested first. |
| `skills` | Skills decline cleanly with no history, rather than inventing an answer. |
| `credentials` | Names the `.env` that was loaded and how many keyed providers are active. Zero is a supported state — A01 runs on free endpoints — but if you added a key and see zero, the file was not found. |

An `interfaces` failure means a route raises rather than returning an error, and
is a defect, not a configuration problem.

---

# 4. Ingestion

Ingestion is a job, not a service.

On Windows, register it once:

```
powershell -ExecutionPolicy Bypass -File scripts\install-task.ps1 -Minutes 10 -Blocks 25
```

The installer runs `doctor` **before** registering, because a task that has
never worked fails silently every ten minutes and the first sign is an empty
database. Output goes to `logs/ingest.log`, rotated at 5 MB — a job on a
ten-minute timer runs about 52,000 times a year, and an unbounded log is how a
forgotten task fills a disk.

Or run it by hand:

```bash
python -m cli ingest --db data/a01.db --chain ethereum --blocks 50 --tokens
```

`--tokens` also captures ERC-20 and ERC-721 transfers from event logs. On
layer 2 it is not optional in practice: the largest native transfer in a
real Arbitrum block is routinely `0.0000`, so without it the chain looks
idle. It costs one extra RPC call per block, and log reads are the first
thing a free provider rate-limits — a failed log read is counted, never
fatal to the block.

Bounded by `--blocks` on purpose: an unbounded catch-up on a chain millions of
blocks behind is indistinguishable from a hang, and an operator can neither see
progress nor stop it cleanly. Run it more often rather than with a larger bound.

Progress is checkpointed to `<db>.checkpoints.json` after every block, so
interrupting the job and running it again **resumes** rather than restarting.
That is what makes it safe to put on a timer.

On the first run there is no checkpoint, so the job reaches back `--blocks`
behind the settled head. Afterwards it follows the head and reports
`caught_up` when there is nothing new — which is the normal steady state, not a
fault.

For a fixed historical range instead of following the head:

```bash
python -m cli ingest --db data/a01.db --backfill --start 21000000 --blocks 500
```

There is deliberately **no HTTP endpoint that triggers a fetch**. A
request-triggered ingest would put an unbounded, rate-limited job behind an
externally reachable call, which is a denial-of-service surface rather than a
feature.

## 4.1 Confirmation depth

The poller stays behind the head by its configured confirmation depth (12 by
default on Ethereum). Reducing it increases reorg exposure; the withdrawal path
handles reorgs correctly, but every withdrawal is work that need not have
happened.

## 4.2 Reading the outcome

| Signal | Meaning | Action |
| --- | --- | --- |
| `records_rejected` rising | A provider is serving malformed payloads | Check which field, in the writer's rejection list |
| `withdrawn_blocks` rising | Reorgs are being handled | Normal at low rates; investigate if sustained |
| `coverage_supports_absence` = 0 | Storage too shallow for negative findings | Backfill; see §7 |
| `orphaned_token_records` rising | Log capture is ahead of block capture | Usually transient; sustained means the two have drifted |

---

# 5. Serving

```bash
python -m cli serve --db data/a01.db
```

Binds `127.0.0.1:8801`. **The bind address is the security boundary** — there is
no authentication, so binding anything else publishes all ingested data to
whatever can reach the interface. The server logs a warning naming the exposure
when asked to do so; it will comply, and it will say what it is doing.

Routes are GET-only: `/health`, `/detectors`, `/skills`, `/metrics`,
`/coverage`, `/investigate`. Every write verb answers 405.

---

# 6. Backup and Recovery

## 6.1 Taking a backup

```bash
python -m cli backup --db data/a01.db
```

Uses SQLite's online backup API and verifies the result immediately.

**Never copy the database file with `cp` or a filesystem snapshot.** Under WAL
the committed state spans the database and its write-ahead log; a copy taken
mid-transaction captures one without the other. The resulting file usually
opens, often reads, and is wrong in a way that surfaces months later.

Exit code `2` means the backup was taken but failed verification — treat it as
no backup at all and investigate the source database.

## 6.2 Restoring

```bash
python -m cli restore --backup data/a01-ethereum-20260809T120000Z.db --db data/a01.db --overwrite
```

Refuses an unverified backup. `--overwrite` moves the incumbent aside with a
`.superseded-<timestamp>` suffix rather than deleting it — recovery is performed
under pressure, and the procedure must not destroy the last good copy. Stale
`-wal` and `-shm` files are cleared, because a leftover log describes a database
that no longer exists and SQLite would try to recover it against the new one.

## 6.3 Verifying a backup without restoring

```python
from telemetry import verify
print(verify("data/backup.db").as_dict())
```

## 6.4 Disaster recovery

| Scenario | Recovery |
| --- | --- |
| Database corrupted | Restore the most recent verified backup (§6.2), then re-ingest from the restored head |
| Database lost entirely | Re-ingest from scratch; history is public and A01 holds nothing unique |
| Backup fails verification | Fall back to an earlier backup; if none verifies, re-ingest |
| Provider serving bad data | Rejections rise and nothing is stored — the write path fails closed |
| Reorg mishandled | Withdrawn blocks are retained, so the fork is reconstructible from storage |

**A01's data is recoverable by construction.** Everything it stores is derived
from public chains, so the worst case is a re-ingest costing time rather than
information. This is a deliberate property, not luck — it is why nothing in the
system holds state that exists only here.

---

# 7. Coverage Management

The single most consequential operational fact: **a shallow database cannot
support a negative finding.** With less than 3,600 contiguous blocks stored, A01
reports "not determinable" rather than "did not happen", and it is right to.

```bash
curl -s http://127.0.0.1:8801/coverage | python -m json.tool
```

`supports_absence: false` with a stated reason means the window is the limiting
factor, not the detectors. Backfill until it flips.

---

# 8. What A01 Will Not Do

Verified by the test suite, not just documented:

* Raise an alert from a detector without a measured error rate
* State a negative finding the stored window cannot support
* Publish a narrative asserting a particular absent from the evidence
* Sign, submit, or construct a transaction
* Accept a write over any interface

If any of these ever happens, it is a defect of the first order.

---

# 9. Known Operational Limits

| Limit | Detail |
| --- | --- |
| No alerts | Every detector is `implemented`; alerting requires `validated`. Run `evaluation/` against a labelled window. |
| Address totals capped | Bounded at 50,000 rows and reported as a floor (`totals_are_floors`) |
| Native value only | ERC-20 transfers are event logs, which A01 does not decode |
| Seven EVM chains | Solana and Bitcoin are registry-only; no sensor for their dialects |
| Single writer | SQLite allows one writer; run one ingestion job per database |

---

# 10. Escalation

A01 provides evidence, not decisions. Every conclusion carries a
`falsified_by` naming what would retract it, and the determination belongs to a
human analyst. An operator should never act on an A01 output without reading its
binding constraint and coverage.
