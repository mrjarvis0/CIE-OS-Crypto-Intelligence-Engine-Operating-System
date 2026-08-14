# 08 — Linea

| Field | Value |
|---|---|
| Chain ID | 59144 |
| Type | EVM (zkEVM rollup) |
| Native | ETH (18 decimals) |
| Block time | ~8s (demand-driven) |
| Finality | Rollup |
| Confirmations | 20 |
| Observable | Yes |
| Token-capable | Yes |

## What A01 can do here

Full EVM sensor and log decoding. No keyed provider catalogued.

## Providers

4 endpoints — all open. See `endpoints.yaml`.

## Known limits

- No keyed provider, so no archive upgrade path
- Blocks are produced on demand — 8.4s measured, not the 2s marketing
  suggests
- `safe` and `finalized` return the same block
