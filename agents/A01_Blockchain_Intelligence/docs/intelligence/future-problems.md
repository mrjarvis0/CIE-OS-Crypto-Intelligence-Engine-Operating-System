# Future Problems

## A01 Blockchain Intelligence Agent

**Project:** CIE-OS (Crypto Intelligence Engine Operating System)
**Document Type:** Strategic Analysis — Forward-Looking
**Version:** 1.0.0
**Status:** Authoritative
**Review cadence:** Every 6 months, or on any trigger in §10

---

# 1. Purpose and Method

`identity/roadmap.md` describes features A01 intends to build. This document
describes **the ground shifting underneath those features**.

The distinction matters. A roadmap assumes the problem stays still. Blockchain
intelligence has a structural disadvantage that most software domains do not:
**the substrate is adversarial and it changes faster than the analysis of it.**
Heuristics decay. Some decay gradually as adoption shifts; others break
discontinuously when a standard lands.

Each section below states: what changes, *what specifically breaks in A01*, the
horizon, and what to do now. A prediction with no engineering consequence is
not included.

**Severity scale:**

- **Structural** — invalidates a core assumption; requires re-architecture
- **Degrading** — accuracy erodes over time; requires continuous investment
- **Additive** — new work, existing work stays valid

---

# 2. Account Abstraction Breaks Sender-Based Attribution

**Severity: Structural. Horizon: already underway.**

## What changes

Ethereum is moving from externally-owned accounts to programmable accounts.
ERC-4337 delivers this without protocol changes: users submit `UserOperation`
pseudo-transactions to a **separate mempool**, bundlers batch them, paymasters
can pay the gas, and authentication is programmable rather than a fixed
private-key signature. EIP-7702 extends the direction by letting existing EOAs
take on smart-account behaviour.

## What breaks in A01

Nearly every attribution assumption on account-model chains:

1. **`tx.origin` and `msg.sender` stop identifying the actor.** The transaction
   sender is the *bundler*. The economic actor is inside the `UserOperation`.
   Any A01 logic keyed on the transaction sender will attribute activity to
   bundler infrastructure — a small set of addresses that will accumulate
   enormous, meaningless clusters. This is a cluster-collapse event waiting to
   happen (`attribution-doctrine.md` §3.2).

2. **The public mempool stops being the full picture.** ERC-4337 uses an
   alternate mempool. Any A01 detection with `latency_class: realtime` observes
   a partial and biased sample. This compounds the private-orderflow problem
   already degrading MEV detection (`detection-catalog.md` §4).

3. **Gas-funding heuristics invert.** A01's account-model co-ownership table
   (`attribution-doctrine.md` §3.3) weights gas funding at 0.60. With
   paymasters, gas is routinely paid by a sponsor with **no relationship** to
   the user. That heuristic does not weaken — it becomes actively misleading,
   and it will systematically link users to dapp sponsors.

4. **Key rotation severs address-to-controller continuity.** Programmable
   authentication means the controlling key can change while the address
   persists. "Same address" no longer implies "same controller over time" — an
   assumption embedded throughout behavioural classification.

5. **Social recovery and multi-sig authorisation** mean there may be no single
   controller at all. The mental model of one address = one owner does not
   survive.

## What to do now

- Treat `UserOperation` as a **first-class ingestion object**, not a decoded
  detail of a bundler transaction. This is a schema decision; making it later
  is a migration.
- Add `sender_semantics` to every attribution: `eoa` | `bundled_userop` |
  `contract_account` | `sponsored`. Detectors dispatch on it.
- Set gas-funding heuristic weight to **0.0 when a paymaster is present**.
- Introduce `controller_epoch` so a cluster's history can be segmented at key
  rotations rather than silently merged.
- Add the ERC-4337 EntryPoint contracts to a **never-cluster** list alongside
  bridges and mixers.

**This is the highest-priority forward-looking item.** It is not speculative;
it is deployed and growing, and A01's account-model attribution is being built
right now on assumptions it invalidates.

---

# 3. Intent-Based Architectures Hide the Actor

**Severity: Structural. Horizon: 1–3 years.**

## What changes

Users increasingly express *what they want* rather than *how to do it*. A solver
network competes to fulfil the intent. The on-chain footprint is the solver's
execution path, not the user's instruction.

## What breaks

The on-chain record becomes a record of **solver behaviour**, with user
intent inferable only indirectly. Specifically:

- Trade-size and slippage analysis measures the solver's routing, not the user's
  order.
- Counterparty analysis links users to solvers rather than to each other.
- Batched settlement means multiple users' intents net against each other
  off-chain and settle as one transaction — the individual flows never appear
  on-chain at all.

This is qualitatively different from a mixer. A mixer is an obfuscation barrier
A01 can *recognise and mark*. Intent settlement is **normal infrastructure**
that structurally does not record what A01 wants to know.

## What to do now

- Maintain a solver/settlement-contract registry; treat these as attribution
  barriers with confidence reset, exactly like bridges.
- Accept and document a **coverage limit**: for intent-routed activity, A01
  reports flows, not actors. Overclaiming here is the failure mode.
- Where intent systems publish off-chain order data, treat it as Type E
  external evidence with the provider's weight — not as protocol fact.

---

# 4. Chain Proliferation Outpaces Coverage

**Severity: Degrading. Horizon: continuous.**

Rollup deployment is now near-commoditised. The number of chains grows faster
than any team can write per-chain integrations, and per-chain work is
non-transferable: new RPC quirks, new bridge contracts, new DEX forks, new
token standards.

**What breaks:** coverage silently becomes unrepresentative. A01 reports
"exchange inflows" that reflect only the chains it indexes. The number is not
wrong; the *implied scope* is. This is the most insidious failure in this
document because nothing errors.

**What to do now:**

- Every aggregate output must carry an explicit `coverage` manifest: chains
  included, block ranges, and known gaps. `intelligence/reporting/` must render
  it, not hide it in metadata.
- Invest in **chain-class abstraction** over per-chain code. An EVM rollup
  should require configuration, not implementation. `config/rpc/chains.py` is
  the right seam; it currently hardcodes nine chains.
- Define an explicit **coverage tier** per chain (`full` / `partial` /
  `none`) and refuse to emit chain-agnostic aggregates that mix tiers without
  saying so.

---

# 5. Privacy Technology Reaches Production

**Severity: Structural where adopted. Horizon: 2–5 years.**

Stealth addresses, ZK-based shielded pools, encrypted mempools, and eventually
FHE-based confidential execution each remove a different observable A01
depends on.

The critical realisation: **A01's entire premise is that blockchains are
publicly readable.** That premise is a historical accident of early design, not
a law. Where privacy technology succeeds, A01 does not degrade gracefully — it
goes blind.

| Technology | What A01 loses |
| --- | --- |
| Stealth addresses | Address reuse; recipient linkability |
| Shielded pools | Amounts and graph structure inside the pool |
| Encrypted mempool | All pre-confirmation signal; realtime detection |
| Confidential execution | Contract state transitions |

**What to do now:**

- Design for **boundary analysis**. Even a perfect privacy pool has entry and
  exit points, and those remain observable. A01's long-term value in a private
  world is analysis of the shielded/transparent boundary, not the interior.
- Never present absence of visibility as absence of activity. Reports must
  distinguish "no activity observed" from "activity not observable" — these are
  different claims and conflating them is a factual error.
- Recognise the legitimate-use reality: privacy tools are used by ordinary
  people for ordinary reasons. A01's ethical principles forbid treating privacy
  use as evidence of wrongdoing. Encode that as a **hard rule**, not a
  guideline: privacy-tool interaction must not by itself raise a risk score.

---

# 6. History Expiry and the Archival Assumption

**Severity: Structural for historical analysis. Horizon: 2–4 years.**

Ethereum's roadmap includes history expiry (the EIP-4444 direction): clients
stop serving ancient history, and its availability moves to specialised
archival providers.

**What breaks:** A01's `memory/` layer and every long-window behavioural
analysis assume historical data is retrievable on demand. Half-lives in
`attribution-doctrine.md` §4.1 assume a 365-day lookback is always available.
If deep history requires a specific paid provider, then A01's historical
reasoning acquires a **single point of dependency and cost**.

**What to do now:**

- Treat historical data as **something A01 must own, not fetch**. Derived facts
  that A01 will need later should be computed and persisted at observation
  time, with provenance, rather than assumed re-derivable.
- This reframes `memory/` from a cache into an **archive of record** — a
  significant but currently cheap architectural decision.
- Record in evidence provenance whether a fact was observed live or
  reconstructed from an archival provider. Their trust weights differ.

---

# 7. Adversaries Adopt AI

**Severity: Degrading. Horizon: already underway.**

Evasion has historically been limited by human effort. That constraint is
lifting. Expect: automated generation of transaction patterns tuned to sit
below published thresholds, synthetic history-building to establish "clean"
addresses at scale, and adversarial probing of detector boundaries.

**What breaks:** static thresholds and any detector whose behaviour can be
inferred from its output. Detection becomes a moving contest rather than a
solved rule.

**What to do now:**

- Distribution-relative thresholds (`detection-catalog.md` §2) rather than
  absolute ones — they move as the population moves.
- **Do not publish exact thresholds.** A published threshold is an evasion
  guide (`threat-model.md` §2.4).
- Continuous calibration measurement (`evidence-standard.md` §2.1). A detector
  whose precision is silently decaying is worse than no detector, because it
  carries unearned authority.
- Treat detector performance as a **time series**, not a fixed property.

---

# 8. Regulatory Divergence Becomes an Architectural Constraint

**Severity: Additive, but non-optional. Horizon: 1–3 years.**

Jurisdictions are diverging on what analytics may be performed, retained, and
acted upon. Sanctions designations change; a designated entity's addresses may
later be delisted, and chain-hopping plus rapid rebranding — the
Garantex-to-Grinex pattern — means designation lists lag reality.

**What breaks:** a single global configuration. And specifically:
**conclusions computed under an old list are wrong under the new one.**

**What to do now:**

- Version every external list and record the version in evidence
  (`evidence-standard.md` §4). "Sanctioned" without a list version and date is
  an unfalsifiable claim.
- Support **retroactive re-evaluation**: when a list changes, identify affected
  conclusions and propagate retraction. This requires the append-only evidence
  store to be queryable by cited source — a schema requirement to decide now.
- Make `retention_class` and jurisdictional policy configuration, not code.

---

# 9. The Explainability Squeeze

**Severity: Structural tension. Horizon: continuous.**

A01 commits to explainability. Accuracy pressure pushes toward ML methods —
graph neural networks are already used for MEV detection without ABI knowledge,
and they outperform hand-written heuristics on several tasks.

These pull against each other. A GNN embedding is not an explanation, and it
does not satisfy the Daubert testability and error-rate criteria in the way a
named heuristic does.

**The resolution A01 adopts:** ML is permitted for **triage and ranking**, never
for **conclusion**. A model may decide what a human or a deterministic pipeline
examines next. It may not be the thing that asserts a fact. This preserves the
evidence standard while capturing most of the practical benefit — because in
intelligence work, correctly prioritising the queue is most of the value.

Document this boundary explicitly wherever ML is introduced, because the
pressure to cross it will be constant and will always be framed as a small
exception.

---

# 10. Review Triggers

Revisit this document immediately when any of these occur:

- ERC-4337 `UserOperation` volume exceeds 10% of transactions on any chain A01
  covers.
- Any chain A01 covers deploys an encrypted mempool.
- History expiry activates on a covered chain.
- A01's measured calibration drifts >10 points on any claim type.
- An intent/solver architecture exceeds 10% of DEX volume on a covered chain.
- A cluster-collapse incident occurs in production.

---

# 11. Priority Summary

| # | Problem | Severity | Horizon | Act now? |
| --- | --- | --- | --- | --- |
| 1 | Account abstraction | Structural | Now | **Yes — schema decisions** |
| 2 | Chain proliferation | Degrading | Continuous | **Yes — coverage manifest** |
| 3 | History expiry | Structural | 2–4y | **Yes — archive-of-record** |
| 4 | Adversarial AI | Degrading | Now | **Yes — relative thresholds** |
| 5 | Intent architectures | Structural | 1–3y | Registry + coverage limits |
| 6 | Regulatory divergence | Additive | 1–3y | List versioning |
| 7 | Explainability squeeze | Tension | Continuous | Boundary documented |
| 8 | Privacy technology | Structural | 2–5y | Boundary analysis design |

Items 1–4 have **cheap actions now and expensive migrations later**. They are
schema and architecture decisions, and A01 is at exactly the point in its
lifecycle where they cost the least.

---

## Sources

- [ERC-4337: Account Abstraction Using Alt Mempool](https://eips.ethereum.org/EIPS/eip-4337)
- [Turnkey — Account abstraction: from ERC-4337 to EIP-7702](https://www.turnkey.com/blog/account-abstraction-erc-4337-eip-7702)
- [Alchemy — What is account abstraction](https://www.alchemy.com/overviews/what-is-account-abstraction)
- [Sandwiched and Silent: Behavioral Adaptation and Private Channel Exploitation in Ethereum MEV](https://arxiv.org/pdf/2512.17602)
- [Cross-Chain Arbitrage: The Next Frontier of MEV](https://arxiv.org/pdf/2501.17335)
- [Unraveling the MEV enigma: ABI-free detection using Graph Neural Networks](https://www.sciencedirect.com/science/article/abs/pii/S0167739X23004223)
- [Chainalysis — Crypto Sanctions: 2026 Crypto Crime Report](https://www.chainalysis.com/blog/crypto-sanctions-2026/)
- [Evasion Under Blockchain Sanctions](https://arxiv.org/html/2507.11721v2)
- [SoK: Security and Privacy of AI Agents for Blockchain](https://arxiv.org/pdf/2509.07131)

---

**End of Future Problems**
