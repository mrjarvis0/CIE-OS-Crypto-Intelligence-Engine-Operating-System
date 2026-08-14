# 12 — Mantle

| Field | Value |
|---|---|
| Chain ID | 5000 |
| Type | EVM (L2 rollup) |
| Native | MNT (18 decimals) |
| Block time | 2s |
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
- The native unit is MNT, not ether — values expressed in ether are
  meaningless here; comparing native totals across chains compares
  different assets
