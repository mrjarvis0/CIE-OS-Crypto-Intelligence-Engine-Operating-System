# skills — Capability Layer

The A01 capability layer. **One skill = one responsibility.** A skill is a
self-contained vertical slice: it orchestrates the tools/data it needs,
applies its policy and guardrails, and produces a typed, structured output.
Skills do **not** combine other skills — that is the job of the
`intelligence/` engines.

## Status

Four of nineteen are implemented. `python -m cli skills` prints the current
state, including what blocks each unbuilt one — an unexplained absence is
indistinguishable from an oversight.

| Skill | State | Bounded by |
| --- | --- | --- |
| `wallet_lookup` | implemented | no balance sensor, so materiality is unavailable |
| `whale_detection` | implemented | no price feed; does not read the label ledger |
| `token_flow` | implemented | no event-log decoding; native value only |
| `exchange_flow` | implemented | an unverified label list; native value only |
| the other fifteen | planned | see `skills.registry.PLANNED_SKILLS` |

`exchange_flow` is the first skill whose answer rests on something A01 did not
observe. Direction comes from an address list loaded with `a01 labels --load`,
so every figure it produces carries that list's source and confidence, and a
transfer between two labelled addresses is reported as internal movement rather
than as a deposit.

### Coverage is part of every answer

A skill reads storage, and storage holds only what was ingested. So "no
activity found" is a statement about the database, and asked of a shallow one
it is true of the database and false of the chain — with nothing in the number
to show the difference.

Every result therefore carries a `Coverage`, and a skill consults
`coverage.supports_absence` before reporting that something did *not* happen.
Where the window is too thin, the field is **withheld** rather than supplied:
the detector above already handles a missing field honestly, and it has no way
to notice a plausible lie.

```
skills/
├── wallet_lookup/        Wallet entity resolution and profile
├── whale_detection/      Large-holder / whale behavior detection
├── smart_money/          Smart-money flow tracking
├── exchange_flow/        Exchange inflow/outflow analysis
├── stablecoin/           Stablecoin mint/burn/transfer intelligence
├── token_unlock/         Token unlock & vesting schedules
├── staking/              Staking / delegation / yield analysis
├── validator/            Validator health and behavior
├── mining/               Miner / pool activity
├── defi/                 DeFi protocol positions, liquidity, risk
├── nft/                  NFT collection and trading analysis
├── governance/           DAO votes, proposals, governance power
├── bridge/               Cross-chain bridge activity and risk
├── smart_contract/       Contract analysis (code, events, state)
├── security/             Exploit, rug-pull, approval-risk screening
├── network_health/       Chain health metrics
├── cross_chain/          Multi-chain flow correlation
└── developer_activity/   On-chain developer / deployment activity
```

## Rules

1. A skill depends on `blockchain/` (domain data), `database/`, `memory/`,
   and `tools/` — never on another skill.
2. A skill exposes a typed input/output contract (`schemas/`) and is
   independently testable.
3. Do **not** scaffold all 18 skills at once. Build one skill end-to-end
   through the full pipeline, validate it, then move to the next.
4. Skills stay deterministic-first; AI assists, never substitutes, verified
   data.

## Skill → Engine relationship

```
Skill = one responsibility           Intelligence Engine = multiple skills
                                       combined into higher-order reasoning
wallet_lookup ─┐
whale_detection├─► behavior_engine / anomaly_engine / risk_engine / ...
exchange_flow ─┘
```
