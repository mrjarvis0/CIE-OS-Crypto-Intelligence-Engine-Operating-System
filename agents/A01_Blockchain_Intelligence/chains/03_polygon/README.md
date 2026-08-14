# 03 — Polygon

| Field | Value |
|---|---|
| Chain ID | 137 |
| Type | EVM |
| Native | POL (18 decimals) |
| Block time | 2s |
| Finality | Checkpoint |
| Confirmations | 128 |
| Observable | Yes |
| Token-capable | Yes |

## What A01 can do here

Full EVM sensor and log decoding. Archive available via Alchemy.

## Providers

10 endpoints — 4 keyed (free tier), 6 open. See `endpoints.yaml`.

## Known limits

- Deep reorgs are normal before checkpoint; 128 confirmations is the
  real safety depth, not a conservative choice
- Token decimals unresolved
