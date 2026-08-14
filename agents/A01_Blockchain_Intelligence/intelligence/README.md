# intelligence

CIE-OS / A01 Blockchain Intelligence Agent - **Cognitive Intelligence Layer**

## Purpose

The `intelligence/` package is the cognitive core of the A01 Blockchain
Intelligence Agent. It converts raw, tool-collected evidence into
**explainable, evidence-backed, and decision-ready intelligence**.

```
Observe -> Collect -> Normalize -> Correlate -> Reason -> Hypothesize
       -> Verify -> Score -> Predict -> Explain -> Report -> Remember
```

It is deliberately separated from `planning/` (decides *what* to do),
`tools/` (decides *how* to gather data) and `memory/` (decides *what* to
remember). `intelligence/` decides **what the data actually means**.

## Subpackages

| Package        | Responsibility                                                     |
|----------------|--------------------------------------------------------------------|
| `core`         | Intelligence engine, pipeline, manager, context, state, runtime.   |
| `reasoning`    | Structured multi-step reasoning (ReAct, CoT, ToT, reflection...).  |
| `evidence`     | Evidence building, provenance, source ranking, chains, confidence. |
| `analysis`     | Domain analyzers (wallet, token, contract, whale, liquidity...).   |
| `correlation`  | Cross-source linking (wallet, entity, social, bridge, exchange...).|
| `attribution`  | Identity/label/ownership attribution and heuristics.               |
| `graph`        | Graph intelligence (flow graphs, clusters, pathfinding).           |
| `timeline`     | Chronological event reconstruction and milestones.                 |
| `scoring`      | Risk, trust, fraud, reputation, whale, smart-money, anomaly scores.|
| `prediction`   | Trend / wallet / market / scenario forecasting.                    |
| `hypothesis`   | Hypothesis generation, testing, elimination, ranking.              |
| `verification` | Cross-checking claims against on-chain, web, social, GitHub.       |
| `reporting`    | Final intelligence report rendering (md, json, pdf, dashboard).    |
| `alerts`       | Intelligence triggers, notifications, subscriptions.               |
| `monitoring`   | Metrics, profiling, diagnostics, tracing, health.                  |
| `schemas`      | Canonical intelligence data models.                                |
| `utils`        | Normalization, hashing, formatting, ranking, converters.           |

## Engine Layer (higher-order intelligence)

Engines combine **multiple skills** into higher-order reasoning. Each engine
is a vertical slice: skills provide capabilities, engines interpret.

| Engine               | Responsibility                                                      |
|----------------------|---------------------------------------------------------------------|
| `liquidity_engine`   | Pool/DEX liquidity, depth, slippage, composition, risk.             |
| `behavior_engine`    | Wallet/entity behavioral patterns, smart-money behavior.            |
| `anomaly_engine`     | Deviations from established baselines.                              |
| `manipulation_engine`| Wash trading, spoofing, pump-and-dump, market abuse patterns.       |
| `blockchain_dna`     | Chain-level fingerprint of activity and health.                     |
| `digital_twin`       | Simulated replica of wallets/protocols for what-if analysis.        |
| `probability_engine` | Probabilistic forecasts from engine evidence.                       |
| `confidence_engine`  | Aggregated confidence scoring across evidence sources.              |
| `reasoning_engine`   | Structured multi-hop reasoning over skill outputs.                  |
| `risk_engine`        | Consolidated risk assessment feeding `decision/`.                   |

**Skill vs Engine rule:** `skills/` = one responsibility each; `intelligence/`
engines combine skills. An engine must never fetch data directly — it consumes
skill outputs and `blockchain/` domain data.

## Design Principles

* Every conclusion carries **evidence** with provenance, timestamp, and hash.
* Every output carries a **confidence** value derived from evidence strength.
* Intelligence is **deterministic-first**; AI supplements but never replaces
  verified evidence.
* Engines are **independently testable** vertical slices.
* No secrets, no environment-specific values, no business logic in constants.

## Build Order (Vertical Slices)

1. `schemas` - canonical data models everything depends on.
2. `utils` - shared helpers.
3. `evidence` - the foundation of evidence-backed intelligence.
4. `core` - engine, pipeline, manager.
5. `reporting` - turn results into reports.
6. `scoring` + `risk` - decision layer.
7. `analysis` - domain analyzers.
8. Everything else (correlation, graph, prediction, hypothesis...).
