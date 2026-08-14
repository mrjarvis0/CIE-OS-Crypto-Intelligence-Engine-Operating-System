"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    knowledge.chains

Purpose:
    What A01 can and cannot learn about each registered chain.

Design goals:
    - Capability, not configuration; the registry stays the source for the latter
    - Measured facts, dated, with a way to re-measure them
    - Limits stated as plainly as capabilities
    - No network at import; `probe()` is opt-in
    - Answers a question no other module answers

Notes:
    ``config/rpc/chains.py`` says what a chain *is* -- its id, its native
    currency, its block time. This module says what A01 can *do* with it, which
    is a different question and one nothing else answers. A caller deciding
    whether to trust an analysis on Arbitrum needs to know that native transfers
    there are routinely zero and the activity is all in token logs; no chain id
    tells them that.

    The registry is imported, never restated. Duplicating chain ids here would
    give A01 two answers to the same question and no way to notice when they
    diverge.

    **The capability facts are measured, not assumed.** Every value in
    :data:`CAPABILITIES` came from probing the live chain through A01's own
    sensor stack on the date recorded. :func:`probe` re-measures, so the table
    can be checked rather than trusted -- and on 2026-08-14 it was, which is how
    five rows came to change.

    ``archive_available`` used to read ``False`` on every chain, because the
    open endpoints A01 defaults to serve recent state only. It now reads
    ``True`` on the five chains a configured Alchemy key reaches. Nothing about
    those chains changed; a credential appeared. The distinction is kept visible
    through :data:`_ARCHIVE_VIA_KEY` rather than flattened into a property of
    the chain, because withdrawing the key withdraws the capability.

    The limits are the part worth reading. A chain A01 can reach is not a chain
    A01 understands: Solana and Bitcoin are in the registry with working
    endpoints and no sensor, because their RPC dialects are not EVM and a
    dialect A01 cannot parse is a chain it cannot observe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Final

from config.rpc.chains import ChainConfig, ChainName, ChainType, get_chain

#: When the capability table below was last measured against live endpoints.
#: Stated so a reader can judge how stale it might be, rather than assuming it
#: is current.
MEASURED_ON: Final[date] = date(2026, 8, 14)


class Finality(StrEnum):
    """How a chain decides a block will not be reverted."""

    #: An explicit finalized tag the node will serve (Ethereum post-merge).
    CHECKPOINT = "checkpoint"
    #: Finality inherited from a settlement layer, with a challenge window.
    ROLLUP = "rollup"
    #: Probabilistic: deeper is safer, nothing is ever certain.
    PROBABILISTIC = "probabilistic"
    #: Fast deterministic finality from the consensus protocol itself.
    INSTANT = "instant"


@dataclass(frozen=True, slots=True)
class ChainCapability:
    """
    What A01 can observe on one chain, and what it cannot.

    ``limits`` is not a disclaimer section. Each entry is a specific thing a
    reader would otherwise wrongly assume from the presence of the chain in
    this table.
    """

    chain: str
    #: A sensor exists that speaks this chain's RPC dialect.
    has_sensor: bool
    #: Event logs are reachable, which is what makes token decoding possible.
    supports_logs: bool
    #: Historical state at arbitrary depth. False on every free endpoint.
    archive_available: bool
    finality: Finality
    #: Confirmations A01 waits before treating a block as settled.
    reorg_depth: int
    limits: tuple[str, ...] = field(default_factory=tuple)

    @property
    def observable(self) -> bool:
        """Whether A01 can capture this chain at all."""
        return self.has_sensor

    @property
    def token_capable(self) -> bool:
        """Whether ERC-20 and ERC-721 movement can be decoded here."""
        return self.has_sensor and self.supports_logs

    @property
    def config(self) -> ChainConfig:
        """The registry entry. Imported, not restated."""
        return get_chain(self.chain)

    def as_dict(self) -> dict[str, Any]:
        cfg = self.config
        return {
            "chain": self.chain,
            "display_name": cfg.display_name,
            "chain_id": cfg.chain_id,
            "chain_type": cfg.chain_type.value,
            "native_currency": cfg.native_currency.symbol,
            "native_decimals": cfg.native_currency.decimals,
            "block_time_seconds": cfg.average_block_time_seconds,
            "confirmations": cfg.confirmations,
            "has_sensor": self.has_sensor,
            "supports_logs": self.supports_logs,
            "archive_available": self.archive_available,
            "finality": self.finality.value,
            "reorg_depth": self.reorg_depth,
            "observable": self.observable,
            "token_capable": self.token_capable,
            "limits": list(self.limits),
            "measured_on": MEASURED_ON.isoformat(),
        }


#: A limit true of every chain A01 reaches on open endpoints alone.
_NO_ARCHIVE: Final[str] = (
    "no archive endpoint on the free tier, so historical state is unreachable; "
    "block and log history is fine, contract state at depth is not"
)

#: The counterpart, and the reason ``archive_available`` moved on five chains
#: between the 2026-08-10 and 2026-08-14 measurements. Nothing about those
#: chains changed; a keyed provider was configured. Recorded as a conditional
#: rather than as a property of the chain, because it reverts the moment the
#: credential is withdrawn.
_ARCHIVE_VIA_KEY: Final[str] = (
    "archive access here comes from the keyed provider, not from the chain: "
    "without ALCHEMY_API_KEY this reverts to recent-state only, and dormancy "
    "questions become unanswerable again"
)

#: The six chains added on 2026-08-14 have open endpoints and no keyed one.
_NO_KEYED_ROUTE: Final[str] = (
    "no keyed provider is catalogued for this chain, so there is no archive "
    "upgrade path: DET-DORMANT-01 and any backtest are unavailable here until "
    "one exists"
)

#: The L2 observation that motivated token decoding. Measured: on live Arbitrum
#: and Optimism blocks the largest native transfer was 0.0000.
_L2_NATIVE_EMPTY: Final[str] = (
    "native transfers are routinely 0 here; real movement is in token logs, so "
    "ingest with --tokens or A01 sees an idle chain that is not idle"
)

_NO_DECIMALS: Final[str] = (
    "token decimals are unresolved (needs eth_call), so token amounts are raw "
    "base units — comparable within one token and never across tokens"
)


CAPABILITIES: Final[tuple[ChainCapability, ...]] = (
    ChainCapability(
        chain=ChainName.ETHEREUM.value,
        has_sensor=True,
        supports_logs=True,
        archive_available=True,
        finality=Finality.CHECKPOINT,
        reorg_depth=12,
        limits=(
            _ARCHIVE_VIA_KEY,
            _NO_DECIMALS,
            "a single block emits ~600–2,400 logs, of which a few hundred are "
            "transfers; the rest are protocol events A01 does not decode",
        ),
    ),
    ChainCapability(
        chain=ChainName.BNB_CHAIN.value,
        has_sensor=True,
        supports_logs=True,
        archive_available=False,
        finality=Finality.PROBABILISTIC,
        reorg_depth=15,
        limits=(
            _NO_ARCHIVE,
            _NO_DECIMALS,
            "short block time and a small validator set make reorgs more common "
            "than on Ethereum; the withdrawal path sees more use here",
        ),
    ),
    ChainCapability(
        chain=ChainName.POLYGON.value,
        has_sensor=True,
        supports_logs=True,
        archive_available=True,
        finality=Finality.CHECKPOINT,
        reorg_depth=128,
        limits=(
            _ARCHIVE_VIA_KEY,
            _NO_DECIMALS,
            "deep reorgs are normal before checkpoint; a shallow confirmation "
            "depth here produces withdrawals that need not have happened",
        ),
    ),
    ChainCapability(
        chain=ChainName.ARBITRUM.value,
        has_sensor=True,
        supports_logs=True,
        archive_available=True,
        finality=Finality.ROLLUP,
        reorg_depth=20,
        limits=(
            _ARCHIVE_VIA_KEY,
            _NO_DECIMALS,
            _L2_NATIVE_EMPTY,
            "sequencer ordering is not final until the batch settles on "
            "Ethereum; a settled-looking block can still change",
        ),
    ),
    ChainCapability(
        chain=ChainName.OPTIMISM.value,
        has_sensor=True,
        supports_logs=True,
        archive_available=True,
        finality=Finality.ROLLUP,
        reorg_depth=20,
        limits=(_ARCHIVE_VIA_KEY, _NO_DECIMALS, _L2_NATIVE_EMPTY),
    ),
    ChainCapability(
        chain=ChainName.BASE.value,
        has_sensor=True,
        supports_logs=True,
        archive_available=True,
        finality=Finality.ROLLUP,
        reorg_depth=20,
        limits=(_ARCHIVE_VIA_KEY, _NO_DECIMALS, _L2_NATIVE_EMPTY),
    ),
    ChainCapability(
        chain=ChainName.AVALANCHE.value,
        has_sensor=True,
        supports_logs=True,
        archive_available=False,
        finality=Finality.INSTANT,
        reorg_depth=5,
        limits=(
            _NO_ARCHIVE,
            _NO_DECIMALS,
            "consensus finalises in seconds, so a deep confirmation wait costs "
            "freshness without buying safety",
        ),
    ),
    # -- added 2026-08-14 --------------------------------------------------
    #
    # All six were probed through `probe()` -- A01's own sensor stack, not a
    # bare HTTP call -- and every one returned reachable, sensored and
    # log-capable. That is the whole test of "supported": the endpoints being
    # live proves the chain is up, and only the sensor answering proves A01 can
    # read it.
    ChainCapability(
        chain=ChainName.LINEA.value,
        has_sensor=True,
        supports_logs=True,
        archive_available=False,
        finality=Finality.ROLLUP,
        reorg_depth=20,
        limits=(
            _NO_ARCHIVE,
            _NO_KEYED_ROUTE,
            _NO_DECIMALS,
            _L2_NATIVE_EMPTY,
            "blocks are produced on demand: 8.4s measured over 500 blocks, not "
            "the 2s a reader would assume, and the rate moves with activity",
            "safe and finalized return the same block, so there is no cheaper "
            "intermediate read here",
        ),
    ),
    ChainCapability(
        chain=ChainName.SCROLL.value,
        has_sensor=True,
        supports_logs=True,
        archive_available=False,
        finality=Finality.ROLLUP,
        reorg_depth=20,
        limits=(
            _NO_ARCHIVE,
            _NO_KEYED_ROUTE,
            _NO_DECIMALS,
            _L2_NATIVE_EMPTY,
            "the finalized tag is unusable: it reads 18.9M blocks behind head "
            "and safe reads null, so finality here is unestablished rather "
            "than approximated — see blockchain/reorg/finality.py",
            "not served by Etherscan V2, so its only explorer is Blockscout "
            "and label coverage is thinner than on the other EVM chains",
            "blocks are produced on demand: 10.1s measured over 500 blocks",
        ),
    ),
    ChainCapability(
        chain=ChainName.GNOSIS.value,
        has_sensor=True,
        supports_logs=True,
        archive_available=False,
        finality=Finality.CHECKPOINT,
        reorg_depth=32,
        limits=(
            _NO_ARCHIVE,
            _NO_KEYED_ROUTE,
            _NO_DECIMALS,
            "the native unit is xDAI, a stablecoin: a materiality floor of 1e18 "
            "means roughly one dollar here and roughly four thousand on "
            "Ethereum, so a floor carried across chains is not one threshold",
        ),
    ),
    ChainCapability(
        chain=ChainName.CELO.value,
        has_sensor=True,
        supports_logs=True,
        archive_available=False,
        finality=Finality.ROLLUP,
        reorg_depth=20,
        limits=(
            _NO_ARCHIVE,
            _NO_KEYED_ROUTE,
            _NO_DECIMALS,
            _L2_NATIVE_EMPTY,
            "one-second blocks, so 20 confirmations is twenty seconds of wall "
            "time against Base's forty for the same depth",
        ),
    ),
    ChainCapability(
        chain=ChainName.MANTLE.value,
        has_sensor=True,
        supports_logs=True,
        archive_available=False,
        finality=Finality.ROLLUP,
        reorg_depth=20,
        limits=(
            _NO_ARCHIVE,
            _NO_KEYED_ROUTE,
            _NO_DECIMALS,
            _L2_NATIVE_EMPTY,
            "the native unit is MNT, not ether, so a value expressed in ether "
            "is meaningless here and comparing native totals across chains "
            "compares different assets",
        ),
    ),
    ChainCapability(
        chain=ChainName.UNICHAIN.value,
        has_sensor=True,
        supports_logs=True,
        archive_available=False,
        finality=Finality.ROLLUP,
        reorg_depth=20,
        limits=(
            _NO_ARCHIVE,
            _NO_KEYED_ROUTE,
            _NO_DECIMALS,
            _L2_NATIVE_EMPTY,
            "one-second blocks; see the note on Celo's confirmation depth",
        ),
    ),
    ChainCapability(
        chain=ChainName.SOLANA.value,
        has_sensor=False,
        supports_logs=False,
        archive_available=False,
        finality=Finality.CHECKPOINT,
        reorg_depth=32,
        limits=(
            "no sensor: the RPC dialect is not EVM, so registered endpoints are "
            "reachable and unusable — A01 cannot observe this chain at all",
            "slots differ from blocks and can be skipped, so height arithmetic "
            "that works on EVM does not transfer",
        ),
    ),
    ChainCapability(
        chain=ChainName.BITCOIN.value,
        has_sensor=False,
        supports_logs=False,
        archive_available=False,
        finality=Finality.PROBABILISTIC,
        reorg_depth=6,
        limits=(
            "no sensor: the RPC dialect is not EVM, so registered endpoints are "
            "reachable and unusable — A01 cannot observe this chain at all",
            "UTXO, not accounts: there are no addresses with balances to profile "
            "and no event logs, so most of A01's analysis has no counterpart here",
        ),
    ),
)

_BY_NAME: Final[dict[str, ChainCapability]] = {c.chain: c for c in CAPABILITIES}


# ==============================================================================
# LOOKUP
# ==============================================================================


def capability(chain: ChainName | str) -> ChainCapability:
    """
    What A01 can do on one chain.

    Raises rather than returning a permissive default. A caller that receives
    a fabricated "yes, fully supported" for an unknown chain would proceed to
    analyse nothing and report it as an absence.
    """
    name = str(chain)
    found = _BY_NAME.get(name)
    if found is None:
        raise KeyError(
            f"no capability record for {name!r}; known: {', '.join(sorted(_BY_NAME))}"
        )
    return found


def observable_chains() -> tuple[str, ...]:
    """Chains A01 can actually capture today."""
    return tuple(c.chain for c in CAPABILITIES if c.observable)


def token_capable_chains() -> tuple[str, ...]:
    """Chains where ERC-20 and ERC-721 movement can be decoded."""
    return tuple(c.chain for c in CAPABILITIES if c.token_capable)


def registry_only_chains() -> tuple[str, ...]:
    """
    Chains configured but unobservable.

    Kept visible rather than filtered out of the registry: the endpoints are
    real and the gap is a missing sensor, which is a different problem from an
    unsupported chain and has a different fix.
    """
    return tuple(c.chain for c in CAPABILITIES if not c.observable)


def summary() -> dict[str, Any]:
    """Everything, for `cli chains` and the dashboard."""
    return {
        "measured_on": MEASURED_ON.isoformat(),
        "total": len(CAPABILITIES),
        "observable": len(observable_chains()),
        "token_capable": len(token_capable_chains()),
        "registry_only": list(registry_only_chains()),
        "chains": [c.as_dict() for c in CAPABILITIES],
    }


# ==============================================================================
# RE-MEASUREMENT
# ==============================================================================


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """One chain re-measured against live endpoints."""

    chain: str
    reachable: bool
    has_sensor: bool
    supports_logs: bool
    archive_available: bool
    head: int | None = None
    error: str = ""

    def disagrees_with_table(self) -> tuple[str, ...]:
        """
        Fields where the live chain contradicts :data:`CAPABILITIES`.

        The point of the whole module: a table of measured facts is only honest
        if it can be re-checked. A drift here means the record is stale, not
        that the chain is wrong.
        """
        try:
            known = capability(self.chain)
        except KeyError:
            return ("chain is not in the capability table",)

        drift: list[str] = []
        if self.reachable and known.has_sensor != self.has_sensor:
            drift.append(f"has_sensor: table {known.has_sensor}, live {self.has_sensor}")
        if self.reachable and known.supports_logs != self.supports_logs:
            drift.append(
                f"supports_logs: table {known.supports_logs}, live {self.supports_logs}"
            )
        if self.reachable and known.archive_available != self.archive_available:
            drift.append(
                f"archive_available: table {known.archive_available}, "
                f"live {self.archive_available}"
            )
        return tuple(drift)

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "reachable": self.reachable,
            "has_sensor": self.has_sensor,
            "supports_logs": self.supports_logs,
            "archive_available": self.archive_available,
            "head": self.head,
            "error": self.error,
            "drift": list(self.disagrees_with_table()),
        }


def probe(chain: ChainName | str) -> ProbeResult:
    """
    Re-measure one chain against live endpoints.

    Opt-in and never called at import: this module must be readable offline,
    and a knowledge base that needs the network to be read is not one.
    """
    name = str(chain)
    try:
        from sensors import SensorRegistry

        sensor = SensorRegistry().get(name)
    except Exception as exc:  # noqa: BLE001 - no sensor is a result, not a fault
        return ProbeResult(
            chain=name,
            reachable=False,
            has_sensor=False,
            supports_logs=False,
            archive_available=False,
            error=str(exc),
        )

    caps = sensor.capability()
    head = sensor.head()

    return ProbeResult(
        chain=name,
        reachable=caps.reachable,
        has_sensor=True,
        supports_logs=caps.logs,
        archive_available=caps.archive,
        head=head.unwrap().height if head.ok else None,
        error="" if head.ok else (head.reason or "head undetermined"),
    )


__all__ = [
    "CAPABILITIES",
    "MEASURED_ON",
    "ChainCapability",
    "Finality",
    "ProbeResult",
    "capability",
    "observable_chains",
    "probe",
    "registry_only_chains",
    "summary",
    "token_capable_chains",
]
