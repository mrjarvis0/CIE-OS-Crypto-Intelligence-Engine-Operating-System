"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    fixtures.replay

Purpose:
    Serve recorded chain data as a sensor, so the whole pipeline can be tested
    without a network and with a chain that does exactly what a test needs.

Design goals:
    - Byte-identical replay; a recording is a fact, not a fixture to tweak
    - Same `Sensor` contract, so nothing downstream knows it is replaying
    - Scriptable reorgs, which cannot be arranged on a real chain
    - Faults injectable, so failure paths are reachable
    - No network, no clock dependence, no randomness

Notes:
    Three of A01's most consequential paths — a reorg, a deep fork, a
    finality violation — cannot be produced on demand against mainnet. You
    cannot ask Ethereum to reorganise while a test watches. Until they can be
    replayed they are exercised only by unit tests of the components, and the
    interaction between ingestion, the writer and storage stays unverified in
    precisely the situation where getting it wrong loses or corrupts history.

    So the recording is real and the *sequence* is scripted. Blocks come from
    mainnet, captured once and committed; a replay serves them in whatever
    order the test needs, including serving a different block at a height it
    already served. That is a reorg, and downstream cannot tell it from the
    real thing because nothing about it is simulated except the timing.

    Recordings are immutable. A test that adjusts a captured payload to make an
    assertion pass has stopped testing against a chain and started testing
    against its own expectations — and the adjustment is invisible in the diff
    of a JSON blob. Fixtures are captured by :func:`capture`, committed, and
    thereafter read-only.
"""

from __future__ import annotations

import json
import logging

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from sensors.base import Capability, Sensor
from sensors.envelope import Provenance, RawRecord, RecordKind, SensorResult

logger = logging.getLogger("a01.fixtures")

#: Where captured recordings live. Committed, so a checkout can run the full
#: pipeline offline.
FIXTURE_DIR = Path(__file__).parent / "recordings"


@dataclass(frozen=True, slots=True)
class Recording:
    """
    A captured range of chain data.

    ``provider`` and ``captured_at`` are kept so a surprising fixture can be
    traced to when and where it came from, rather than being argued about.
    """

    chain: str
    blocks: tuple[dict[str, Any], ...]
    provider: str = "unknown"
    captured_at: str = ""
    #: Event logs by height, when the capture included them. Kept separate from
    #: the blocks because a block payload and its logs come from different RPC
    #: calls, and a recording is only honest if it mirrors how the data arrived.
    logs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def logs_at(self, height: int) -> list[dict[str, Any]]:
        return self.logs.get(str(height), [])

    @property
    def has_logs(self) -> bool:
        return bool(self.logs)

    @property
    def heights(self) -> tuple[int, ...]:
        return tuple(int(b["number"], 16) for b in self.blocks)

    @property
    def head(self) -> int:
        return max(self.heights)

    def block_at(self, height: int) -> dict[str, Any] | None:
        for block in self.blocks:
            if int(block["number"], 16) == height:
                return block
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "provider": self.provider,
            "captured_at": self.captured_at,
            "blocks": list(self.blocks),
            "logs": {k: list(v) for k, v in self.logs.items()},
        }

    @classmethod
    def load(cls, path: str | Path) -> Recording:
        """
        Read a recording, gzipped or plain.

        Stored gzipped because a block of real mainnet transactions is around
        half a megabyte and JSON of this shape compresses roughly tenfold. The
        alternative — trimming transactions to keep the file small — would make
        every replayed block incomplete against its own stated count, so the
        fixture would exercise the degraded path and never the normal one.
        """
        target = Path(path)
        if target.suffix == ".gz":
            import gzip

            with gzip.open(target, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
        else:
            payload = json.loads(target.read_text(encoding="utf-8"))

        return cls(
            chain=payload["chain"],
            blocks=tuple(payload["blocks"]),
            provider=payload.get("provider", "unknown"),
            captured_at=payload.get("captured_at", ""),
            logs=payload.get("logs", {}),
        )

    @classmethod
    def named(cls, name: str) -> Recording:
        """Load a committed recording by file stem, preferring the gzipped form."""
        compressed = FIXTURE_DIR / f"{name}.json.gz"
        if compressed.is_file():
            return cls.load(compressed)
        return cls.load(FIXTURE_DIR / f"{name}.json")


def fork(
    recording: Recording, *, at: int, tag: str = "b"
) -> tuple[dict[str, Any], ...]:
    """
    Build an alternative branch from ``at`` upward.

    Derived from the recording rather than written by hand: the blocks keep
    their real transactions, gas figures and timestamps, and only the identity
    linkage changes. A hand-written fork tests the reorg logic against a shape
    the chain does not produce, which is how a detector passes its tests and
    fails on mainnet.
    """
    branch: list[dict[str, Any]] = []
    previous: str | None = None

    for block in recording.blocks:
        height = int(block["number"], 16)
        if height < at:
            continue
        forked = dict(block)
        forked["hash"] = f"0x{tag}{height:062x}"
        if previous is not None:
            forked["parentHash"] = previous
        previous = forked["hash"]
        branch.append(forked)

    return tuple(branch)


@dataclass
class ReplaySensor(Sensor):
    """
    A sensor backed by a recording rather than a network.

    Implements the same contract as the live EVM sensor, so ingestion, the
    writer and storage behave exactly as they do in production. What differs is
    that the test decides what the chain does.
    """

    recording: Recording
    name: str = "replay"

    #: Heights whose block should be served from an alternative branch. Set by
    #: :meth:`reorg_to` to make the chain fork under a running poller.
    _override: dict[int, dict[str, Any]] = field(default_factory=dict, repr=False)
    #: Heights that should fail, so the undetermined path is reachable.
    _faults: set[int] = field(default_factory=set, repr=False)
    #: Head reported to callers. Lets a test hold the head still while blocks
    #: below it change, which is what a reorg looks like from a poller.
    _head: int | None = None

    # -- Sensor contract --------------------------------------------------

    @property
    def chain(self) -> str:
        return self.recording.chain

    def capability(self) -> Capability:
        return Capability(
            chain=self.chain,
            reachable=True,
            archive=True,
            logs=self.recording.has_logs,
            endpoints=1,
        )

    def head(self) -> SensorResult:
        height = self._head if self._head is not None else self.recording.head
        return SensorResult(
            determined=True,
            chain=self.chain,
            method="head",
            record=RawRecord(
                chain=self.chain,
                kind=RecordKind.HEAD,
                payload={"height": height},
                height=height,
                provenance=self._provenance("head"),
            ),
        )

    def block(self, height: int, *, include_transactions: bool = False) -> SensorResult:
        if height in self._faults:
            # A real provider failure, not an empty answer. Ingestion must not
            # read the two as the same thing, and this is where that is tested.
            return SensorResult(
                determined=False,
                chain=self.chain,
                method="block",
                outcome="all_endpoints_failed",
                reason=f"injected fault at height {height}",
            )

        payload = self._override.get(height) or self.recording.block_at(height)
        if payload is None:
            return SensorResult(
                determined=False,
                chain=self.chain,
                method="block",
                outcome="no_endpoint",
                reason=f"height {height} is not in the recording",
            )

        if not include_transactions:
            payload = dict(payload)
            payload["transactions"] = [
                tx["hash"] if isinstance(tx, dict) else tx
                for tx in payload.get("transactions", [])
            ]

        return SensorResult(
            determined=True,
            chain=self.chain,
            method="block",
            record=RawRecord(
                chain=self.chain,
                kind=RecordKind.BLOCK,
                payload=payload,
                height=height,
                provenance=self._provenance("eth_getBlockByNumber"),
            ),
        )

    def logs(
        self,
        *,
        from_height: int,
        to_height: int,
        address: str | None = None,
        topics: Any = None,
    ) -> SensorResult:
        """
        Recorded logs for a height range.

        Declines when the recording has none, rather than returning an empty
        list. An empty result would read as "this range emitted no events",
        which is a claim about the chain; the truth is that the capture did not
        include them.
        """
        if not self.recording.has_logs:
            return SensorResult(
                determined=False,
                chain=self.chain,
                method="logs",
                outcome="capability_unavailable",
                reason="this recording was captured without logs",
            )

        collected: list[dict[str, Any]] = []
        for height in range(from_height, to_height + 1):
            collected.extend(self.recording.logs_at(height))

        return SensorResult(
            determined=True,
            chain=self.chain,
            method="logs",
            record=RawRecord(
                chain=self.chain,
                kind=RecordKind.LOGS,
                payload=collected,
                height=from_height,
                provenance=self._provenance("eth_getLogs"),
            ),
        )

    # -- scripting --------------------------------------------------------

    def reorg_to(self, branch: Iterable[dict[str, Any]]) -> None:
        """
        Switch the chain onto an alternative branch.

        After this, a height already served returns a different block — which
        is what a reorg is. Nothing downstream is told; it has to notice
        through parent linkage, which is the property under test.
        """
        for block in branch:
            self._override[int(block["number"], 16)] = block

    def fail_at(self, *heights: int) -> None:
        """Make these heights return an undetermined result."""
        self._faults.update(heights)

    def recover(self) -> None:
        self._faults.clear()

    def set_head(self, height: int) -> None:
        """Hold the reported head, so a test controls how far a poller runs."""
        self._head = height

    def _provenance(self, method: str) -> Provenance:
        return Provenance(
            provider=f"replay:{self.recording.provider}",
            chain=self.chain,
            method=method,
            outcome="ok",
        )


def capture(
    sensor: Sensor,
    *,
    start: int,
    count: int,
    name: str,
    provider: str = "live",
    with_logs: bool = False,
) -> Path:
    """
    Record a live range to a committed fixture.

    Run by hand when a new fixture is needed, never by a test. A test that
    captured its own input would pass against whatever the chain happened to be
    doing, which is not a regression test.
    """
    from datetime import UTC, datetime

    blocks: list[dict[str, Any]] = []
    logs: dict[str, list[dict[str, Any]]] = {}

    for height in range(start, start + count):
        result = sensor.block(height, include_transactions=True)
        if not result.ok:
            raise RuntimeError(f"capture failed at {height}: {result.reason}")
        blocks.append(result.unwrap().payload)

        if with_logs:
            # One height per call. Free endpoints reject wide ranges, and a
            # partial multi-block response would silently record fewer events
            # than the chain emitted.
            found = sensor.logs(from_height=height, to_height=height)
            if not found.ok:
                raise RuntimeError(f"log capture failed at {height}: {found.reason}")
            logs[str(height)] = list(found.unwrap().payload)

    recording = Recording(
        chain=sensor.chain,
        blocks=tuple(blocks),
        provider=provider,
        captured_at=datetime.now(UTC).isoformat(),
        logs=logs,
    )

    import gzip

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / f"{name}.json.gz"
    # mtime=0 so a recapture of identical data produces an identical file, and
    # a fixture diff means the chain data changed rather than the clock.
    with gzip.GzipFile(path, "wb", mtime=0) as handle:
        handle.write(json.dumps(recording.as_dict()).encode("utf-8"))

    logger.info(
        "captured %d block(s) to %s (%.1f KiB)",
        len(blocks),
        path,
        path.stat().st_size / 1024,
    )
    return path


__all__ = ["FIXTURE_DIR", "Recording", "ReplaySensor", "capture", "fork"]
