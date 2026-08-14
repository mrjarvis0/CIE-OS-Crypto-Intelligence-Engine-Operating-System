"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for sensors -- capture, provenance, and the determined/undetermined
distinction.

No test here touches the network. Every read is served by a scripted
dispatcher, because a sensor suite that depends on a live endpoint tests the
endpoint's uptime rather than the sensor, and fails for reasons unrelated to
the code under change.
"""

from __future__ import annotations

import pytest

from blockchain.rpc.clients.dispatch import CallResult, Outcome
from core.exceptions import SensorError
from sensors import (
    Capability,
    EvmRpcSensor,
    Provenance,
    RawRecord,
    RecordKind,
    Sensor,
    SensorRegistry,
    content_id,
    parse_quantity,
    to_quantity,
)


#: Scripts an explicit JSON null answer. A plain ``None`` in the response map
#: cannot mean this: it is indistinguishable from "this method was not
#: scripted", and the two produce opposite results -- a determined empty answer
#: versus a transport failure.
NULL = object()


class ScriptedDispatcher:
    """
    A ChainDispatcher stand-in that answers from a script.

    Records every call so a test can assert not only what came back but what
    was asked -- the log-range clamp and the archive flag are only observable
    in the request.
    """

    def __init__(self, responses: dict[str, object] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, str, object]] = []
        self.report = {
            "chain": "ethereum",
            "endpoints": 3,
            "archive": False,
            "logs": True,
            "reachable": True,
        }

    def capability_report(self, chain: str) -> dict[str, object]:
        return dict(self.report, chain=chain)

    def call(self, chain, method, params=None, **kwargs):  # noqa: ANN001
        self.calls.append((str(chain), method, params))

        if method not in self.responses:
            return CallResult(
                outcome=Outcome.ALL_ENDPOINTS_FAILED,
                chain=str(chain),
                method=method,
                reason="no scripted response",
            )

        scripted = self.responses[method]
        if isinstance(scripted, CallResult):
            return scripted
        return CallResult(
            outcome=Outcome.OK,
            value=None if scripted is NULL else scripted,
            provider="scripted",
            chain=str(chain),
            method=method,
            attempts=1,
        )

    def health(self) -> dict[str, object]:
        return {"scripted": True}


def evm_block(number: int, tag: str = "a", parent_tag: str | None = None) -> dict:
    """A minimal EVM block payload with readable linkage."""
    parent = parent_tag if parent_tag is not None else tag
    return {
        "number": hex(number),
        "hash": f"0x{tag}{number:06d}",
        "parentHash": f"0x{parent}{number - 1:06d}" if number else "0x0",
        "timestamp": hex(1_700_000_000 + number * 12),
    }


def sensor_with(responses: dict[str, object]) -> EvmRpcSensor:
    return EvmRpcSensor("ethereum", dispatcher=ScriptedDispatcher(responses))


# ==============================================================================
# QUANTITY PARSING
# ==============================================================================

def test_parse_quantity_reads_hex_and_decimal():
    assert parse_quantity("0x64") == 100
    assert parse_quantity("100") == 100
    assert parse_quantity(100) == 100


def test_parse_quantity_refuses_rather_than_defaulting():
    """
    A malformed height is not height zero. Defaulting would hand the pipeline
    a fact the chain never stated.
    """
    for bad in ["", "0xzz", "not a number", None, {}, [], True]:
        assert parse_quantity(bad) is None, bad


def test_to_quantity_rejects_negative_heights():
    with pytest.raises(ValueError):
        to_quantity(-1)


# ==============================================================================
# ENVELOPE
# ==============================================================================

def test_content_id_is_stable_across_key_order():
    """The same observation must dedupe however the provider ordered its keys."""
    first = content_id("ethereum", RecordKind.BLOCK, {"a": 1, "b": 2})
    second = content_id("ethereum", RecordKind.BLOCK, {"b": 2, "a": 1})
    assert first == second


def test_content_id_separates_chains_and_kinds():
    payload = {"number": "0x1"}
    assert content_id("ethereum", RecordKind.BLOCK, payload) != content_id(
        "polygon", RecordKind.BLOCK, payload
    )
    assert content_id("ethereum", RecordKind.BLOCK, payload) != content_id(
        "ethereum", RecordKind.HEAD, payload
    )


def test_record_id_excludes_provider_and_time():
    """
    Two providers serving the same block must produce one record, or every
    corroborating read would double-count as a new observation.
    """
    payload = evm_block(100)
    first = RawRecord(
        chain="ethereum",
        kind=RecordKind.BLOCK,
        payload=payload,
        height=100,
        provenance=Provenance("alpha", "ethereum", "eth_getBlockByNumber", "ok"),
    )
    second = RawRecord(
        chain="ethereum",
        kind=RecordKind.BLOCK,
        payload=payload,
        height=100,
        provenance=Provenance("beta", "ethereum", "eth_getBlockByNumber", "ok"),
    )
    assert first.record_id == second.record_id


def test_provenance_never_carries_the_endpoint_url():
    """A keyed URL holds a credential, and these records reach disk and reports."""
    provenance = Provenance("alpha", "ethereum", "eth_blockNumber", "ok")
    assert "url" not in provenance.as_dict()
    assert "endpoint" not in provenance.as_dict()


def test_record_rejects_negative_height():
    with pytest.raises(ValueError):
        RawRecord(
            chain="ethereum",
            kind=RecordKind.BLOCK,
            payload={},
            height=-1,
            provenance=Provenance("a", "ethereum", "m", "ok"),
        )


# ==============================================================================
# CONSTRUCTION
# ==============================================================================

def test_unregistered_chain_fails_at_construction():
    """A typo should surface at wiring time, not halfway through a backfill."""
    with pytest.raises(SensorError):
        EvmRpcSensor("ethereumm", dispatcher=ScriptedDispatcher())


def test_non_evm_chain_is_refused():
    """
    Solana speaks a different RPC. An EVM sensor pointed at it would fail every
    call in a way that reads as an outage rather than as a wiring mistake.
    """
    with pytest.raises(SensorError) as excinfo:
        EvmRpcSensor("solana", dispatcher=ScriptedDispatcher())
    assert "not EVM" in str(excinfo.value)


def test_confirmations_come_from_the_chain_registry():
    """Polygon's reorg depth is not Ethereum's, and neither is a constant here."""
    ethereum = EvmRpcSensor("ethereum", dispatcher=ScriptedDispatcher())
    polygon = EvmRpcSensor("polygon", dispatcher=ScriptedDispatcher())
    assert polygon.confirmations != ethereum.confirmations


# ==============================================================================
# HEAD
# ==============================================================================

def test_head_returns_height_with_provenance():
    sensor = sensor_with({"eth_blockNumber": "0x64"})
    result = sensor.head()

    assert result.ok
    record = result.unwrap()
    assert record.height == 100
    assert record.kind is RecordKind.HEAD
    assert record.provenance.provider == "scripted"


def test_head_failure_is_undetermined_not_zero():
    """
    The distinction this whole layer exists to preserve: a transport failure
    must not read as "the chain is at height 0".
    """
    sensor = sensor_with({})
    result = sensor.head()

    assert not result.determined
    assert result.record is None
    with pytest.raises(LookupError):
        result.unwrap()


def test_malformed_head_is_undetermined():
    sensor = sensor_with({"eth_blockNumber": "not-a-quantity"})
    result = sensor.head()

    assert not result.determined
    assert result.outcome == "malformed_response"


# ==============================================================================
# BLOCKS
# ==============================================================================

def test_block_returns_payload_unreshaped():
    """Sensors capture; normalization renames. parentHash stays parentHash."""
    sensor = sensor_with({"eth_getBlockByNumber": evm_block(100)})
    record = sensor.block(100).unwrap()

    assert "parentHash" in record.payload
    assert "parent_hash" not in record.payload
    assert record.height == 100


def test_absent_block_is_determined_with_no_record():
    """
    A null block is an answer: the height is not produced yet. That is not a
    failure, and conflating the two would make the poller retry forever or
    give up wrongly.
    """
    sensor = sensor_with({"eth_getBlockByNumber": NULL})
    result = sensor.block(100)

    assert result.determined
    assert result.record is None


def test_provider_returning_the_wrong_height_is_refused():
    """
    Asking for 100 and being handed 99 means the endpoint is behind or ignoring
    the parameter. Filing it under 100 would corrupt the stream.
    """
    sensor = sensor_with({"eth_getBlockByNumber": evm_block(99)})
    result = sensor.block(100)

    assert not result.determined
    assert result.outcome == "malformed_response"
    assert "returned 99" in result.reason


def test_negative_height_is_a_programming_error():
    sensor = sensor_with({})
    with pytest.raises(SensorError):
        sensor.block(-1)


# ==============================================================================
# FINALITY
# ==============================================================================

def test_finalized_head_reads_the_chains_tag():
    sensor = sensor_with({"eth_getBlockByNumber": evm_block(90)})
    result = sensor.finalized_head()

    assert result.ok
    assert result.unwrap().height == 90


class MinimalSensor(Sensor):
    """
    A sensor implementing only the two required reads.

    Stands in for the non-EVM sensors not yet written -- Bitcoin is the one
    registered chain with no authoritative finality tag -- so the base class's
    declining defaults are exercised rather than assumed.
    """

    name = "minimal"

    @property
    def chain(self) -> str:
        return "bitcoin"

    def capability(self) -> Capability:
        return Capability(chain="bitcoin", reachable=True)

    def head(self):
        raise NotImplementedError

    def block(self, height: int, *, include_transactions: bool = False):
        raise NotImplementedError


def test_finalized_head_declines_when_the_chain_has_no_tag():
    """
    A confirmation-depth estimate presented as a finality statement is the
    quiet substitution that turns into a wrong rollback later, so a sensor
    that cannot read finality declines instead of estimating it.
    """
    result = MinimalSensor().finalized_head()

    assert not result.determined
    assert result.outcome == "capability_unavailable"


def test_log_reads_decline_by_default():
    """An unimplemented capability reports itself rather than raising."""
    result = MinimalSensor().logs(0, 10)

    assert not result.determined
    assert result.outcome == "capability_unavailable"


# ==============================================================================
# LOGS
# ==============================================================================

def test_log_range_wider_than_the_limit_is_refused_not_trimmed():
    """
    Trimming would return a correct-looking answer for a narrower window than
    was asked about, and the caller would record it as covering the whole range.
    """
    sensor = sensor_with({"eth_getLogs": []})
    result = sensor.logs(0, sensor.log_range + 10)

    assert not result.determined
    assert result.outcome == "range_too_wide"


def test_logs_request_asks_for_log_capability():
    dispatcher = ScriptedDispatcher({"eth_getLogs": [{"address": "0xabc"}]})
    sensor = EvmRpcSensor("ethereum", dispatcher=dispatcher)
    result = sensor.logs(10, 20)

    assert result.ok
    assert result.unwrap().kind is RecordKind.LOGS
    chain, method, params = dispatcher.calls[-1]
    assert method == "eth_getLogs"
    assert params[0]["fromBlock"] == "0xa"
    assert params[0]["toBlock"] == "0x14"


def test_inverted_log_range_is_a_programming_error():
    sensor = sensor_with({})
    with pytest.raises(SensorError):
        sensor.logs(20, 10)


# ==============================================================================
# CAPABILITY
# ==============================================================================

def test_capability_names_what_would_unlock_archive():
    """Reporting a gap without naming the fix sends an operator nowhere."""
    dispatcher = ScriptedDispatcher()
    dispatcher.report["archive_blocked_by"] = "no archive endpoint available"
    dispatcher.report["archive_unlocked_by"] = ["ALCHEMY_API_KEY"]

    capability = EvmRpcSensor("ethereum", dispatcher=dispatcher).capability()

    assert not capability.archive
    assert capability.unlocked_by == ("ALCHEMY_API_KEY",)


def test_capability_supports_gates_log_reads():
    reachable = Capability(chain="ethereum", reachable=True, logs=False)
    assert reachable.supports(RecordKind.BLOCK)
    assert not reachable.supports(RecordKind.LOGS)

    unreachable = Capability(chain="ethereum", reachable=False, logs=True)
    assert not unreachable.supports(RecordKind.BLOCK)


# ==============================================================================
# REGISTRY
# ==============================================================================

def test_registry_builds_evm_sensors_lazily_and_reuses_them():
    registry = SensorRegistry(dispatcher=ScriptedDispatcher())
    assert len(registry) == 0

    first = registry.get("ethereum")
    second = registry.get("ethereum")

    assert first is second
    assert len(registry) == 1


def test_registry_refuses_chains_without_an_implementation():
    """Approximating Solana with an EVM sensor would fail as a fake outage."""
    registry = SensorRegistry(dispatcher=ScriptedDispatcher())
    with pytest.raises(SensorError):
        registry.get("solana")


def test_registry_reports_every_evm_chain_as_implemented():
    registry = SensorRegistry(dispatcher=ScriptedDispatcher())
    implemented = registry.implemented_chains()

    assert "ethereum" in implemented
    assert "solana" not in implemented
    assert "bitcoin" not in implemented


def test_registered_sensor_overrides_the_built_one():
    """The seam non-EVM chains and scripted tests both need."""
    registry = SensorRegistry(dispatcher=ScriptedDispatcher())
    custom = sensor_with({"eth_blockNumber": "0x1"})
    registry.register(custom)

    assert registry.get("ethereum") is custom
