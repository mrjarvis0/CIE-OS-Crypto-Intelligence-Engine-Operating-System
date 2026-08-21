"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the command-line entry point.

These assert the operator-facing contract: exit codes, output formats, and
in particular that the renderer never asserts a low-confidence inference as
a fact.
"""

from __future__ import annotations

import json

import pytest

from cli.main import EXIT_OK, EXIT_USAGE, build_parser, load_subject, main
from cli.render import qualify, render_text

POPULATION = [1, 5, 12, 40, 110, 480, 1200, 5400, 21000]


@pytest.fixture
def subject_file(tmp_path):
    path = tmp_path / "subject.json"
    path.write_text(
        json.dumps(
            {
                "address": "0xabc",
                "transfer_population": POPULATION,
                "large_transfers": [
                    {
                        "value": 999_999,
                        "direction": "out",
                        "counterparty_type": "exchange",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


# =============================================================================
# Argument handling
# =============================================================================


class TestSubjectLoading:
    def test_address_flag_builds_subject(self) -> None:
        args = build_parser().parse_args(["investigate", "--address", "0xabc"])
        assert load_subject(args)["address"] == "0xabc"

    def test_subject_file_loaded(self, subject_file) -> None:
        args = build_parser().parse_args(
            ["investigate", "--subject", str(subject_file)]
        )
        subject = load_subject(args)
        assert subject["address"] == "0xabc"
        assert subject["transfer_population"] == POPULATION

    def test_address_flag_overrides_file(self, subject_file) -> None:
        args = build_parser().parse_args(
            ["investigate", "--subject", str(subject_file), "--address", "0xdef"]
        )
        assert load_subject(args)["address"] == "0xdef"

    def test_missing_address_rejected(self) -> None:
        args = build_parser().parse_args(["investigate"])
        with pytest.raises(ValueError, match="no subject address"):
            load_subject(args)

    def test_missing_file_rejected(self) -> None:
        args = build_parser().parse_args(["investigate", "--subject", "nope.json"])
        with pytest.raises(FileNotFoundError):
            load_subject(args)

    def test_malformed_json_rejected(self, tmp_path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        args = build_parser().parse_args(["investigate", "--subject", str(bad)])
        with pytest.raises(ValueError, match="not valid JSON"):
            load_subject(args)


# =============================================================================
# Commands
# =============================================================================


class TestCommands:
    def test_doctor_passes(self, capsys) -> None:
        assert main(["doctor"]) == EXIT_OK
        assert "FAIL" not in capsys.readouterr().out

    def test_detectors_lists_registered(self, capsys) -> None:
        assert main(["detectors"]) == EXIT_OK
        assert "DET-WHALE-01" in capsys.readouterr().out

    def test_investigate_text_output(self, capsys, subject_file) -> None:
        assert main(["investigate", "--subject", str(subject_file)]) == EXIT_OK
        out = capsys.readouterr().out
        assert "A01 BLOCKCHAIN INTELLIGENCE" in out
        assert "sell pressure" in out

    def test_investigate_json_output(self, capsys, subject_file) -> None:
        """
        The JSON contract: the analysis under `package`, the decision beside it.

        Nested rather than merged so the two namespaces cannot collide, and so
        a consumer can tell what A01 observed from what it decided about it.
        """
        code = main(
            ["--format", "json", "investigate", "--subject", str(subject_file)]
        )
        assert code == EXIT_OK
        payload = json.loads(capsys.readouterr().out)

        assert payload["package"]["scores"]
        assert payload["package"]["evidence_chains"]
        assert "conclusions" in payload["decision"]

    def test_investigate_json_carries_the_decision(self, capsys, subject_file) -> None:
        """Every conclusion states its verb and what would retract it."""
        main(["--format", "json", "investigate", "--subject", str(subject_file)])
        decision = json.loads(capsys.readouterr().out)["decision"]

        assert decision["conclusions"]
        for conclusion in decision["conclusions"]:
            assert conclusion["falsified_by"]
            assert conclusion["qualifier"]

    def test_the_cli_raises_no_alerts(self, capsys, subject_file) -> None:
        """
        Not a placeholder assertion. Alerting requires a measured error rate,
        no detector has one, and a passing test here while one alerted would
        mean the gate had been bypassed.
        """
        main(["--format", "json", "investigate", "--subject", str(subject_file)])
        decision = json.loads(capsys.readouterr().out)["decision"]

        assert decision["alerts"]["raised"] == []
        assert decision["alerts"]["silent"] is True

    def test_investigate_without_address_exits_usage(self, capsys) -> None:
        assert main(["investigate"]) == EXIT_USAGE
        assert "error:" in capsys.readouterr().err

    def test_unknown_subject_still_produces_a_package(self, capsys) -> None:
        """No signal is a valid result, not a failure."""
        assert main(["investigate", "--address", "0x0"]) == EXIT_OK
        out = capsys.readouterr().out
        assert "Signal      : 0.0/100" in out
        # Absence of reference data must read as "cannot tell", never as
        # "nothing is happening".
        assert "not determinable" in out
        assert "cannot be determined" in out


# =============================================================================
# Confidence vocabulary
# =============================================================================


class TestConfidenceVocabulary:
    """Verb choice must not upgrade an inference into a fact."""

    @pytest.mark.parametrize(
        "confidence,expected",
        [
            (0.95, "is"),
            (0.75, "strongly indicates"),
            (0.55, "likely"),
            (0.35, "possibly"),
            (0.10, "cannot be determined from"),
        ],
    )
    def test_qualifier_matches_confidence(
        self, confidence: float, expected: str
    ) -> None:
        assert qualify(confidence)[1] == expected

    def test_low_confidence_never_renders_assertive_verb(self) -> None:
        package = {
            "package_id": "pkg-1",
            "subject": {"address": "0xabc"},
            "scores": [{"name": "signal", "value": 10.0, "band": "low"}],
            "evidence_chains": [],
            "metadata": {
                "findings": {"report": {"subject": "0xabc", "confidence": 0.2}}
            },
        }
        text = render_text(package)
        assert "cannot be determined" in text
        assert "strongly indicates" not in text

    def test_renderer_survives_empty_package(self) -> None:
        text = render_text({"package_id": "p", "subject": {}, "metadata": {}})
        assert "A01 BLOCKCHAIN INTELLIGENCE" in text


class TestIngest:
    """
    The command that makes A01 more than a query tool over an empty database.

    Driven against the replay fixture, so these run offline and deterministically
    rather than against whatever mainnet happens to be doing.
    """

    def test_ingest_requires_a_database(self, capsys) -> None:
        with pytest.raises(SystemExit):
            main(["ingest"])

    def test_an_unreachable_chain_is_reported_not_crashed(self, capsys) -> None:
        """Bitcoin is in the registry but has no sensor for its RPC dialect."""
        code = main(["ingest", "--db", "unused.db", "--chain", "notachain"])

        assert code == EXIT_USAGE
        assert "no sensor" in capsys.readouterr().err

    def test_ingest_writes_blocks_and_reports_what_it_did(self, capsys, tmp_path, monkeypatch) -> None:
        from fixtures.replay import Recording, ReplaySensor
        from sensors import SensorRegistry

        recording = Recording.named("ethereum_mainnet")
        monkeypatch.setattr(
            SensorRegistry, "get", lambda self, chain: ReplaySensor(recording)
        )

        code = main([
            "ingest", "--db", str(tmp_path / "a01.db"),
            "--blocks", "3", "--confirmations", "0",
            "--start", str(recording.heights[0]),
        ])
        out = capsys.readouterr().out

        assert code == EXIT_OK
        assert "stored     : 3 block(s)" in out
        assert "transaction(s)" in out

    def test_a_second_run_resumes_rather_than_restarting(self, capsys, tmp_path, monkeypatch) -> None:
        """Checkpointed progress is what makes the job safe to schedule."""
        from fixtures.replay import Recording, ReplaySensor
        from sensors import SensorRegistry

        recording = Recording.named("ethereum_mainnet")
        monkeypatch.setattr(
            SensorRegistry, "get", lambda self, chain: ReplaySensor(recording)
        )
        db = str(tmp_path / "a01.db")
        args = ["ingest", "--db", db, "--blocks", "3", "--confirmations", "0"]

        main(args + ["--start", str(recording.heights[0])])
        capsys.readouterr()
        main(args)
        out = capsys.readouterr().out

        # Resumed past the first three, so it took the next ones rather than
        # re-fetching what it already had.
        assert "database   : 6 block(s)" in out or "advanced" in out

    def test_backfill_takes_a_fixed_range(self, capsys, tmp_path, monkeypatch) -> None:
        from fixtures.replay import Recording, ReplaySensor
        from sensors import SensorRegistry

        recording = Recording.named("ethereum_mainnet")
        monkeypatch.setattr(
            SensorRegistry, "get", lambda self, chain: ReplaySensor(recording)
        )

        code = main([
            "ingest", "--db", str(tmp_path / "a01.db"), "--backfill",
            "--start", str(recording.heights[0]), "--blocks", "4",
        ])
        out = capsys.readouterr().out

        assert code == EXIT_OK
        assert "backfill" in out
        assert "stored     : 4 block(s)" in out


class TestCredentials:
    """
    Provider keys are read from `os.environ`, and nothing else puts a file's
    contents there. Before the CLI loaded a `.env`, a correctly written key
    file activated no provider and A01 quietly ran on free endpoints.
    """

    def test_the_entry_point_loads_a_dotenv(self, tmp_path, monkeypatch):
        from config import dotenv

        dotenv.reset()
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("A01_TEST_MARKER=loaded\n", encoding="utf-8")
        monkeypatch.setattr(dotenv, "candidate_paths", lambda start=None: (tmp_path / ".env",))

        main(["detectors"])

        import os

        assert os.environ.get("A01_TEST_MARKER") == "loaded"
        os.environ.pop("A01_TEST_MARKER", None)
        dotenv.reset()

    def test_providers_reports_dormant_and_usable(self, capsys) -> None:
        assert main(["providers"]) == EXIT_OK
        out = capsys.readouterr().out

        assert "dormant" in out
        assert "usable" in out
        assert "ALCHEMY_API_KEY" in out, "a dormant provider must name its variable"

    def test_providers_json_shape(self, capsys) -> None:
        main(["--format", "json", "providers"])
        payload = json.loads(capsys.readouterr().out)

        assert "keyed_providers_active" in payload
        assert payload["endpoints"] > 0

    def test_no_key_value_is_ever_printed(self, capsys, monkeypatch) -> None:
        """A key that reaches a log or a report is a key that must be rotated."""
        monkeypatch.setenv("ALCHEMY_API_KEY", "sentinel-secret-value")
        main(["providers"])

        assert "sentinel-secret-value" not in capsys.readouterr().out


class TestApprovals:
    """
    The read path onto stored approval grants. The screen must report breadth
    without asserting a spender is dangerous -- the one inference the data
    cannot support -- so its limits are checked as strictly as its figures.
    """

    OWNER = "0x" + "11" * 20
    SPENDER = "0x" + "22" * 20
    TOKEN = "0x" + "44" * 20

    def _seed(self, path):
        from contracts.signatures import APPROVAL_FOR_ALL_TOPIC, APPROVAL_TOPIC
        from database import (
            Database,
            RecordWriter,
            SqliteApprovalRepository,
            SqliteBlockRepository,
        )
        from normalization.approvals import normalize_approvals
        from sensors.envelope import Provenance, RawRecord, RecordKind

        def word(a):
            return "0x" + a[2:].rjust(64, "0")

        block = RawRecord(
            chain="ethereum",
            kind=RecordKind.BLOCK,
            height=100,
            provenance=Provenance("fixture", "ethereum", "eth_getBlockByNumber", "ok"),
            payload={
                "number": hex(100),
                "hash": "0xa000100",
                "parentHash": "0xa000099",
                "timestamp": hex(1_700_000_000),
                "transactions": [],
            },
        )
        logs = [
            {
                "address": self.TOKEN,
                "topics": [APPROVAL_TOPIC, word(self.OWNER), word(self.SPENDER)],
                "data": "0x" + format(2**255, "064x"),  # unlimited
                "blockNumber": 100,
                "logIndex": 0,
                "blockHash": "0xa000100",
                "transactionHash": "0xt0",
            },
            {
                "address": self.TOKEN,
                "topics": [APPROVAL_FOR_ALL_TOPIC, word(self.OWNER), word(self.SPENDER)],
                "data": "0x" + format(1, "064x"),
                "blockNumber": 100,
                "logIndex": 1,
                "blockHash": "0xa000100",
                "transactionHash": "0xt1",
            },
        ]
        with Database(path) as db:
            RecordWriter(SqliteBlockRepository(db)).write(block)
            activity, _ = normalize_approvals(logs, chain="ethereum")
            SqliteApprovalRepository(db).save(activity)

    def test_a_missing_database_exits_usage(self, capsys, tmp_path) -> None:
        code = main(["approvals", "--db", str(tmp_path / "none.db"), "--address", self.OWNER])
        assert code == EXIT_USAGE
        assert "not found" in capsys.readouterr().err

    def test_the_screen_reports_breadth_and_its_own_limits(self, capsys, tmp_path) -> None:
        db = tmp_path / "a01.db"
        self._seed(db)

        code = main(["approvals", "--db", str(db), "--address", self.OWNER])
        out = capsys.readouterr().out

        assert code == EXIT_OK
        assert "2 live" in out
        assert "unlimited" in out
        # The limits are never omitted: a list of unlimited grants without them
        # reads as an accusation the data cannot support.
        assert "not determined here" in out
        assert "no label source" in out

    def test_json_carries_the_grants_and_the_unanswerable(self, capsys, tmp_path) -> None:
        db = tmp_path / "a01.db"
        self._seed(db)

        main(["--format", "json", "approvals", "--db", str(db), "--address", self.OWNER])
        payload = json.loads(capsys.readouterr().out)

        assert payload["total"] == 2
        assert payload["unlimited"] == 2
        assert payload["collection_wide"] == 1
        assert payload["unanswerable"], "the screen must carry its limits into JSON too"
