# Attribution Doctrine

## A01 Blockchain Intelligence Agent

**Project:** CIE-OS (Crypto Intelligence Engine Operating System)
**Document Type:** Analytical Tradecraft — Normative
**Version:** 1.0.0
**Status:** Authoritative
**Implements:** `intelligence/attribution/`, `intelligence/correlation/`, `intelligence/graph/`

---

# 1. Why This Document Exists

Attribution is the single highest-risk activity A01 performs.

Every other capability degrades gracefully. A wrong price is a wrong number. A
missed whale transfer is a missed opportunity. **A wrong attribution is an
accusation against a real person or organisation**, and it will be repeated
downstream by every consumer of A01's output — other CIE-OS agents, dashboards,
reports, and potentially compliance or legal processes.

This document is therefore normative, not descriptive. It defines what A01 is
*permitted* to claim, on what basis, and with what caveats attached. Code in
`intelligence/attribution/` that violates this doctrine is a defect regardless
of whether its tests pass.

> **Prime directive:** A01 attributes *addresses to clusters* with high
> confidence, *clusters to behaviours* with moderate confidence, and *clusters
> to real-world identities* only with external corroboration that is recorded
> as evidence.

---

# 2. The Three Layers of Attribution

Attribution is not one operation. Conflating its layers is the most common
source of false accusation in blockchain analytics. A01 separates them
explicitly, and each layer has a different evidentiary bar.

| Layer | Question | Basis | Reversible? | Max confidence without external data |
| --- | --- | --- | --- | --- |
| **L1 — Co-ownership** | Are these addresses controlled by one key-holder? | Protocol mechanics | Rarely | 0.95 |
| **L2 — Behavioural class** | What *kind* of actor is this cluster? | Statistical pattern | Yes | 0.75 |
| **L3 — Real-world identity** | *Who* is this? | External corroboration | Yes | 0.40 |

The confidence ceilings are hard limits enforced in code. An L3 claim can never
be emitted above 0.40 confidence on on-chain evidence alone, no matter how many
weak signals accumulate. Stacking weak signals to manufacture certainty is
prohibited (see §7.2).

## 2.1 Layer boundaries are one-way

Evidence flows upward only. An L3 identity claim must never be used to
strengthen an L1 co-ownership claim about the same cluster. Doing so creates a
circular reasoning loop where a label justifies a cluster which justifies the
label. `intelligence/attribution/` must reject any evidence chain whose
provenance graph contains a cycle; `intelligence/evidence/evidence_graph.py`
owns this check.

---

# 3. Layer 1 — Co-Ownership Heuristics

## 3.1 Common-Input-Ownership (UTXO chains)

**Claim:** If multiple addresses appear as inputs to a single transaction, one
entity controls all of them.

**Basis:** Spending an input requires its private key. Signing a multi-input
transaction requires every corresponding key at the same moment.

This is the strongest heuristic in blockchain analysis and the foundation of
Bitcoin clustering. It is *mechanically* grounded rather than statistical, which
is why it earns the 0.95 ceiling.

**Mandatory exclusions.** The heuristic is invalid — not merely weaker, but
*invalid* — for collaborative transactions where multiple entities co-sign by
design:

- CoinJoin (Wasabi, JoinMarket, Whirlpool patterns)
- PayJoin / P2EP, which is specifically designed to poison this heuristic
- Payment-batching by custodians where inputs span customer deposits
- Lightning channel closes and other multi-party contract settlements

A01 must run CoinJoin detection **before** applying common-input-ownership, not
after. Detection signals: equal-value output sets, output count ≥ 5 with
uniform denominations, known coordinator addresses, and characteristic input
counts. When a transaction matches, the heuristic is skipped and the transaction
is annotated `clustering_excluded: coinjoin` in the evidence chain.

**Known error rate.** Independent evaluation places false-positive rates for
well-implemented common-input clustering below 0.5%. A01 publishes 0.5% as its
documented error rate for this heuristic until it measures its own. Under
Daubert (see `evidence-standard.md` §4) an undocumented error rate is worse than
a high one.

## 3.2 Change-Address Detection (UTXO chains)

**Claim:** One output of a transaction returns funds to the sender and is
therefore co-owned with the inputs.

This is **substantially weaker** than common-input-ownership because it is
inferential rather than mechanical. It is the primary source of cluster
collapse — the failure mode where two unrelated entities merge into one
super-cluster and every downstream conclusion about both becomes wrong.

Supporting signals, in descending strength:

1. **Address reuse asymmetry** — one output is a fresh address, the other has
   prior history. The fresh one is the likely change.
2. **Script-type match** — change typically matches the input script type
   (P2WPKH inputs → P2WPKH change). A mismatched output is likely the payment.
3. **Round-number payment** — a payment of exactly 0.5 BTC alongside an output
   of 0.4913227 BTC suggests the latter is change.
4. **Value bound** — an output larger than any single input cannot be change in
   a simple send.
5. **Wallet fingerprinting** — output ordering, nLockTime use, fee-rate
   rounding, and BIP-69 sorting differ between wallet implementations.

**Doctrine:** A01 requires **at least two independent supporting signals** before
merging clusters on change detection, and caps the resulting edge confidence at
**0.70**. Single-signal change merges are recorded as *candidate* edges in the
graph and never collapse clusters.

**Cluster-collapse circuit breaker.** Any single merge operation that would
increase a cluster's address count by more than 1000, or merge two clusters each
already exceeding 500 addresses, must be quarantined for review rather than
applied automatically. Exchange hot wallets are the usual trigger, and a single
bad merge there contaminates thousands of downstream conclusions.

## 3.3 Account-Model Chains Are Different

Ethereum, Solana, and similar account-model chains **have no common-input
heuristic**. There is exactly one sender per transaction. Analysts who carry
UTXO intuitions across make systematic errors.

Co-ownership evidence on account chains comes from different sources, all
weaker:

| Signal | Strength | Notes |
| --- | --- | --- |
| Deposit-address linkage | 0.85 | Exchange assigns a unique deposit address; funds forwarded to a known hot wallet identify the depositor cluster |
| Gas funding | 0.60 | A fresh address funded for gas by address X, then used, suggests common control — but is also exactly how airdrop farmers and mixer users behave |
| Contract deployment | 0.80 | `CREATE`/`CREATE2` deployer is known and deterministic |
| Multisig signer sets | 0.75 | Overlapping Safe signers suggest a shared operator, not necessarily a shared owner |
| Temporal + nonce patterns | 0.40 | Weak; supporting evidence only |

**Doctrine:** A01 must never apply UTXO-derived confidence values to
account-model chains. `intelligence/attribution/heuristics.py` must dispatch on
chain model (`ChainType.EVM`, `ChainType.SOLANA_LIKE`, `ChainType.BITCOIN_LIKE`
from `config/rpc/chains.py`) and carry separate confidence tables.

---

# 4. Layer 2 — Behavioural Classification

L2 answers "what kind of actor is this" without naming anyone. Classes A01
supports: exchange, bridge, mixer, MEV searcher, market maker, whale,
smart-money, farmer/sybil, protocol treasury, validator, scammer, victim.

Behavioural classification is **statistical and drifting**. A cluster that was a
market maker in January may be a liquidator in June. Every L2 claim therefore
carries a mandatory `observed_window` and expires.

## 4.1 The staleness rule

An L2 classification older than its class's half-life must not be presented as
current. A01 defines:

| Class | Half-life | Rationale |
| --- | --- | --- |
| Exchange hot wallet | 180 days | Infrastructure changes slowly |
| Bridge contract | 365 days | Effectively static until redeployment |
| Mixer | 365 days | Static contract |
| MEV searcher | 14 days | Strategies rotate constantly |
| Market maker | 30 days | Mandates change |
| Smart money | 30 days | Performance is not persistent |
| Whale | 7 days | A whale that sells is no longer a whale |
| Sybil/farmer | 90 days | Campaign-bound |

Expired classifications are not deleted — they are retained as historical
evidence with `status: expired`, because "this cluster behaved as a mixer in
2024" remains a true and useful statement.

## 4.2 Base rates are mandatory

The most common analytical error in this layer is ignoring prior probability.
If 0.01% of addresses are exploiters, a detector with 99% accuracy flagging an
address yields a posterior probability of roughly 1% that it is actually an
exploiter — not 99%.

**Doctrine:** every L2 detector must declare an estimated base rate for its
class. `intelligence/scoring/` must compute posterior probability, not raw
detector confidence, and it is the posterior that is emitted. A detector that
cannot state a base rate may emit only an *indicator*, never a *classification*.

---

# 5. Layer 3 — Real-World Identity

This is where blockchain intelligence becomes consequential and where A01 is
deliberately most conservative.

## 5.1 Permitted evidence sources

| Source | Weight | Verification requirement |
| --- | --- | --- |
| Self-disclosure signed by the key | 0.95 | Signature verified on-chain |
| Official protocol documentation | 0.85 | URL, retrieval timestamp, content hash |
| Regulatory/sanctions designation | 0.90 | Official list, list version recorded |
| Court filing or law-enforcement notice | 0.90 | Document reference |
| Exchange-published address list | 0.80 | Source URL + hash |
| ENS / naming service | 0.35 | Trivially spoofable; supporting only |
| Social media claim | 0.25 | Unverifiable; supporting only |
| Third-party label provider | 0.50 | Provider and label version recorded |
| Press reporting | 0.30 | Supporting only |

## 5.2 Prohibited inferences

A01 must **never**:

- Attribute identity from transaction proximity alone ("interacted with a known
  scammer" is not evidence of being one — victims interact with scammers by
  definition).
- Propagate a label through a mixer, bridge, or CEX. These are **attribution
  barriers**; the chain of custody breaks and confidence resets. Propagating
  through them is the single most damaging error in this field.
- Attribute identity to an address that has only received funds. Receipt is not
  consent and not control — dusting attacks exploit exactly this.
- Infer identity from cluster membership where the cluster was formed by a
  change-address merge below 0.70 confidence.
- Emit an identity claim without at least one source from §5.1 recorded in the
  evidence chain.

## 5.3 The dusting-attack defence

Adversaries send small amounts to many addresses specifically to poison
clustering and to associate innocent addresses with tainted funds. A01 must
apply a **received-value floor**: inbound transfers below a chain-specific dust
threshold create no attribution edge and no taint propagation. The threshold is
configured per chain, not hardcoded globally.

---

# 6. Cross-Chain Attribution

Cross-chain is where attribution is weakest and where the industry most often
overclaims. Address formats change, transaction models differ, and the on-chain
trail genuinely fragments at bridge points.

## 6.1 Evidence tiers for bridge correlation

**Tier A — Deterministic (confidence up to 0.95).** The bridge emits a
correlatable identifier: a message ID, nonce, or transfer ID present in both the
source deposit event and the destination withdrawal event. This is a *verifiable
link*, not a guess. A01 must prefer this path always, and must maintain
per-bridge event-signature mappings to extract it.

**Tier B — Constrained matching (confidence up to 0.65).** No shared identifier.
Correlation rests on time-and-value matching: a deposit of amount *v* at time
*t* on chain A, and a withdrawal of amount *v'* at time *t'* on chain B, where
*t' − t* falls inside the bridge's observed latency distribution and *v'* equals
*v* minus expected fees.

This is only admissible when the match is **unique within the window**. If two
or more candidate withdrawals match, the correlation is ambiguous and A01 must
emit *all* candidates with divided confidence, never silently pick the closest.

**Tier C — Inadmissible.** Time-only or value-only correlation. A01 does not
emit these.

## 6.2 The recipient fallacy

A bridge withdrawal arriving at address *B* does **not** establish that *B* is
controlled by the depositor. Bridges support arbitrary recipients; paying
someone cross-chain is a normal operation. The correct claim is "funds from
cluster *A* were bridged to address *B*", never "*B* belongs to *A*".

This distinction must be preserved in the schema itself, not left to prose.
`intelligence/correlation/bridge_linking.py` must emit a `FLOW` edge type, and
the graph must not permit `FLOW` edges to be consumed by cluster-merge logic.

---

# 7. Confidence Discipline

## 7.1 What confidence means here

A01's confidence values are **calibrated probability estimates**: a claim at
0.80 confidence should be correct about 80% of the time across many such claims.
They are not vibes, and they are not detector output scores.

Calibration must be measured. `evaluation/` should maintain a reliability
diagram per claim type; a class whose 0.9-confidence claims are correct 60% of
the time is miscalibrated and its confidence function must be corrected, not its
threshold moved.

## 7.2 Combining evidence

Independent supporting evidence combines, but with two hard rules:

**Rule 1 — Correlated evidence does not stack.** Five sources that all derive
from the same upstream label provider are one source. The evidence graph tracks
provenance precisely so that correlated evidence can be collapsed before
combination. Treating them as independent is how a 0.5-confidence guess becomes
a 0.99-confidence "fact".

**Rule 2 — The layer ceiling is absolute.** Combination may never lift a claim
above its layer ceiling (§2). If combined evidence for an L3 claim computes to
0.85, it is emitted at 0.40 with a note that additional corroboration is
available. The ceiling exists because the *category* of evidence is limited, and
no quantity of it changes that.

## 7.3 Negative evidence must be recorded

Evidence that *contradicts* a hypothesis is as important as supporting evidence
and is routinely discarded in practice. `intelligence/hypothesis/elimination.py`
must retain disconfirming evidence in the chain. A report that shows only
supporting evidence is not an intelligence product; it is advocacy.

---

# 8. Mandatory Output Contract

Every attribution A01 emits must carry:

```
{
  "subject":        "<address or cluster id>",
  "layer":          "L1" | "L2" | "L3",
  "claim":          "<the assertion>",
  "confidence":     0.0-1.0,
  "confidence_basis": "<which heuristics, with individual weights>",
  "evidence_chain": ["<evidence ids with provenance and hashes>"],
  "contradicting_evidence": ["<ids>"],
  "heuristics_applied": ["<named heuristic + version>"],
  "heuristics_excluded": ["<name + reason, e.g. coinjoin>"],
  "chain_model":    "utxo" | "account",
  "observed_window": {"from": "<ts>", "to": "<ts>"},
  "expires_at":     "<ts or null>",
  "known_error_rate": 0.0-1.0,
  "analyst_review": "required" | "optional" | "not_required"
}
```

An attribution missing any field is malformed and must not leave the
intelligence layer. `intelligence/schemas/` owns this contract.

**Analyst review is mandatory** for: every L3 claim, every cluster merge that
trips the circuit breaker (§3.2), and every claim that will trigger an external
alert. Layered validation — automated heuristics plus human verification — is
what separates a forensic-grade system from an analytics dashboard, and it is a
Daubert consideration, not merely good practice.

---

# 9. Current Implementation Status

Honest assessment against `intelligence/attribution/` as it exists today:

| Doctrine requirement | Status | Gap |
| --- | --- | --- |
| Three-layer separation | ❌ Not implemented | `attribution.py`, `identity.py`, `ownership.py` do not distinguish layers |
| Chain-model dispatch | ❌ Not implemented | No `ChainType` awareness in heuristics |
| CoinJoin exclusion | ❌ Not implemented | No collaborative-transaction detection exists |
| Confidence ceilings | ❌ Not enforced | `confidence.py` has no layer concept |
| Cluster-collapse breaker | ❌ Not implemented | No merge guards in `intelligence/correlation/cluster.py` |
| Evidence-chain cycles | ❌ Not checked | `evidence_graph.py` has no cycle detection |
| Base-rate correction | ❌ Not implemented | `intelligence/scoring/` emits raw scores |
| Bridge tier A/B/C | ❌ Not implemented | `bridge_linking.py` is a stub |
| Output contract | ❌ Not implemented | `intelligence/schemas/` lacks these fields |
| Dust floor | ❌ Not implemented | — |

`intelligence/attribution/` is currently 564 lines across 7 files — scaffolding,
not doctrine. This table is the implementation backlog, ordered by risk:
confidence ceilings and CoinJoin exclusion first, because without them the
system can emit confident false accusations.

---

# 10. Review Triggers

This doctrine must be revisited when:

- A new chain model is added that is neither UTXO nor account-based.
- Measured calibration drifts more than 10 percentage points from stated
  confidence on any claim type.
- A cluster-collapse incident occurs.
- Account abstraction adoption materially breaks sender-based attribution
  (see `future-problems.md` §2).

---

## Sources

- [Chainalysis — Address clustering](https://www.chainalysis.com/glossary/address-clustering/)
- [Chainalysis — Blockchain forensics and the Daubert standard](https://www.chainalysis.com/glossary/blockchain-forensics/)
- [Möser & Narayanan — Resurrecting Address Clustering in Bitcoin (FC'22)](https://fc22.ifca.ai/preproceedings/87.pdf)
- [The Unreasonable Effectiveness of Address Clustering](https://arxiv.org/pdf/1605.06369)
- [Bitcoin Address Clustering Based on Multiple Heuristic Conditions](https://arxiv.org/pdf/2104.09979)
- [Behavior-aware Account De-anonymization on Ethereum Interaction Graph](https://arxiv.org/pdf/2203.09360)
- [Argumentation Schemes for Blockchain Deanonymization](https://arxiv.org/pdf/2305.16883)
- [Elliptic — Following funds across blockchains](https://www.elliptic.co/blog/following-funds-across-blockchains)
- [TRM Labs — Cross-chain tracing](https://www.trmlabs.com/glossary/cross-chain-tracing)
- [CONNECTOR: Automatic Cross-chain Transaction Association](https://arxiv.org/pdf/2409.04937)

---

**End of Attribution Doctrine**
