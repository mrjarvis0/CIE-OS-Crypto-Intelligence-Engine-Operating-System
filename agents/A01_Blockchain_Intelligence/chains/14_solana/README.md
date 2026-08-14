# 14 — Solana

| Field | Value |
|---|---|
| Chain ID | — |
| Type | Solana-like |
| Native | SOL (9 decimals) |
| Block time | ~1s (slots) |
| Finality | Checkpoint |
| Confirmations | 32 |
| Observable | **No** |
| Token-capable | No |

## What A01 can do here

**Nothing yet.** Endpoints are registered and reachable, but A01 has no
sensor that speaks the Solana RPC dialect. The chain is in the catalog so
that its status is visible rather than silently absent.

## What would be needed

A `SolanaSensor` implementation. Solana's JSON-RPC uses different methods
from EVM (`getBlock`, `getTransaction`, `getSignaturesForAddress` rather
than `eth_getBlockByNumber`, `eth_getTransactionReceipt`, `eth_getLogs`).
Slots can be skipped, so height arithmetic that works on EVM does not
transfer.

## Providers

7 endpoints — 2 keyed (Helius, QuickNode), 5 open. See `endpoints.yaml`.

## Known limits

- No sensor — A01 cannot observe this chain at all
- Slots differ from blocks and can be skipped
- Commitment levels are processed/confirmed/finalized
