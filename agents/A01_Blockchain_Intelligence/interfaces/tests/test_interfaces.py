"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the interfaces layer -- the facade, and the HTTP surface over it.

The property worth protecting here is that surfaces cannot disagree. Most of
these tests exercise the service directly, because that is where an answer is
produced; the HTTP tests check only that the transport preserves it, refuses
what it should, and never leaks a traceback.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http import HTTPStatus

import pytest

from database import Database, RecordWriter, SqliteBlockRepository
from decision import Subscription
from interfaces import IntelligenceService, ServiceResult, build_server
from interfaces.rest import MAX_QUERY_LENGTH, Router
from sensors.envelope import Provenance, RawRecord, RecordKind

TIMESTAMP = 1_700_000_000
ALICE = "0x" + "a1" * 20
BOB = "0x" + "b2" * 20


def block_record(number: int) -> RawRecord:
    return RawRecord(
        chain="ethereum",
        kind=RecordKind.BLOCK,
        height=number,
        provenance=Provenance("fixture", "ethereum", "eth_getBlockByNumber", "ok"),
        payload={
            "number": hex(number),
            "hash": f"0xa{number:06d}",
            "parentHash": f"0xa{number - 1:06d}",
            "timestamp": hex(TIMESTAMP + number * 12),
            "transactions": [
                {
                    "hash": f"0xtx{number:05d}",
                    "from": ALICE,
                    "to": BOB,
                    "value": hex(10**24),
                    "transactionIndex": "0x0",
                    "input": "0x",
                }
            ],
        },
    )


@pytest.fixture
def db_path(tmp_path):
    """A small on-disk database, since the service opens by path."""
    path = tmp_path / "a01.db"
    with Database(path) as database:
        writer = RecordWriter(SqliteBlockRepository(database))
        for number in (100, 101, 102):
            writer.write(block_record(number))
    return path


@pytest.fixture
def service(db_path):
    return IntelligenceService(database_path=db_path)


@pytest.fixture
def client(service):
    """A live server on an ephemeral port, torn down after the test."""
    server = build_server(service, port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def get(path: str):
        """Returns (status, body, headers). Closes the response either way."""
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as response:
                return response.status, json.loads(response.read()), dict(response.headers)
        except urllib.error.HTTPError as exc:
            with exc:  # HTTPError is a response; leaving it open warns
                return exc.code, json.loads(exc.read()), dict(exc.headers)

    try:
        yield get
    finally:
        server.shutdown()
        server.server_close()


# ==============================================================================
# SERVICE
# ==============================================================================

def test_the_service_runs_the_whole_path(service):
    result = service.investigate(address=ALICE)

    assert result.ok
    assert "package" in result.data
    assert "decision" in result.data
    assert "composition" in result.data


def test_investigating_without_a_subject_is_a_usage_error():
    result = IntelligenceService().investigate()

    assert not result.ok
    assert result.status == 400


def test_a_malformed_address_is_rejected_not_reported_as_unknown(service):
    """
    Every skill returning 'not found' for a typo reads as an address with no
    history, which is a different and wrong answer.
    """
    result = service.investigate(address="0x123")

    assert not result.ok
    assert result.status == 400
    assert "address rejected" in result.error


def test_coverage_is_answerable_without_running_an_investigation(service):
    result = service.coverage()

    assert result.ok
    assert result.data["blocks"] == 3
    assert result.data["supports_absence"] is False


def test_coverage_without_storage_reports_unavailable():
    result = IntelligenceService().coverage()

    assert not result.ok
    assert result.status == 503


def test_the_detector_listing_comes_from_the_gate(service):
    """
    The listing reports the gate's own answer, including the refusals.

    It used to assert every listed detector could alert, which held only
    while every detector was validated. What the listing has to get right is
    the *correspondence*: a detector appears as alerting exactly when the gate
    says it may, and a muted one carries the reason it is muted -- otherwise
    the API shows a detector that looks live and is not.
    """
    from decision.maturity import MaturityGate

    result = service.detectors()
    gate = MaturityGate()

    assert result.ok

    assert set(result.data["alerting"]) == {
        entry.detector for entry in gate.alerting_detectors()
    }

    for row in result.data["detectors"]:
        standing = gate.for_detector(row["detector"])
        assert row["may_alert"] is standing.may_alert
        if not row["may_alert"]:
            assert row["blocked_by"], f"{row['detector']} is muted without a reason"


def test_health_reports_storage_and_decision_state(service):
    result = service.health()

    assert result.ok
    assert result.data["read_only"] is True
    assert result.data["storage"]["available"] is True
    assert result.data["storage"]["rows"]["blocks"] == 3


def test_the_service_works_without_storage_when_given_a_subject():
    result = IntelligenceService().investigate(
        address=ALICE, subject={"large_transfers": []}
    )

    assert result.ok
    assert "composition" not in result.data


def test_overrides_are_applied_after_composition(service):
    """An operator's figure must not be overwritten by a stored one."""
    result = service.investigate(
        address=ALICE, subject={"circulating_supply": 12345.0}
    )

    assert result.ok
    assert result.data["package"]["subject"]["circulating_supply"] == 12345.0


def test_alert_budget_state_survives_across_calls(db_path):
    """
    Held on the service rather than rebuilt per request; a budget that resets
    every call is not a budget.
    """
    service = IntelligenceService(
        database_path=db_path, subscriptions=[Subscription("desk")]
    )
    first = service.decisions
    service.investigate(address=ALICE)

    assert service.decisions is first


def test_a_failure_result_renders_as_an_error_body():
    result = ServiceResult.failure("nope", status=404)

    assert result.as_dict() == {"error": "nope"}


# ==============================================================================
# ROUTER
# ==============================================================================

def test_every_route_is_reachable(service):
    router = Router(service)

    for path in router.paths():
        assert router.dispatch(path, {}).status in {200, 400, 503}


def test_the_chain_catalogue_is_answerable_without_storage():
    """
    What A01 can read is not a property of what it has read, so this route
    answers with no database configured. It is also the route most likely to be
    hit first, before anything has been ingested at all.
    """
    result = IntelligenceService().chains()

    assert result.ok
    names = {entry["chain"] for entry in result.data["chains"]}
    assert {"ethereum", "linea", "scroll", "gnosis", "celo", "mantle", "unichain"} <= names
    assert result.data["measured_on"]


def test_the_chain_catalogue_makes_no_network_call(monkeypatch):
    """
    Fifteen chains behind one request would turn a status page into a load
    generator, so this route reads the measured table and never probes.
    """
    import knowledge.chains as knowledge_chains

    def explode(_chain):  # pragma: no cover - the point is that it is not called
        raise AssertionError("chains() probed the network")

    monkeypatch.setattr(knowledge_chains, "probe", explode)
    assert IntelligenceService().chains().ok


def test_every_chain_in_the_catalogue_states_a_limit():
    """A capability entry with no limits reads as a claim of completeness."""
    for entry in IntelligenceService().chains().data["chains"]:
        assert entry["limits"], entry["chain"]


def test_labels_without_storage_reports_unavailable():
    result = IntelligenceService().labels()

    assert not result.ok
    assert result.status == 503


def test_labels_report_their_source(service, db_path):
    """
    A count with no provenance is the shape of claim this system refuses. The
    route reports per source so a reader can see which list an attribution
    would have come from.
    """
    from tiers.ledger import EVM_SCOPE, Label, LabelRepository

    with Database(db_path) as database:
        LabelRepository(database).save(
            Label(
                chain=EVM_SCOPE,
                address=BOB,
                label="Binance 2",
                entity="Binance",
                category="exchange",
                source="test:fixture-list",
                confidence=0.5,
            )
        )

    result = service.labels()

    assert result.ok
    assert result.data["total"] == 1
    assert result.data["sources"][0]["source"] == "test:fixture-list"
    assert "external assertion" in result.data["note"]


def test_flows_without_labels_is_a_success_carrying_its_reason(service):
    """
    "No labels are loaded" is an answer about A01, not a server fault. Returning
    it as an error would make an unanswerable question look like an outage.
    """
    result = service.flows(chain="ethereum")

    assert result.ok
    assert result.data["determined"] is False
    assert "no exchange address labels loaded" in result.data["reason"]


def test_flows_attribute_transfers_once_labels_exist(service, db_path):
    from tiers.ledger import EVM_SCOPE, Label, LabelRepository

    with Database(db_path) as database:
        LabelRepository(database).save(
            Label(
                chain=EVM_SCOPE,
                address=BOB,
                label="Binance 2",
                entity="Binance",
                category="exchange",
                source="test:fixture-list",
                confidence=0.5,
            )
        )

    result = service.flows(chain="ethereum")

    assert result.ok
    assert result.data["determined"] is True
    assert result.data["flow"]["attributed"] == 3
    assert result.data["flow"]["label_confidence"] == 0.5


def test_an_unknown_route_names_the_available_ones(service):
    result = Router(service).dispatch("/nope", {})

    assert result.status == HTTPStatus.NOT_FOUND
    assert "/health" in result.error


def test_a_handler_raising_becomes_a_500_not_a_traceback(service, monkeypatch):
    """A traceback reaching a client is an information disclosure and useless."""
    def explode():
        raise RuntimeError("internal detail that must not escape")

    monkeypatch.setattr(service, "health", explode)
    result = Router(service).dispatch("/health", {})

    assert result.status == HTTPStatus.INTERNAL_SERVER_ERROR
    assert "internal detail" not in result.error


# ==============================================================================
# HTTP
# ==============================================================================

def test_health_is_served(client):
    status, body, _ = client("/health")

    assert status == 200
    assert body["read_only"] is True


def test_investigate_is_served(client):
    status, body, _ = client(f"/investigate?address={ALICE}")

    assert status == 200
    assert body["decision"]["conclusions"]


def test_chains_are_served(client):
    status, body, _ = client("/chains")

    assert status == 200
    assert body["total"] == 15


def test_flows_are_served(client):
    status, body, _ = client("/flows?chain=ethereum")

    assert status == 200
    assert body["chain"] == "ethereum"


def test_coverage_is_served(client):
    status, body, _ = client("/coverage?chain=ethereum")

    assert status == 200
    assert body["blocks"] == 3


def test_an_unknown_path_is_404(client):
    status, body, _ = client("/nope")

    assert status == 404
    assert "error" in body


def test_writes_are_refused_with_405(service):
    """
    A01 is read-only by architecture. 405 rather than 404 says the resource
    exists and mutation is not offered, which is the accurate statement.
    """
    server = build_server(service, port=0)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/investigate", data=b"{}", method="POST"
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(request)

        with excinfo.value as response:
            assert response.code == HTTPStatus.METHOD_NOT_ALLOWED
            assert "read-only" in json.loads(response.read())["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_an_overlong_query_is_refused(client):
    status, _, _ = client("/investigate?address=" + "a" * (MAX_QUERY_LENGTH + 1))

    assert status == HTTPStatus.REQUEST_URI_TOO_LONG


def test_the_server_binds_loopback_by_default(service):
    """An unauthenticated service on 0.0.0.0 publishes everything ingested."""
    server = build_server(service, port=0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


def test_a_public_bind_is_permitted_but_warned(service, caplog):
    """The operator can still do it, and cannot do it without being told."""
    import logging

    with caplog.at_level(logging.WARNING, logger="interfaces.rest"):
        server = build_server(service, host="0.0.0.0", port=0)  # noqa: S104
        server.server_close()

    assert any("unauthenticated" in record.message for record in caplog.records)


def test_responses_are_not_cached(client):
    """A coverage answer minutes stale is misleading in the way A01 avoids."""
    _, _, headers = client("/coverage")

    assert headers["Cache-Control"] == "no-store"


def test_content_type_sniffing_is_disabled(client):
    _, _, headers = client("/health")

    assert headers["X-Content-Type-Options"] == "nosniff"


def test_the_python_version_is_not_advertised(client):
    """The server banner tells a scanner what to try."""
    _, _, headers = client("/health")

    assert "Python" not in headers.get("Server", "")
