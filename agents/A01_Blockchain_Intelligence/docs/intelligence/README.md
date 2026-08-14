# Intelligence Tradecraft Documentation

## A01 Blockchain Intelligence Agent

**Project:** CIE-OS (Crypto Intelligence Engine Operating System)
**Document Type:** Tradecraft Index
**Version:** 1.0.0

---

# 1. What This Directory Is

`docs/architecture/` describes **how A01 is built**.
`identity/` describes **what A01 is for**.
**This directory describes how A01 thinks** — the analytical rules that decide
what it may claim, on what evidence, with what confidence, and where it must
refuse to conclude.

These documents are **normative**. Code that contradicts them is a defect even
if its tests pass. That is a deliberately strong statement, and it exists
because the failure mode here is not a crash — it is a confident, well-formatted,
wrong accusation about a real person or organisation.

---

# 2. Reading Order

Read in sequence. Each builds on the previous.

| # | Document | Answers |
| --- | --- | --- |
| 1 | [attribution-doctrine.md](attribution-doctrine.md) | What may A01 claim about who someone is? |
| 2 | [evidence-standard.md](evidence-standard.md) | What counts as proof, and how is it recorded? |
| 3 | [detection-catalog.md](detection-catalog.md) | How does each detection actually work? |
| 4 | [threat-model.md](threat-model.md) | Who attacks A01, and how? |
| 5 | [future-problems.md](future-problems.md) | What breaks next, and what do we do now? |

---

# 3. The Four Rules

Everything in these documents reduces to four commitments.

## 3.1 Separate the layers of attribution

Co-ownership (mechanical), behavioural class (statistical), and real-world
identity (external) are three different claims with three different
evidentiary bars and three different confidence ceilings — 0.95, 0.75, and
0.40. Conflating them is the field's most common and most damaging error.

## 3.2 Every conclusion is grounded and falsifiable

Every claim terminates in protocol facts or recorded external sources. No claim
supports itself. Contradicting evidence is retained, not discarded. Every
detector states what observation would retract its conclusion.

## 3.3 Confidence is a measurement, not a mood

A claim at 0.80 should be correct about 80% of the time. This is checkable, and
A01 commits to checking it. Correlated evidence does not stack. Layer ceilings
are absolute and cannot be exceeded by accumulating weak signals.

## 3.4 Untrusted data never becomes trusted by moving inward

Chain data is attacker-writable by design. A token name remains untrusted after
it is stored, summarised by a model, and read by another agent. Trust attaches
to provenance, not to location.

---

# 4. Relationship to Code

Each document ends with an **implementation status table** measured against the
working tree. Those tables are the intelligence backlog — read together they
give the honest position:

> A01's infrastructure is substantial (`memory/` 34k lines, `tools/` 22k,
> `planning/` 17k). Its analytical core is a scaffold: `intelligence/` averages
> 69 lines per file, and the three packages carrying A01's central promises —
> `evidence`, `attribution`, `verification` — are among its smallest.

The tradecraft is specified here **before** it is built, deliberately. Writing
the doctrine after the code means the code becomes the doctrine, and the
confidence ceilings and refusal conditions never get written at all.

---

# 5. Cross-Cutting Priorities

Consolidated from the individual backlogs, ordered by risk:

| # | Item | Source | Why first |
| --- | --- | --- | --- |
| 1 | Untrusted-data fencing in reasoning | Threat §3.1 | Novel, high-impact, absent |
| 2 | AI output grounding check | Evidence §6 | Bounds hallucination and injection damage |
| 3 | Layer confidence ceilings | Attribution §2 | Prevents confident false accusation |
| 4 | Error-rate declarations | Evidence §2.1 | Unblocks honest confidence everywhere |
| 5 | CoinJoin / collaborative-tx exclusion | Attribution §3.1 | Prevents invalid clustering |
| 6 | Cluster-collapse circuit breaker | Attribution §3.2 | One bad merge contaminates thousands of conclusions |
| 7 | SSRF allowlist + redirect revalidation | Threat §3.3 | Standard control, currently absent |
| 8 | `evaluation/` backtesting harness | Detection §7.3 | **Nothing can reach `Validated` without it** |
| 9 | `UserOperation` as first-class object | Future §2 | Cheap now, migration later |
| ✅ | ~~`SecretValue` serialisation block~~ | Threat §3.4 | **Done** — redaction was bypassable via `asdict` |

Items 1–2 and 7 are security. Items 3–6 are analytical integrity. Item 8 is the
structural blocker: with `evaluation/` empty, no A01 capability can be
validated, so every detector is permanently capped at 0.60 confidence.

---

# 6. Maintenance

- These documents are versioned with the code and reviewed together with it.
- Implementation status tables must be updated in the same change that alters
  the corresponding code. A stale status table is worse than none, because it
  is trusted.
- `future-problems.md` carries explicit review triggers (§10); check them at
  each review rather than relying on the six-month cadence alone.

---

**End of Tradecraft Index**
