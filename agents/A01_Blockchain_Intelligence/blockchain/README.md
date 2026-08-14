# blockchain — Blockchain Data & Intelligence Subsystem

A01's dedicated multi-chain data infrastructure. Raw chain data enters here,
is indexed, validated, labeled, and turned into queryable domain knowledge for
`skills/` and `intelligence/`.

```
blockchain/
├── chains/       Chain knowledge/config (id, native token, finality, RPC, explorers)
├── rpc/          RPC clients, providers, load balancer, health, failover, rate limit
├── nodes/        Node management (full, archive, light, health)
├── indexing/     The heart — block/tx/receipt/log/trace/state/token/contract indexers
├── ingestion/    realtime, websocket, polling, backfill, replay, mempool
├── reorg/        Detector, tracker, rollback, reconciliation, finality
├── decoding/     ABI, events, functions, errors, calldata, traces, selectors
├── entities/     Blocks, transactions, wallets, contracts, tokens, protocols,
│                 exchanges, bridges, validators
├── flows/        wallet/exchange/whale/stablecoin/bridge/defi/cross-chain flows
├── labeling/     wallet/entity/contract/protocol/exchange/smart-money labels
├── analytics/    balances, transfers, holders, gas, activity, fees, supply,
│                 staking, liquidity
├── validation/   block/tx/event/rpc/cross-source validation + consistency
├── storage/      Data lifecycle: raw → normalized → indexed → snapshots → archives
├── adapters/     explorers, defi, bridges, exchanges, analytics, third-party
├── monitoring/   sync status, lag, missing blocks, rpc errors, metrics, quality
└── security/     rpc/contract security, exploit/rug detection, approval risk,
                  anomaly detection
```

## Position in the pipeline

`blockchain/` is the **chain-aware domain layer**. The generic pipeline
(`sensors/` → `ingestion/` → `normalization/` → `database/`) remains the
single source of orchestration and storage truth. This folder provides
blockchain-specific implementations, models, and intelligence that those
layers use — it must **not** duplicate their responsibility:

| If you need… | Use… |
| --- | --- |
| A data source client | `sensors/` (+ chain config here) |
| Data collection orchestration | `ingestion/` (top-level) |
| Canonical schema | `schemas/` (+ chain-specific here) |
| Permanent storage | `database/` (+ lifecycle mapping here) |
| A capability | `skills/` |
| Higher-order reasoning | `intelligence/` engines |

## Data flow (production pattern, research-validated)

```
Chain → RPC (load-balanced, failover, rate-limited)
     → ingestion (polling = canonical source of truth; WS = realtime layer only)
     → normalization (dedup via (chain_id, tx_hash, log_index); idempotent writes)
     → indexing (blocks + receipts + logs, block_hash stored alongside events)
     → reorg (parent-hash continuity check, rollback to common ancestor,
              reprocess; confirmations N before finality)
     → validation (cross-source hash comparison → confidence tagging)
     → database (atomic upserts, raw logs kept as insurance)
     → labeling/analytics/flows → skills → intelligence engines
```

## Empty directories

All leaf directories are scaffolded with `.gitkeep`. Per the vertical-slice
rule, start with **1 chain + 1 RPC + block/tx indexing + ingestion + reorg +
database + 1 skill**, then expand to remaining chains and indexers.
