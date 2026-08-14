"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    sensors.registry

Purpose:
    Resolve a chain name to the sensor that can read it, and report which
    chains are actually readable right now.

Design goals:
    - One sensor instance per chain, reused across calls
    - Transport shared, so provider health and rate budget are global
    - Unsupported chains fail at lookup, not mid-read
    - Construction never performs network I/O

Notes:
    The dispatcher is shared across every sensor on purpose. Rate limits and
    circuit-breaker state are per provider, not per chain, and several chains
    are commonly served by one provider. Giving each sensor its own transport
    would let three chains each spend the full budget of the same endpoint and
    discover the throttle independently, three times over.

    Sensors are built lazily. Constructing all nine at import time would make a
    registry lookup for Ethereum depend on Bitcoin's configuration being valid,
    which is the kind of coupling that turns one bad entry into a dead agent.
"""

from __future__ import annotations

import logging

from typing import Any

from blockchain.rpc.clients.dispatch import ChainDispatcher
from config.rpc.chains import ChainName, ChainType, get_chain, supported_chain_names
from core.exceptions import SensorError

from .base import Sensor, chain_str
from .evm.rpc_sensor import EvmRpcSensor

logger = logging.getLogger(__name__)


class SensorRegistry:
    """
    The set of sensors A01 can read chains through.

    Lookup is by chain name. A chain in the registry but without a sensor
    implementation is reported as unsupported rather than approximated with
    the nearest available one -- an EVM sensor pointed at Solana would fail
    every call in a way that looks like an outage.
    """

    def __init__(self, *, dispatcher: ChainDispatcher | None = None) -> None:
        self._dispatcher = dispatcher if dispatcher is not None else ChainDispatcher()
        self._sensors: dict[str, Sensor] = {}

    @property
    def dispatcher(self) -> ChainDispatcher:
        return self._dispatcher

    # -- lookup ----------------------------------------------------------

    def supports(self, chain: ChainName | str) -> bool:
        """Whether a sensor implementation exists for this chain."""
        try:
            return get_chain(chain_str(chain)).chain_type is ChainType.EVM
        except (KeyError, ValueError):
            return False

    def get(self, chain: ChainName | str) -> Sensor:
        """
        The sensor for a chain, constructing it on first use.

        Raises :class:`core.exceptions.SensorError` for a chain A01 cannot
        read. Returning None instead would push the check to every caller,
        and the check would eventually be skipped somewhere.
        """
        name = chain_str(chain)
        existing = self._sensors.get(name)
        if existing is not None:
            return existing

        if not self.supports(name):
            raise SensorError(
                f"no sensor implementation for chain {name!r}",
                sensor="registry",
                chain=name,
            )

        sensor = EvmRpcSensor(name, dispatcher=self._dispatcher)
        self._sensors[name] = sensor
        logger.debug("constructed sensor %s", sensor.name)
        return sensor

    def register(self, sensor: Sensor) -> None:
        """
        Install a sensor explicitly, replacing any built for that chain.

        The seam for non-EVM chains and for tests that drive a scripted
        transport without reaching the network.
        """
        self._sensors[sensor.chain] = sensor

    # -- reporting -------------------------------------------------------

    def implemented_chains(self) -> tuple[str, ...]:
        """Chains with a sensor implementation, readable or not."""
        return tuple(
            name.value for name in supported_chain_names() if self.supports(name)
        )

    def readable_chains(self) -> tuple[str, ...]:
        """
        Chains that have both an implementation and a reachable endpoint.

        Distinct from :meth:`implemented_chains`: an implemented chain with no
        configured endpoint is a configuration gap, not a missing feature, and
        conflating the two sends an operator to the wrong fix.
        """
        readable: list[str] = []
        for name in self.implemented_chains():
            try:
                if self.get(name).capability().reachable:
                    readable.append(name)
            except SensorError:  # pragma: no cover - filtered by implemented_chains
                continue
        return tuple(readable)

    def health(self) -> dict[str, Any]:
        """Operator-facing summary, for doctor."""
        implemented = self.implemented_chains()
        return {
            "implemented": list(implemented),
            "readable": list(self.readable_chains()),
            "constructed": sorted(self._sensors),
            "transport": self._dispatcher.health(),
        }

    def __len__(self) -> int:
        return len(self._sensors)

    def __repr__(self) -> str:
        return f"SensorRegistry(constructed={len(self._sensors)})"


def default_registry() -> SensorRegistry:
    """A registry over the default provider catalog."""
    return SensorRegistry()


__all__ = ["SensorRegistry", "default_registry"]
