# Detection Catalog

## A01 Blockchain Intelligence Agent

**Project:** CIE-OS (Crypto Intelligence Engine Operating System)
**Document Type:** Detection Specification — Normative
**Version:** 1.2.0
**Status:** Authoritative — §8 regrounded against the working tree
**Implements:** `intelligence/analysis/`, `intelligence/scoring/`, `intelligence/alerts/`

---

# 1. Scope and Contract

`identity/capabilities.md` lists *what* A01 can do. This document specifies
*how each detection actually works*: its signal, thresholds, error
characteristics, evasion surface, and known false-positive sources.

A capability without an entry here is not a capability. It is an aspiration,
and it must not be advertised in reports or APIs.

## 1.1 Mandatory detector specification

Every detector declares:

| Field | Purpose |
| --- | --- |
| `id` | Stable identifier, e.g. `DET-WHALE-01` |
| `class` | Output class emitted |
| `signal` | The observable it keys on |
| `thresholds` | Named, configurable, never hardcoded |
| `base_rate` | Prior probability of the class (`attribution-doctrine.md` §4.2) |
| `error_rate` | `measured` / `stated` / `unmeasured` |
| `fp_sources` | Enumerated benign patterns that trip it |
| `evasion` | How an adversary defeats it |
| `data_requirements` | Which transfer types must be present |
| `latency_class` | `realtime` / `block` / `batch` |
| `maturity` | `spec` / `scaffold` / `implemented` / `validated` |

A detector at `maturity: scaffold` emits **indicators only** — never
classifications, never alerts.

---

# 2. Why Thresholds Must Be Relative

The most common detector defect in blockchain analytics is the absolute
threshold. A01's first `WhaleAnalyzer` illustrated it exactly:

```python
threshold = _to_float(self._get(subject, "whale_threshold", 1000))  # removed
```

A default of `1000` with no unit, no asset, and no chain context is not a
detection rule. 1000 what? 1000 USDC is a retail transaction. 1000 BTC is a
market-moving event. 1000 wei is dust. It is also a published evasion guide:
an adversary simply sits below it.

That code is gone — `intelligence/analysis/whale.py` now qualifies on relative
measures only. The example is kept because the defect recurs, and because the
rebuild exposed a second-order version of it worth recording:

> A percentile threshold needs a population large enough to *reach* it. The
> detector ranks by the count of strictly-smaller observations, so the largest
> value in a population of *n* scores `(n-1)/n × 100`. A 99.9 threshold is
> therefore unreachable below 1,000 samples — and below it every subject reports
> no whale activity while the thresholds, the population and the transfers all
> look correct. `skills.whale_detection.min_population_for` derives the bound
> from the threshold rather than assuming a round number.

**Doctrine:** thresholds are expressed as one of:

1. **Percentile against a rolling population** — "top 0.1% of transfers for
   this asset over 30 days"
2. **Fraction of a reference quantity** — "≥ 2% of circulating supply",
   "≥ 5% of pool liquidity"
3. **Normalised value** — USD-denominated with the price source, timestamp, and
   staleness recorded as evidence

Absolute native-unit thresholds are permitted only for chain-level constants
(dust limits, gas floors) where the unit is intrinsically meaningful.

---

# 3. Movement Detections

## DET-WHALE-01 — Whale transfer

| | |
| --- | --- |
| **Signal** | Single transfer in the top percentile of its asset's distribution |
| **Thresholds** | (`percentile ≥ 99.9` **or** `supply_fraction ≥ 0.001`), **and** `usd_value ≥ floor` (default 1,000,000) as a floor only |
| **Base rate** | ~0.1% of transfers by construction |
| **Error rate** | `unmeasured` — capped at 0.60 confidence, barred from alerting |
| **Latency** | `block` |
| **Maturity** | `implemented` |
| **Population** | ≥ 1,000 transfers, or the percentile is unreachable (§2) |

**False-positive sources.** These are the majority of naive "whale alerts":

- **Internal custody rebalancing.** Exchange cold→hot movements are enormous
  and carry zero market signal. Suppress when both endpoints are in the same
  attributed cluster.
- **Bridge lock/mint pairs.** A bridge deposit and its corresponding mint are
  one economic event, counted twice by transfer-level detection.
- **Wrapping and rebasing.** ETH→WETH is not a transfer of economic exposure.
- **Contract-internal routing.** A DEX aggregator's intermediate hops are not
  whale transfers.
- **Token contract deployment.** The initial mint to treasury is 100% of supply
  and trips every threshold.

**Doctrine:** DET-WHALE-01 must run *after* cluster attribution and
*after* internal-transfer folding, never on the raw transfer stream. A whale
detector operating on raw transfers produces a firehose of noise, and its alert
fatigue destroys trust in every other detection A01 emits.

**Evasion.** Trivial: split into *n* sub-threshold transfers (structuring).
Counter-signal is the aggregate — see DET-STRUCT-01.

## DET-STRUCT-01 — Structuring / value splitting

| | |
| --- | --- |
| **Signal** | Many sub-threshold transfers from one cluster to one destination cluster within a window, summing above the whale threshold |
| **Thresholds** | `count ≥ 5`, `window ≤ 24h`, `sum ≥ whale_floor`, `value_variance ≤ 0.15` (uniform amounts are the tell) |
| **Base rate** | Low; also produced by legitimate batching |
| **Error rate** | `unmeasured` |
| **Maturity** | `spec` |

**False positives.** Payroll batching, airdrop distribution, market-maker
inventory management, and NFT royalty payouts all look like this. Uniformity of
*timing* alongside uniformity of *value* is the discriminating signal;
legitimate batching is usually uniform in one dimension, not both.

## DET-DORMANT-01 — Dormant wallet reactivation

| | |
| --- | --- |
| **Signal** | First outbound transfer after prolonged inactivity |
| **Thresholds** | `dormancy ≥ 365d`, `balance_percentile ≥ 99` |
| **Base rate** | Very low — genuinely rare, genuinely informative |
| **Error rate** | `unmeasured` — capped at 0.60 confidence, barred from alerting |
| **Maturity** | `implemented` |

**Note.** This is one of the few detections with a *high* signal-to-noise ratio,
because the base rate is low and the benign explanations are few. Prioritise it.

---

# 4. Market-Structure Detections

## DET-MEV-01 — Sandwich attack

| | |
| --- | --- |
| **Signal** | Frontrun/victim/backrun triple within one block |
| **Maturity** | `spec` |

**Specification.** Within a single block, ordered by index: locate transaction
*F* and transaction *B* from the same sender (or same searcher cluster), on the
same pool, in opposing directions, with at least one victim transaction *V*
between them trading the same pair in the same direction as *F*.

**Known heuristic weakness.** Published research is explicit that naive
implementations produce both false positives and false negatives. The dominant
error is comparing input/output token amounts across multi-swap routes and
concluding profit where none exists. A01 must evaluate profit on the
*swap graph* across the full route, not on first-in/last-out amounts.

**Evasion — and why this detector is decaying.** MEV extraction has migrated to
private orderflow channels. Sandwiching conducted through private relays does
not appear in the public mempool, and searcher behaviour has adapted
specifically to evade public-mempool detection. A01's mempool-based signal
therefore observes a shrinking and increasingly biased sample.

**Doctrine:** DET-MEV-01 must report *observed* sandwiching with an explicit
coverage caveat. It must never present its count as total MEV activity, and its
output must carry `coverage: public_mempool_only`.

## DET-ARB-01 — Atomic arbitrage

| | |
| --- | --- |
| **Signal** | Single transaction with ≥ 2 swaps forming a closed cycle returning to the input asset at a profit |
| **Thresholds** | `cycle_closed = true`, `net_profit > gas_cost` |
| **Maturity** | `spec` |

Detection is via cycle search over the transaction's swap graph. This is
cleaner than sandwich detection because atomicity makes profit computable
exactly within the transaction. Non-atomic and cross-chain arbitrage are
substantially harder and out of scope for v1 — document that boundary rather
than pretending coverage.

---

# 5. Security Detections

These carry the highest consequence and the highest false-positive cost.

## DET-EXPLOIT-01 — Flash-loan price manipulation

| | |
| --- | --- |
| **Signal** | Flash loan + oracle-relevant pool state change + profitable extraction, atomically |
| **Latency** | `realtime` (mempool) or `block` |
| **Maturity** | `spec` |

**Specification.** Composite, all within one transaction:

1. A flash loan is opened (borrow with same-transaction repayment).
2. A pool that is an oracle input experiences a price deviation beyond a
   configured band (default 5%) relative to a TWAP or external reference.
3. A dependent protocol is interacted with while the price is deviated.
4. Net value extracted exceeds gas plus fees.

All four are required. Flash loans alone are overwhelmingly benign — they are a
normal primitive for arbitrage, collateral swaps, and refinancing. **A detector
that alerts on flash loans is a detector that alerts on normal DeFi.**

**Not all flash-loan attacks manipulate price.** A significant class exploits
contract logic — access control, reentrancy, accounting errors — with no oracle
component. Price-deviation-based detection is structurally blind to these. A01
must document this blind spot explicitly rather than implying full coverage.

**Realtime detection is achievable.** Published systems report ~150ms mempool
detection latency at high accuracy by analysing pending-transaction function
signatures. That is the target if A01 pursues realtime; if it cannot meet it,
block-latency post-hoc detection is still valuable for attribution and
incident response, and should be scoped honestly as such.

## DET-EXPLOIT-02 — Anomalous outflow

| | |
| --- | --- |
| **Signal** | Protocol TVL drop far beyond its historical volatility, in a short window |
| **Thresholds** | `outflow_fraction ≥ 0.30` within `≤ 3` blocks, **and** `z_score ≥ 6` against 90d volatility |
| **Maturity** | `spec` |

**Why this complements DET-EXPLOIT-01.** It is mechanism-agnostic. It cannot
tell you *how*, but it catches novel exploit classes that signature-based
detection misses. Given that preventive measures cannot anticipate all attack
variations, mechanism-agnostic anomaly detection is the necessary safety net.

**False positives.** Scheduled unlocks, migration events, governance-approved
treasury moves, and mass unstaking after a rewards change. Suppress against a
known-events calendar; the absence of that calendar is why anomaly detectors
get muted in practice.

## DET-RUG-01 — Rug-pull indicators

| | |
| --- | --- |
| **Signal** | Composite of contract-permission and liquidity signals |
| **Maturity** | `spec` |

**Component indicators**, each individually weak:

- Liquidity not locked, or lock expiring imminently
- Owner retains mint, blacklist, or fee-modification authority
- Proxy admin is an EOA rather than a timelock or multisig
- Supply concentration: top-10 non-contract holders exceed 70%
- Trading asymmetry: buys succeed, sells revert (honeypot)
- Deployer cluster linked to prior abandoned deployments

**Doctrine — this detection is defamation-adjacent.** "Rug pull" alleges
intent to defraud. A01 must emit `rug_risk_indicators` with the individual
components enumerated, **never** a `is_rug_pull` boolean. The determination is
the human analyst's. This constraint follows directly from
`attribution-doctrine.md` §5 and the mission's ethical principles.

Honeypot detection specifically requires simulation (`eth_call` against a
forked state), not static analysis — a contract can pass bytecode inspection
and still block sells at runtime.

---

# 6. Cross-Chain Detections

## DET-BRIDGE-01 — Cross-chain flow correlation

| | |
| --- | --- |
| **Signal** | Deposit on chain A matched to withdrawal on chain B |
| **Maturity** | `spec` |

Implements the tiering in `attribution-doctrine.md` §6.1:

- **Tier A** — shared identifier from bridge event logs. Confidence ≤ 0.95.
  Requires a per-bridge event-signature registry; this registry is the actual
  engineering work and it requires ongoing maintenance as bridges upgrade.
- **Tier B** — time-and-value matching inside the bridge's observed latency
  distribution, admissible **only when the match is unique in the window**.
  Confidence ≤ 0.65. Ambiguous matches emit all candidates with divided
  confidence.
- **Tier C** — time-only or value-only. Not emitted.

**The fee problem.** Tier B matching must model each bridge's fee structure to
predict the destination amount. Fees are often percentage-based with minimums,
change without notice, and differ per asset and per route. A stale fee model
silently converts Tier B matches into misses. Fee models require a freshness
check, and a stale model must downgrade output rather than fail silently.

---

# 7. Cross-Cutting Requirements

## 7.1 Alert economics

Alert volume must be budgeted, not emergent. A detector that fires more than
its budget is muted and flagged for retuning rather than being allowed to
degrade the whole system's credibility. Alert fatigue is the primary failure
mode of production intelligence systems — it kills the true positives along
with the false ones.

Each `decision.alerts.Subscription` declares a `max_alerts_per_day`. On breach,
`decision.alerts.AlertPolicy` emits a `Digest` carrying every folded conclusion
rather than dropping the excess: the budget limits how often a recipient is
interrupted, not how much they are allowed to know. Dropping would lose the
tail, and the tail is where the unusual case sits.

**Implementation status.** The policy is built and tested; it currently raises
nothing, because §7.3 bars every detector A01 has. `decision.MaturityGate`
suppresses each one with a stated reason, and `Decision.silence_explained`
reports it — so a quiet system is distinguishable from a broken one.

## 7.2 Every detection must state what would disprove it

A detection that cannot be falsified is not a detection. Each entry in this
catalog must eventually carry a `falsified_by` field naming the observation
that would retract the conclusion. This is the operational form of the Daubert
testability criterion (`evidence-standard.md` §2) and it is what makes
`intelligence/hypothesis/elimination.py` meaningful rather than decorative.

## 7.3 Backtesting is mandatory before `validated`

A detector reaches `maturity: validated` only after running against a labelled
historical window with measured precision and recall. Until then it stays at
`implemented` and its error rate remains `unmeasured` — which caps it at 0.60
confidence and bars it from generating external alerts.

**This is now enforced in code**, not merely stated here.
`decision.maturity.REGISTRY` holds each detector's standing and
`decision.maturity.MaturityGate` applies it: confidence is clamped to the
maturity ceiling and alerting requires `VALIDATED`. The gate has no override
parameter — one that can be bypassed per call is documentation, not a gate — and
it fails closed, so an unrecognised detector name silences a detector rather
than granting it full privileges.

Promotion is a one-line registry edit **after** the backtest, and editing a row
without one is the single change in the codebase that would make A01 dishonest.

---

# 8. Implementation Status

| Detector | Spec | Code | Gap |
| --- | --- | --- | --- |
| DET-WHALE-01 | ✅ | ✅ `whale.py`, 330 lines | No cluster folding; error rate unmeasured |
| DET-STRUCT-01 | ✅ | ❌ | Not started |
| DET-DORMANT-01 | ✅ | ✅ `dormant.py`, 237 lines | Error rate unmeasured |
| DET-MEV-01 | ✅ | ❌ | No MEV module exists |
| DET-ARB-01 | ✅ | ❌ | Not started |
| DET-EXPLOIT-01 | ✅ | ❌ | `intelligence/analysis/contract.py` is a stub |
| DET-EXPLOIT-02 | ✅ | ❌ | Not started |
| DET-RUG-01 | ✅ | ❌ | Not started |
| DET-BRIDGE-01 | ✅ | ⚠️ `bridge.py` + `bridge_linking.py`, both stubs | No event registry, no tiering |

`✅` in the Code column means the detector is functionally complete and
registered in `intelligence/core/stages.py` — reachable via `python -m cli
detectors`. It does **not** mean validated: per §7.3 both implemented
detectors still carry an `unmeasured` error rate and are capped at 0.60
confidence.

## 8.1 Completed

1. **DET-DORMANT-01** — dormancy window (365d default) plus a balance
   materiality floor at the 99th percentile, reported in dormancy bands.
2. **DET-WHALE-01 rebuild** — the absolute `threshold = 1000` is gone.
   Qualification now requires the strongest of three *relative* measures to
   trip: percentile rank within the asset's own transfer distribution, fraction
   of circulating supply, or USD notional used only as a floor. Non-economic
   transfer kinds (internal rebalancing, bridge lock/mint, wrap) are folded out
   before anything is measured.

## 8.2 Remaining, by value-to-effort

1. **Backtest the two implemented detectors.** The `evaluation/` harness now
   exists (`Backtest`, `ClassificationMetrics`, `calibration`); what is missing
   is a labelled historical window to run it against. Until that lands, A01 has
   zero validated detectors, so this outranks building the third one.
2. **DET-EXPLOIT-02** — mechanism-agnostic, catches novel classes, no signature
   maintenance burden.
3. **DET-BRIDGE-01 Tier A** — unlocks cross-chain, deterministic, defensible.
4. **DET-RUG-01 indicators** — high user demand; ship as indicators only.
5. **DET-EXPLOIT-01**, **DET-ARB-01**, **DET-MEV-01** — highest complexity,
   and MEV specifically has a decaying signal.

---

## Sources

- [Remeasuring the Arbitrage and Sandwich Attacks of MEV in Ethereum](https://arxiv.org/pdf/2405.17944)
- [MEV in DeFi: Taxonomy, Detection, and Mitigation](https://arxiv.org/pdf/2411.03327)
- [Sandwiched and Silent: Behavioral Adaptation and Private Channel Exploitation in Ethereum MEV](https://arxiv.org/pdf/2512.17602)
- [Protecting DeFi Platforms against Non-Price Flash Loan Attacks](https://arxiv.org/pdf/2503.01944)
- [DeFiRanger: Detecting Price Manipulation Attacks on DeFi Applications](https://arxiv.org/pdf/2104.15068)
- [Penetrating the Hostile: Detecting DeFi Protocol Exploits through Cross-Contract Analysis](https://arxiv.org/pdf/2511.00408)
- [A Robust Front-Running Methodology for Malicious Flash-Loan DeFi Attacks](https://www.eecg.utoronto.ca/~veneris/23dapps.pdf)
- [CONNECTOR: Automatic Cross-chain Transaction Association](https://arxiv.org/pdf/2409.04937)
- [Cross-Chain Arbitrage: The Next Frontier of MEV](https://arxiv.org/pdf/2501.17335)

---

**End of Detection Catalog**
