# `blockchain/` — Architecture

A01's blockchain data subsystem: everything between a node's JSON-RPC port and
a canonical fact a skill can reason over.

This document exists to answer one question before any code is written for a
new module: **does something already do this?** For four of the modules in the
target structure, the answer is yes, and building them here would put the same
responsibility in two places that can disagree.

---

## 1. Boundary

`tools/blockchain/` and `blockchain/` are both about chains, and the split
between them is not obvious from the names.

| | `tools/blockchain/` | `blockchain/` |
|---|---|---|
| Nature | Pure functions and contracts | Live infrastructure |
| Network | Never | Always |
| Contents | ABI codecs, address validation, block/log parsing, `*Client` ABCs, `Local*` stubs | Endpoint catalog, transport, indexing, reorg tracking |
| Fails when | Input is malformed | A remote host is down |

`tools/blockchain/` was already complete and correct. `blockchain/` supplies
what those `*Client` contracts were shaped around — the network-backed
counterparts to the `Local*` stubs. **Codecs are never reimplemented here.**

---

## 2. Modules already provided elsewhere

The A01 blockchain structure names these. They exist and work. This package
consumes them.

| Target module | Already implemented by | Lines | Why not rebuild |
|---|---|---|---|
| `rpc/load_balancer/` | `config/rpc/rpc_manager.py` | 407 | Resolves and ranks endpoints, tracks per-endpoint health, exposes `resolve`, `record_success`, `record_failure`. Endpoint health in two places is worse than in one less obvious place. |
| `rpc/failover/` | `config/rpc/fallback.py` | 324 | Working circuit breaker: `EndpointState`, failure thresholds, cooldown, `select_endpoint`. |
| `decoding/` | `tools/blockchain/evm.py` | 378 | `abi_encode`/`abi_decode`, `function_selector`, `event_topic`, `parse_block`, `parse_log`, `compute_contract_address`. Pure, tested, no network. |
| `adapters/explorers/` | `tools/blockchain/explorer.py` | 173 | `ExplorerClient` ABC plus `LocalExplorer`. The live implementation belongs in `rpc/clients/`, not a parallel adapter tree. |

Transport itself is also not written here: `tools/adapters/rpc.py` is a
JSON-RPC 2.0 client over `http.client` and `tools/adapters/rest.py` is an HTTP
client over `urllib`, both stdlib-only. `rpc/clients/dispatch.py` drives them.

---

## 3. Data flow

```
                    provider catalog          (rpc/providers)
                            │
                    endpoint selection        (config/rpc/rpc_manager)
                            │
                    circuit breaker           (config/rpc/fallback)
                            │
                    rate limit                (rpc/rate_limit)
                            │
                    cache lookup              (rpc/clients/cache)
                            │
                    dispatch ──────────────── (rpc/clients/dispatch)
                            │                        │
                    tools/adapters/{rpc,rest}        └── health feedback ──┐
                            │                                              │
                    CallResult (+ provenance, determined)  ────────────────┘
                            │
                    linkage check             (reorg/detector)
                            │
                    ┌───────┴────────┬──────────────┐
                 EXTENDED          GAP            REORG
                    │                │              │
                 index          backfill        withdraw
```

Three properties hold across the whole path:

**A read either produced an answer or it did not.** `CallResult.determined`
carries which. "The chain has nothing" and "A01 could not ask" both arrive as
an empty result and the evidence standard treats them oppositely — the first
is a finding, the second must never be reported as one.

**Capability is checked before dispatch, not after failure.** A non-archive
endpoint asked for historical state does not reliably error; some return the
latest value, which is a wrong answer wearing the costume of a right one.

**Provenance never carries a URL.** A keyed endpoint holds its credential in
the URL path, and evidence records are written to disk and rendered into
reports. The provider name is the citable identity.

---

## 4. Finality is per chain, not a number

`ChainConfig.confirmations` is one integer, and one integer cannot describe
what these nine chains do. `reorg/finality.py` replaces it with a model.

| Model | Chains | How finality is established |
|---|---|---|
| `DETERMINISTIC` | Ethereum, BNB, Polygon, Avalanche, Solana | The chain states it. Read the `finalized` tag. |
| `SETTLED_ON_L1` | Arbitrum, Optimism, Base | Only as final as the L1 batch that settles it. |
| `PROBABILISTIC` | Bitcoin | No tag exists. Confirmation depth is the correct instrument. |

`depth_is_authoritative` is true only for Bitcoin. For the rollups it is the
case that gets actively wrong: a Base block is sequencer-confirmed in under a
second, so 20 of its own blocks pass in seconds and settle nothing.

Confirming this model against the chain registry surfaced a real defect —
Solana was configured with `confirmations=1`, which is the *processed*
commitment level. A block one slot old can still be dropped, so A01 was
treating unconfirmed state as settled history. Corrected to 32.

---

## 5. Gaps, reorgs, and the one that should be impossible

`reorg/detector.py` classifies every arriving block by parent-hash linkage.
Block numbers alone cannot see a reorg, because the replacement block carries
the same number as the block it replaced.

| Observation | Meaning | Response |
|---|---|---|
| `EXTENDED` | Parent matches the tip | Index it |
| `DUPLICATE` | Same height, same hash | Ignore — backfill and live ingestion overlap at the seam |
| `GAP` | Heights skipped | Backfill `missing_range`. **Missing data, not wrong data** |
| `REORG` | Linkage broke | Withdraw from `rollback_from` |
| `BELOW_WINDOW` | Older than retained history | Cannot check linkage |

Reading a gap as a reorg discards good data; reading a reorg as a gap keeps
bad data and stacks the new chain on top of it.

`ReorgEvent.crossed_finality` is the field that changes what a caller must do.
A reorg reaching below the finalized point cannot legitimately happen on a
deterministic chain, so observing one means something else is true: a provider
is serving a different network, or an endpoint is lying. It is surfaced as an
incident rather than absorbed, because absorbing it would let one bad endpoint
rewrite finalized history.

Detection never mutates. `observe()` reports; `accept_reorg()` acts. A reorg
that crossed finality must not be applied without a decision, and a detector
that applied its own findings would leave nowhere to make one.

---

## 6. Free-tier constraint

A01 is built to run with no credentials. That works, with one measured
consequence, pinned by a test:

**There is no open archive endpoint for any EVM chain.** Public endpoints
serve recent state only.

| Capability | Free tier |
|---|---|
| Current state, whale movement, risk screening | Works |
| EVM historical state / dormancy | Unavailable |
| EVM detector backtesting | Unavailable — so `validated` maturity is unreachable |
| Bitcoin history | Works — Esplora is archival by nature |

`ChainDispatcher.capability_report()` names the environment variable that
would lift each restriction rather than only reporting the gap.

---

## 7. Implementation status

Measured against the working tree.

| Module | Status | Notes |
|---|---|---|
| `rpc/providers/` | **Implemented** | 98 endpoints, 9 chains, 16 keyed providers dormant until keyed. 39 tests. |
| `rpc/clients/` | **Implemented** | Dispatch with failover, capability gating, provenance; finality-aware TTL cache. |
| `rpc/rate_limit/` | **Implemented** | Per-provider token buckets, 429 feedback. |
| `rpc/health_check/` | *Empty* | Live probing. Endpoint health is currently inferred from real traffic via the circuit breaker. |
| `reorg/finality.py` | **Implemented** | Per-chain finality models. |
| `reorg/detector.py` | **Implemented** | Linkage tracking, gap/reorg/violation classification. 28 tests. |
| `reorg/rollback`, `reconciliation` | *Not started* | Act on stored data; blocked on storage. |
| `chains/` | *Empty* | Chain metadata currently lives in `config/rpc/chains.py`. Per-chain YAML is not yet justified. |
| `nodes/` | *Not started* | Self-hosted node management. No node is run today. |
| `indexing/` | *Not started* | **Next slice.** Needs `entities/` and a checkpoint first. |
| `ingestion/` | *Not started* | Backfill and forward-fill are separate modes; the seam between them is `DUPLICATE`. |
| `entities/` | *Not started* | **Next slice.** Canonical block and transaction models. |
| `storage/` | *Not started* | Conceptual lifecycle boundary only — the system of record is `database/`, which does not exist yet either. |
| `validation/` | *Partial* | Cross-source validation is unbuilt; per-endpoint validation is in `config/rpc/rpc_config.py`. |
| `flows/`, `labeling/`, `analytics/` | *Not started* | Downstream of indexing. Building them now would mean analysing data A01 does not store. |
| `monitoring/` | *Partial* | `ChainDispatcher.health()` and `ChainTracker.snapshot()` exist; no aggregation layer. |
| `security/` | *Not started* | Distinct from `config/security/`, which handles secrets. |

### Build order

The remaining work follows the vertical-slice rule — one chain end to end
before breadth:

```
entities/{blocks,transactions}
        ↓
indexing/checkpoint
        ↓
indexing/block_indexer          ← Ethereum only
        ↓
ingestion/{backfill,polling}    ← reorg/detector already gates this
        ↓
storage (via database/)
        ↓
one skill end to end
        ↓
second chain, then breadth
```

`flows/`, `labeling/` and `analytics/` are deliberately last. They are the
visible part, and they are the part that cannot be built honestly until there
is stored, reorg-consistent data underneath them.
