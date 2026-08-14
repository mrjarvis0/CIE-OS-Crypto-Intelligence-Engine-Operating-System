# Evidence Standard

## A01 Blockchain Intelligence Agent

**Project:** CIE-OS (Crypto Intelligence Engine Operating System)
**Document Type:** Analytical Tradecraft — Normative
**Version:** 1.1.0
**Status:** Authoritative
**Implements:** `intelligence/evidence/`, `intelligence/verification/`, `intelligence/reporting/`

---

# 1. The Standard A01 Is Built To

A01's mission document commits to explaining every conclusion. That commitment
is meaningless unless "explanation" has a defined bar. This document sets it.

A01 targets **forensic-grade evidence**: output that could survive hostile
review. The reference framework is the *Daubert* standard, which US courts apply
to expert testimony and which the blockchain forensics industry has adopted as
its quality bar. Not all blockchain analytics tools produce Daubert-admissible
output; the difference is methodology documentation and validation, not data
volume.

A01 does not claim its output *is* admissible — that is a determination for a
court, and it depends on the analyst presenting it. A01 claims that its output
is **structured so that admissibility is achievable**, which is the most a
software system can honestly offer.

> **Design consequence:** if a feature cannot produce a defensible evidence
> chain, it does not ship as intelligence. It may ship as an *indicator* or a
> *hypothesis*, which are separate, clearly-labelled output categories.

---

# 2. The Four Daubert Criteria, Mapped to A01

| Criterion | What it demands | A01's obligation |
| --- | --- | --- |
| **Testability** | The method can be tested and falsified | Every heuristic is a named, versioned, independently-runnable unit with fixture cases |
| **Known error rate** | Documented accuracy and limits | Every detector publishes measured or stated FP/FN rates; unmeasured is declared as such |
| **Peer review** | Subjected to outside scrutiny | Heuristics cite public research or are marked `proprietary: unreviewed` |
| **General acceptance** | Recognised in the field | Deviations from standard practice are documented with rationale |

The fourth criterion has a subtle consequence: **A01 may not silently invent
heuristics**. If it applies a novel method, the novelty must be explicit in the
output so a reviewer can weigh it, rather than discovering it under
cross-examination.

## 2.1 The error-rate obligation is the hard one

Most analytics systems fail here. Stating "we don't know our error rate" is
weak; *not knowing you don't know* is disqualifying. A01 therefore requires
every detector to carry one of three error-rate states:

- `measured` — with sample size, date, and methodology
- `stated` — inherited from cited research, with the citation
- `unmeasured` — explicitly flagged, and the detector's output is capped at
  0.60 confidence until measured

There is no fourth state. A detector without an error-rate declaration fails
schema validation and cannot register with the intelligence pipeline.

---

# 3. Evidence Taxonomy

Not all evidence is the same kind of thing. A01 distinguishes four types,
because they fail differently and must be weighted differently.

## 3.1 Type P — Protocol facts

Statements guaranteed by chain consensus. "Transaction `0xabc` transferred
100 USDC from A to B in block 19,000,000."

- **Failure mode:** reorg, or the node lied.
- **Verification:** confirmation depth ≥ chain's configured `confirmations`
  (see `config/rpc/chains.py`), plus multi-provider agreement for high-stakes
  claims.
- **Decay:** none. A finalised protocol fact is permanent.
- **Max confidence:** 1.0 after finality.

## 3.2 Type D — Derived facts

Computed from protocol facts by deterministic transformation. "Address A's
balance decreased 40% over 7 days."

- **Failure mode:** computation bug, incomplete data range, missing internal
  transactions or token transfers.
- **Verification:** recomputation from source must reproduce the value exactly.
- **Decay:** none for the stated window; the *relevance* decays, not the fact.
- **Max confidence:** 0.99. Never 1.0 — that reserve acknowledges bug risk.

**The internal-transaction trap.** A balance computed from external
transactions alone is wrong for any address that receives via contract calls.
Type D evidence must declare its data completeness: which transfer types were
included. This is one of the most common silent-corruption sources in
blockchain analytics.

## 3.3 Type I — Inferred conclusions

Produced by heuristics. "This cluster is an exchange hot wallet."

- **Failure mode:** heuristic assumption violated; adversary gaming.
- **Verification:** the heuristic's own error rate applies.
- **Decay:** yes, per the half-lives in `attribution-doctrine.md` §4.1.
- **Max confidence:** the layer ceiling.

## 3.4 Type E — External assertions

From outside the chain. Labels, documentation, news, sanctions lists.

- **Failure mode:** source wrong, stale, spoofed, or adversarially planted.
- **Verification:** source identity, retrieval timestamp, content hash.
- **Decay:** source-specific.
- **Max confidence:** the source's weight (`attribution-doctrine.md` §5.1).

## 3.5 The mixing rule

**A conclusion inherits the weakest type in its chain.** A Type I conclusion
resting on Type E evidence is bounded by that Type E weight. This propagates
automatically through `intelligence/evidence/chain.py` and must not be
overridable by callers.

---

# 4. Provenance: The Non-Negotiable Fields

Every evidence record carries:

```
{
  "evidence_id":     "<stable, content-addressed>",
  "type":            "P" | "D" | "I" | "E",
  "claim":           "<the assertion, in one sentence>",
  "source": {
    "kind":          "rpc" | "indexer" | "api" | "document" | "analyst",
    "identity":      "<provider name / URL / analyst id>",
    "endpoint":      "<sanitised — credentials stripped>",
    "retrieved_at":  "<ISO-8601 UTC>",
    "content_hash":  "<sha256 of the raw payload>"
  },
  "chain_context": {
    "chain":         "<chain name>",
    "block_height":  <int>,
    "block_hash":    "<hash>",
    "finality":      "pending" | "probabilistic" | "final",
    "confirmations": <int>
  },
  "derivation":      ["<parent evidence_ids>"],
  "method":          "<heuristic name @ version, or 'observation'>",
  "completeness":    ["external", "internal", "erc20", "erc721", "..."],
  "confidence":      0.0-1.0,
  "error_rate":      {"state": "measured|stated|unmeasured", "value": <float|null>, "citation": "<...>"},
  "contradicts":     ["<evidence_ids>"],
  "expires_at":      "<ISO-8601 UTC or null>"
}
```

## 4.1 Content addressing and reproducibility

`evidence_id` is derived from a canonical hash of the claim plus source plus
chain context. Two independent runs observing the same fact produce the same
id. This gives A01 deduplication for free and, more importantly, makes
**reproducibility checkable**: a reviewer can re-run the pipeline and compare
evidence ids.

`content_hash` covers the *raw* provider payload before normalisation. Without
it, "the API said so" is unfalsifiable, and A01 cannot later prove whether a
provider changed its answer.

## 4.2 Credential hygiene in provenance

`source.endpoint` is operator-facing and lands in logs, reports, and possibly
external outputs. RPC URLs routinely embed API keys as path segments
(`https://eth-mainnet.example.com/v2/<API_KEY>`). Provenance capture must strip
credentials before storage, not at render time — once a secret is written to
the evidence store it must be treated as leaked.

This is a security requirement, not a formatting preference. It is enumerated
in `threat-model.md` §6.

---

# 5. The Chain of Custody

A01's evidence chain is a **directed acyclic graph**, not a list. A conclusion
points to its parents; parents point to theirs; leaves are Type P or Type E.

Three invariants, enforced in `intelligence/evidence/evidence_graph.py`:

1. **Acyclicity.** A cycle means a claim supports itself. Reject on insert.
2. **Leaf grounding.** Every path terminates in Type P or Type E. A chain that
   bottoms out in another inference is incomplete and must not be published.
3. **Correlation collapse.** Before combining, evidence sharing a common
   ancestor is collapsed to a single contribution (see
   `attribution-doctrine.md` §7.2, Rule 1).

## 5.1 Reproducibility levels

Every published conclusion declares one:

| Level | Meaning |
| --- | --- |
| `deterministic` | Re-running on the same chain state yields identical output |
| `stable` | Same output modulo timestamps and ordering |
| `stochastic` | Contains sampling or model non-determinism; seed recorded |
| `non-reproducible` | Depended on a source that does not preserve history |

`non-reproducible` conclusions may be published but must be visually marked in
reports. A01's mission commits to reproducibility; where it cannot deliver, it
says so rather than quietly degrading.

---

# 6. Handling AI-Generated Reasoning

A01 uses LLM reasoning in `intelligence/reasoning/`. This is the sharpest
evidentiary risk in the system, because model output is fluent, confident, and
unfalsifiable by inspection.

**Doctrine: AI output is never Type P or Type D. It is at best Type I, and it
is never a leaf.**

Concretely:

- A model may **structure, summarise, and explain** evidence.
- A model may **propose hypotheses** for testing.
- A model may **never introduce a factual claim** that is not already present in
  the evidence chain. Any fact appearing in AI output but absent from the
  evidence graph is a hallucination by definition, and
  `intelligence/verification/` must detect and strip it.
- Model reasoning carries `method: "<model-id>@<version>"` and
  `reproducibility: stochastic` with the seed and temperature recorded.

**The grounding check.** Before an AI-authored narrative is published, every
factual assertion in it must map to an `evidence_id`. Unmappable assertions
block publication. This check is the difference between "AI-assisted
intelligence" and "plausible text about blockchains".

---

# 7. Presenting Uncertainty

A01's ethical principles require distinguishing fact from inference and
communicating uncertainty. That requires vocabulary discipline, because natural
language silently upgrades confidence.

| Confidence | Permitted verbs | Forbidden |
| --- | --- | --- |
| 0.90–1.00 | "is", "did", "transferred" | — |
| 0.70–0.89 | "almost certainly", "strongly indicates" | "is", "confirmed" |
| 0.50–0.69 | "likely", "appears to" | "shows", "proves" |
| 0.30–0.49 | "possibly", "consistent with" | "likely", "indicates" |
| 0.00–0.29 | "cannot be determined", "insufficient evidence" | any assertive verb |

**`decision/vocabulary.py` owns enforcement** (moved there in v1.1 of this
document; previously assigned to `intelligence/reporting/`). The table lived
with the renderer while there was one renderer. There are now several — the CLI,
the REST API, any future dashboard — and a rule enforced in each renderer is
enforced in none of them: the next surface added is the one that forgets.

The verb is therefore bound where a conclusion is *formed*. `Conclusion.qualifier`
is derived from confidence and cannot be supplied by a caller, and every renderer
prints the verb it was given. `decision.vocabulary.enforce` raises on a violation
rather than softening the wording, because quietly rewriting the text would hide
a defect in whatever produced it.

A renderer that emits "is" for a 0.55-confidence claim is a defect — it launders
an inference into a fact, which is precisely what the mission's ethical
principles prohibit.

## 7.1 Confidence must not be averaged away

A report combining a 0.95 fact and a 0.30 inference must not present "0.62
confidence". Report the *distribution*, or report the binding constraint. An
averaged confidence hides that the conclusion rests on a weak link.

Implemented as `decision.vocabulary.binding_constraint`, which returns the
lowest-confidence contributor and its source. `Conclusion` and `Decision` carry
that instead of a mean, and the CLI renders it under BINDING CONSTRAINT.

---

# 8. Retention, Immutability, and Correction

- Evidence records are **append-only**. Corrections create a new record that
  `supersedes` the old one; the old one is retained.
- Retracted conclusions are marked `retracted` with a reason, never deleted.
  Downstream consumers that already ingested them need the retraction.
- Retention must satisfy the longest applicable requirement among the
  jurisdictions the operator works in — a deployment concern, but the schema
  must support it via `retention_class`.

**Why append-only matters here:** if A01's evidence store can be silently
rewritten, then no conclusion it produced in the past can be defended, because
the record could have been altered after the fact. Immutability is what makes
the chain of custody a chain.

---

# 9. Current Implementation Status

Against `intelligence/evidence/` as it exists (599 lines, 9 files):

| Requirement | Status | Notes |
| --- | --- | --- |
| Evidence type taxonomy (P/D/I/E) | ❌ | No type discrimination |
| Full provenance fields | ⚠️ Partial | `provenance.py` exists; lacks content hash, completeness, error rate |
| Content-addressed ids | ❌ | — |
| DAG acyclicity check | ❌ | `evidence_graph.py` has no cycle detection |
| Leaf grounding | ❌ | — |
| Correlation collapse | ❌ | `confidence.py` combines naively |
| Error-rate declarations | ❌ | No detector declares one |
| AI grounding check | ❌ | `intelligence/verification/` is a 346-line stub |
| Confidence vocabulary | ❌ | `intelligence/reporting/` is a 315-line stub |
| Credential stripping | ❌ | Not implemented |
| Append-only semantics | ❌ | — |

**Build order.** Error-rate declarations and the AI grounding check come first:
the former unblocks honest confidence, the latter prevents the most damaging
failure mode (fabricated facts presented as intelligence). Provenance
completeness follows, then the DAG invariants.

---

## Sources

- [Chainalysis — Blockchain forensics, process and Daubert standard](https://www.chainalysis.com/glossary/blockchain-forensics/)
- [TRM Labs — Fundamentals of cryptocurrency transaction tracing](https://www.trmlabs.com/resources/blog/the-fundamentals-of-cryptocurrency-transaction-tracing)
- [Argumentation Schemes for Blockchain Deanonymization](https://arxiv.org/pdf/2305.16883)
- [Elliptic — Investigator / blockchain forensics](https://www.elliptic.co/solutions/investigations)

---

**End of Evidence Standard**
