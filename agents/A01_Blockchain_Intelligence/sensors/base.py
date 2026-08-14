"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    sensors.base

Purpose:
    The contract every sensor implements, and the capability report that lets
    a caller find out what a sensor cannot do before asking it.

Design goals:
    - One sensor answers for one chain
    - Capture only; a sensor that scores, ranks, or classifies is a violation
    - Capability declared up front, not discovered through failures
    - Every read returns a SensorResult, never a bare payload

Notes:
    The reason capability is declared rather than probed is that probing
    conflates two different negatives. An archive read against a chain with no
    archive endpoint fails; so does an archive read against a chain that has
    one which happens to be down. The first is permanent and should change
    what a detector attempts, the second is transient and should be retried.
    A sensor that only reports "it failed" leaves the caller to guess, and the
    usual guess is to retry the permanent case forever.

    Sensors are synchronous because the transport beneath them is. Wrapping a
    blocking dispatcher in ``async def`` would advertise concurrency the stack
    cannot deliver, and the pretence is worse than the limitation: callers
    would schedule work on the assumption that reads yield, and they do not.
    Ingestion drives sensors from its own loop, which is where the pacing
    decision belongs anyway.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from config.rpc.chains import ChainName

from .envelope import RawRecord, RecordKind, SensorResult


@dataclass(frozen=True, slots=True)
class Capability:
    """
    What a sensor can currently answer for its chain.

    ``blocked_by`` and ``unlocked_by`` exist so a gap is actionable. Reporting
    that archive reads are unavailable tells an operator nothing they can fix;
    naming the environment variable that would enable one does.
    """

    chain: str
    reachable: bool
    #: Historical state at arbitrary depth.
    archive: bool = False
    #: Log range queries (``eth_getLogs`` and equivalents).
    logs: bool = False
    endpoints: int = 0
    blocked_by: str = ""
    unlocked_by: tuple[str, ...] = ()

    def supports(self, kind: RecordKind) -> bool:
        """Whether this sensor can serve the given record kind right now."""
        if not self.reachable:
            return False
        if kind is RecordKind.LOGS:
            return self.logs
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "reachable": self.reachable,
            "archive": self.archive,
            "logs": self.logs,
            "endpoints": self.endpoints,
            "blocked_by": self.blocked_by,
            "unlocked_by": list(self.unlocked_by),
        }


class Sensor(ABC):
    """
    Base class for every data source A01 reads from.

    A sensor decides *how to obtain* an observation. It never decides what the
    observation means, whether it is interesting, or what should happen next.
    Those are the jobs of normalization, intelligence, and decision
    respectively, and a sensor that takes any of them on makes the whole
    pipeline untestable without a network.
    """

    #: Stable identifier used in registries, logs, and provenance.
    name: str = "sensor"

    @property
    @abstractmethod
    def chain(self) -> str:
        """The chain this sensor answers for."""

    @abstractmethod
    def capability(self) -> Capability:
        """What this sensor can answer right now, and what is blocking it."""

    @abstractmethod
    def head(self) -> SensorResult:
        """The current chain head height."""

    @abstractmethod
    def block(self, height: int, *, include_transactions: bool = False) -> SensorResult:
        """One block by height."""

    def finalized_head(self) -> SensorResult:
        """
        The height the chain reports as finalized.

        Chains without an authoritative finality tag cannot answer this, so
        the default declines rather than substituting a confirmation-depth
        estimate. A depth estimate presented as a finality statement is the
        kind of quiet substitution that turns into a wrong rollback later.
        """
        return SensorResult(
            determined=False,
            chain=self.chain,
            method="finalized_head",
            outcome="capability_unavailable",
            reason=f"{self.name} does not report an authoritative finalized head",
        )

    def logs(
        self,
        from_height: int,
        to_height: int,
        *,
        address: str | None = None,
        topics: list[Any] | None = None,
    ) -> SensorResult:
        """A batch of logs over a height range."""
        return SensorResult(
            determined=False,
            chain=self.chain,
            method="logs",
            outcome="capability_unavailable",
            reason=f"{self.name} does not implement log reads",
        )

    def health(self) -> dict[str, Any]:
        """Operator-facing status. Overridden by sensors with a transport."""
        return {"sensor": self.name, "chain": self.chain, **self.capability().as_dict()}

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r}, chain={self.chain!r})"


def chain_str(chain: ChainName | str) -> str:
    """Normalize a chain argument to its string name."""
    return chain.value if isinstance(chain, ChainName) else str(chain)


__all__ = ["Capability", "RawRecord", "Sensor", "chain_str"]
