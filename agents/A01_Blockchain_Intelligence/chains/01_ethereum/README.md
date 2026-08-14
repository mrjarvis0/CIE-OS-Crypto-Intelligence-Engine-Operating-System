# 01 — Ethereum

| Field | Value |
|---|---|
| Chain ID | 1 |
| Type | EVM |
| Native | ETH (18 decimals) |
| Block time | 12s |
| Finality | Checkpoint (post-merge) |
| Confirmations | 12 |
| Observable | Yes |
| Token-capable | Yes |

## What A01 can do here

Ethereum is A01's most complete chain. Full EVM sensor, log decoding,
archive access via Alchemy, and the deepest ingested window. Exchange
flow attribution is active against the loaded label set.

## Providers

15 endpoints — 7 keyed (free tier), 8 open. See `endpoints.yaml`.
Alchemy is the primary keyed provider and the only one currently active.

## Known limits

- Archive access depends on the keyed provider (ALCHEMY_API_KEY)
- Token decimals unresolved (raw base units only)
- Open endpoints may refuse `eth_getLogs` — verified on 2026-08-11
