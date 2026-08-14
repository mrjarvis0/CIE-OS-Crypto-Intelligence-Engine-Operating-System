# 13 — Unichain

| Field | Value |
|---|---|
| Chain ID | 130 |
| Type | EVM (OP-stack L2) |
| Native | ETH (18 decimals) |
| Block time | 1s |
| Finality | Rollup |
| Confirmations | 20 |
| Observable | Yes |
| Token-capable | Yes |

## What A01 can do here

Full EVM sensor and log decoding. No keyed provider catalogued.

## Providers

3 endpoints — all open. See `endpoints.yaml`.

## Known limits

- No keyed provider, so no archive upgrade path
- One-second blocks, so 20 confirmations is 20 seconds of wall time
