# 09 — Scroll

| Field | Value |
|---|---|
| Chain ID | 534352 |
| Type | EVM (zkEVM rollup) |
| Native | ETH (18 decimals) |
| Block time | ~10s (demand-driven) |
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
- The `finalized` tag is unusable — reads 18.9M blocks behind head;
  `safe` reads null
- Not served by Etherscan V2 — only Blockscout, thinner label coverage
- Blocks are produced on demand — 10.1s measured
