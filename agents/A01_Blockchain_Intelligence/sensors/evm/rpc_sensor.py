"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    sensors.evm.rpc_sensor

Purpose:
    Read blocks, heads, and logs from any EVM chain over JSON-RPC.

Design goals:
    - One sensor per chain, built over the shared ChainDispatcher
    - Payloads returned as the provider sent them
    - Finality read from the chain's tag when it has one, never inferred here
    - Log range requests bounded, because providers cap them silently
    - Every failure classified, none raised

Notes:
    This class holds no transport logic of its own. Failover, rate limiting,
    caching, and circuit breaking already exist in
    :class:`blockchain.rpc.clients.dispatch.ChainDispatcher`; duplicating any
    of it here would produce a second, divergent retry policy and the provider
    health recorded in one would be invisible to the other.

    The only translation performed is hex-to-int on block heights, and it is
    structural rather than interpretive: the stream has to be ordered and
    checkpointed by height, so the height must be a number before anything can
    sequence it. The payload itself is untouched -- ``parentHash`` stays
    ``parentHash`` until normalization renames it deliberately.

    Log ranges are clamped because providers enforce their own limits without
    saying so. A 10,000-block ``eth_getLogs`` against a free endpoint commonly
    returns a truncated set with a 200 status, which reads as a complete answer
    and produces a silent hole in history. Requesting a range the endpoint will
    honour, and letting ingestion walk it, is the only way to know the answer
    is whole.
"""

from __future__ import annotations

import logging

from typing import Any, Final

from blockchain.reorg.finality import finality_policy
from blockchain.rpc.clients.dispatch import CallResult, ChainDispatcher
from config.rpc.chains import ChainName, ChainType, get_chain, is_supported_chain
from core.exceptions import SensorError

from ..base import Capability, Sensor, chain_str
from ..envelope import Provenance, RawRecord, RecordKind, SensorResult

logger = logging.getLogger(__name__)

#: Heights per ``eth_getLogs`` request. Chosen to sit inside the smallest cap
#: commonly imposed by free endpoints rather than at the largest that sometimes
#: works, because the failure mode of guessing high is silent truncation.
DEFAULT_LOG_RANGE: Final[int] = 500

#: Methods this sensor issues, named once so provenance and capability checks
#: cannot drift apart from the calls they describe.
_M_BLOCK_NUMBER: Final[str] = "eth_blockNumber"
_M_GET_BLOCK: Final[str] = "eth_getBlockByNumber"
_M_GET_LOGS: Final[str] = "eth_getLogs"


def parse_quantity(value: Any) -> int | None:
    """
    Read an EVM RPC quantity into an int.

    Returns None rather than raising or defaulting to zero. A malformed height
    is not height zero, and a sensor that substitutes a plausible number for
    an unreadable one hands the pipeline a fact the chain never stated.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text, 16) if text.lower().startswith("0x") else int(text, 10)
        except ValueError:
            return None
    return None


def to_quantity(height: int) -> str:
    """Render a height as the hex quantity the RPC expects."""
    if height < 0:
        raise ValueError("height must be >= 0")
    return hex(height)


class EvmRpcSensor(Sensor):
    """
    JSON-RPC sensor for one EVM chain.

    Constructed against a chain in ``config/rpc/chains.py``. An unregistered
    chain raises at construction rather than failing on first read, so a typo
    surfaces at wiring time instead of halfway through a backfill.
    """

    def __init__(
        self,
        chain: ChainName | str,
        *,
        dispatcher: ChainDispatcher | None = None,
        log_range: int = DEFAULT_LOG_RANGE,
    ) -> None:
        name = chain_str(chain)
        if not is_supported_chain(name):
            raise SensorError(
                f"chain {name!r} is not in the chain registry",
                sensor="evm_rpc",
                chain=name,
            )
        if log_range <= 0:
            raise SensorError(
                "log_range must be > 0", sensor="evm_rpc", chain=name
            )

        config = get_chain(name)
        if config.chain_type is not ChainType.EVM:
            # Solana and Bitcoin speak a different JSON-RPC entirely. Accepting
            # them here would produce a sensor that answers every call with a
            # method-not-found, which reads as an outage rather than as the
            # wiring mistake it is.
            raise SensorError(
                f"{name} is {config.chain_type.value}, not EVM; "
                "use a chain-specific sensor",
                sensor="evm_rpc",
                chain=name,
            )

        self._chain = name
        self._config = config
        self._policy = finality_policy(name)
        self._dispatcher = dispatcher if dispatcher is not None else ChainDispatcher()
        self._log_range = log_range
        self.name = f"evm_rpc:{name}"

    # -- identity --------------------------------------------------------

    @property
    def chain(self) -> str:
        return self._chain

    @property
    def dispatcher(self) -> ChainDispatcher:
        return self._dispatcher

    @property
    def log_range(self) -> int:
        return self._log_range

    @property
    def confirmations(self) -> int:
        """Depth at which this chain is treated as settled when no tag exists."""
        return self._policy.confirmations

    # -- capability ------------------------------------------------------

    def capability(self) -> Capability:
        report = self._dispatcher.capability_report(self._chain)
        return Capability(
            chain=self._chain,
            reachable=bool(report.get("reachable")),
            archive=bool(report.get("archive")),
            logs=bool(report.get("logs")),
            endpoints=int(report.get("endpoints") or 0),
            blocked_by=str(report.get("archive_blocked_by") or ""),
            unlocked_by=tuple(report.get("archive_unlocked_by") or ()),
        )

    # -- reads -----------------------------------------------------------

    def head(self) -> SensorResult:
        """The current chain head height."""
        result = self._dispatcher.call(self._chain, _M_BLOCK_NUMBER, [])
        if not result.determined:
            return self._undetermined(result, _M_BLOCK_NUMBER)

        height = parse_quantity(result.value)
        if height is None:
            return self._malformed(
                result, _M_BLOCK_NUMBER, f"unreadable head quantity: {result.value!r}"
            )

        return self._determined(result, RecordKind.HEAD, height, height)

    def finalized_head(self) -> SensorResult:
        """
        The height the chain reports as finalized.

        Declines when the chain has no authoritative tag. Substituting a
        confirmation-depth estimate here would let a rollback be justified by
        a guess, so the depth fallback stays with the caller that can label it
        as one -- see :meth:`blockchain.reorg.finality.FinalityPolicy.is_final_by_depth`.
        """
        tag = self._policy.finalized_tag
        if tag is None:
            return SensorResult(
                determined=False,
                chain=self._chain,
                method=_M_GET_BLOCK,
                outcome="capability_unavailable",
                reason=(
                    f"{self._chain} finality is {self._policy.model.value}; "
                    "no authoritative tag to read"
                ),
            )

        result = self._dispatcher.call(self._chain, _M_GET_BLOCK, [tag, False])
        if not result.determined:
            return self._undetermined(result, _M_GET_BLOCK)

        payload = result.value
        if not isinstance(payload, dict):
            return self._malformed(
                result, _M_GET_BLOCK, f"{tag} tag returned {type(payload).__name__}"
            )

        height = parse_quantity(payload.get("number"))
        if height is None:
            return self._malformed(
                result, _M_GET_BLOCK, f"{tag} block has no readable number"
            )

        return self._determined(result, RecordKind.FINALIZED_HEAD, height, payload)

    def block(self, height: int, *, include_transactions: bool = False) -> SensorResult:
        """
        One block by height.

        ``include_transactions`` asks the provider to expand transaction
        objects inline. Left false by default: the expanded form is an order of
        magnitude larger, and ingestion only needs linkage to track the chain.
        """
        if height < 0:
            raise SensorError(
                "height must be >= 0", sensor=self.name, chain=self._chain
            )

        params = [to_quantity(height), bool(include_transactions)]
        result = self._dispatcher.call(self._chain, _M_GET_BLOCK, params)
        if not result.determined:
            return self._undetermined(result, _M_GET_BLOCK)

        payload = result.value
        # A null block is a determined answer: the height is not yet produced,
        # or this endpoint has not caught up to it. Either way it is not an
        # error, and the caller decides whether to wait or move on.
        if payload is None:
            return SensorResult(
                determined=True,
                record=None,
                chain=self._chain,
                method=_M_GET_BLOCK,
                outcome=result.outcome.value,
                reason=f"block {height} not present at {result.provider}",
                duration_ms=result.duration_ms,
            )

        if not isinstance(payload, dict):
            return self._malformed(
                result, _M_GET_BLOCK, f"block returned {type(payload).__name__}"
            )

        reported = parse_quantity(payload.get("number"))
        if reported is not None and reported != height:
            # Asking for 100 and being handed 99 means the endpoint is behind,
            # serving another network, or ignoring the parameter. Recording it
            # under the requested height would corrupt the stream.
            return self._malformed(
                result,
                _M_GET_BLOCK,
                f"requested block {height}, provider returned {reported}",
            )

        return self._determined(result, RecordKind.BLOCK, height, payload)

    def logs(
        self,
        from_height: int,
        to_height: int,
        *,
        address: str | None = None,
        topics: list[Any] | None = None,
    ) -> SensorResult:
        """
        Logs over an inclusive height range.

        Refuses a range wider than :attr:`log_range` instead of trimming it.
        Trimming would return a correct-looking answer for a narrower window
        than the caller asked about, and the caller would record it as covering
        the whole range.
        """
        if from_height < 0 or to_height < 0:
            raise SensorError(
                "log heights must be >= 0", sensor=self.name, chain=self._chain
            )
        if to_height < from_height:
            raise SensorError(
                f"log range {from_height}-{to_height} is inverted",
                sensor=self.name,
                chain=self._chain,
            )

        span = to_height - from_height + 1
        if span > self._log_range:
            return SensorResult(
                determined=False,
                chain=self._chain,
                method=_M_GET_LOGS,
                outcome="range_too_wide",
                reason=(
                    f"requested {span} heights, limit is {self._log_range}; "
                    "split the range rather than accepting a truncated answer"
                ),
            )

        query: dict[str, Any] = {
            "fromBlock": to_quantity(from_height),
            "toBlock": to_quantity(to_height),
        }
        if address:
            query["address"] = address
        if topics:
            query["topics"] = topics

        result = self._dispatcher.call(
            self._chain, _M_GET_LOGS, [query], require_logs=True
        )
        if not result.determined:
            return self._undetermined(result, _M_GET_LOGS)

        payload = result.value
        if payload is None:
            payload = []
        if not isinstance(payload, list):
            return self._malformed(
                result, _M_GET_LOGS, f"logs returned {type(payload).__name__}"
            )

        # Height is the range start: a log batch spans heights, so no single
        # one identifies it, and the start is what a checkpoint advances from.
        return self._determined(result, RecordKind.LOGS, from_height, payload)

    # -- health ----------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return {
            "sensor": self.name,
            "chain": self._chain,
            "chain_id": self._config.chain_id,
            "confirmations": self._policy.confirmations,
            "finality_model": self._policy.model.value,
            "finalized_tag": self._policy.finalized_tag,
            "log_range": self._log_range,
            "capability": self.capability().as_dict(),
        }

    # -- result construction ---------------------------------------------

    def _determined(
        self,
        result: CallResult,
        kind: RecordKind,
        height: int | None,
        payload: Any,
    ) -> SensorResult:
        record = RawRecord(
            chain=self._chain,
            kind=kind,
            payload=payload,
            height=height,
            provenance=Provenance(
                provider=result.provider,
                chain=self._chain,
                method=result.method,
                outcome=result.outcome.value,
                from_cache=result.from_cache,
                attempts=result.attempts,
            ),
        )
        return SensorResult(
            determined=True,
            record=record,
            chain=self._chain,
            method=result.method,
            outcome=result.outcome.value,
            duration_ms=result.duration_ms,
        )

    def _undetermined(self, result: CallResult, method: str) -> SensorResult:
        return SensorResult(
            determined=False,
            chain=self._chain,
            method=result.method or method,
            outcome=result.outcome.value,
            reason=result.reason or f"{method} undetermined",
            duration_ms=result.duration_ms,
        )

    def _malformed(self, result: CallResult, method: str, reason: str) -> SensorResult:
        """
        A provider answered, and the answer cannot be trusted.

        Kept distinct from a transport failure. A transport failure suggests
        retrying elsewhere; a malformed answer from a reachable provider
        suggests that provider is wrong, and the two should not share a
        counter.
        """
        logger.warning("%s: %s (provider=%s)", self.name, reason, result.provider)
        return SensorResult(
            determined=False,
            chain=self._chain,
            method=result.method or method,
            outcome="malformed_response",
            reason=reason,
            duration_ms=result.duration_ms,
        )


__all__ = [
    "DEFAULT_LOG_RANGE",
    "EvmRpcSensor",
    "parse_quantity",
    "to_quantity",
]
