# 07 — Avalanche C-Chain

| Field | Value |
|---|---|
| Chain ID | 43114 |
| Type | EVM |
| Native | AVAX (18 decimals) |
| Block time | 2s |
| Finality | Instant (Snowman consensus) |
| Confirmations | 12 |
| Observable | Yes |
| Token-capable | Yes |

## What A01 can do here

Full EVM sensor and log decoding. No archive on the free tier.

## Providers

7 endpoints — 2 keyed (free tier), 5 open. See `endpoints.yaml`.

## Known limits

- No archive endpoint available
- Consensus finalises in seconds, so a deep confirmation wait costs
  freshness without buying safety
