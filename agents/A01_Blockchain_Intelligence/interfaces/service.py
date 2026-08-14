"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    interfaces.service

Purpose:
    The one entry point every surface goes through — CLI, REST, and whatever
    comes next.

Design goals:
    - One implementation of each operation, several presentations of it
    - Typed results; a surface renders, it does not decide
    - Storage opened per call and closed after, so no surface holds a handle
    - Errors returned as values, because a transport must not raise a stack trace
    - Read-only throughout; there is no method here that writes

Notes:
    Every surface asking the layers below it directly is how surfaces drift. The
    CLI would gain a flag the REST API lacks, the REST API would apply the
    maturity gate in a slightly different place, and two callers would get two
    answers to the same question. Worse, the drift is invisible until someone
    compares them — and by then both are in use.

    So the pipeline is assembled once, here. A surface's only job is to turn a
    :class:`ServiceResult` into bytes.

    Operations return errors rather than raising them. A transport that has to
    catch exceptions to produce a status code will eventually miss one and leak
    a traceback to a client, which is both an information disclosure and an
    unhelpful response. ``ok`` and ``error`` make the failure path the same
    shape as the success path.

    The service is read-only by construction. A01 holds no keys and writes to no
    chain (``identity/scope.md`` §4), and the ingestion write path is deliberately
    absent from this facade: exposing "fetch and store these blocks" over an
    interface would put an unbounded, rate-limited, externally-triggered job
    behind a request, which is a denial-of-service surface rather than a feature.
    Ingestion stays operator-driven.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from decision import DecisionEngine, Subscription
from intelligence.narrative import NarrativeService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ServiceResult:
    """
    One operation's outcome, successful or not.

    ``status`` is an HTTP-shaped integer even for the CLI. Inventing a second
    vocabulary and mapping between them is how a "not found" becomes a 500 in
    one surface and a 404 in another.
    """

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    status: int = 200

    @classmethod
    def success(cls, data: dict[str, Any]) -> ServiceResult:
        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, error: str, status: int = 400) -> ServiceResult:
        return cls(ok=False, error=error, status=status)

    def as_dict(self) -> dict[str, Any]:
        return self.data if self.ok else {"error": self.error}


class IntelligenceService:
    """
    A01's operations, assembled once.

    Holds the decision engine because it carries alert-budget state that must
    persist across calls; everything else is built per request. The database is
    opened and closed per call rather than held: a long-lived handle would keep
    a WAL reader open against a file the ingestion writer is appending to, and
    it would make the service's lifetime a constraint on the operator's.
    """

    def __init__(
        self,
        *,
        database_path: str | Path | None = None,
        subscriptions: Iterable[Subscription] = (),
    ) -> None:
        self._database_path = Path(database_path) if database_path else None
        self._decisions = DecisionEngine(subscriptions=subscriptions)
        self._narrative = NarrativeService()

    @property
    def database_path(self) -> Path | None:
        return self._database_path

    @property
    def decisions(self) -> DecisionEngine:
        return self._decisions

    @property
    def narrative(self) -> NarrativeService:
        return self._narrative

    @property
    def has_storage(self) -> bool:
        return self._database_path is not None and self._database_path.is_file()

    # -- catalogue --------------------------------------------------------

    def detectors(self) -> ServiceResult:
        """Every detector with its maturity and what blocks its promotion."""
        gate = self._decisions.gate
        return ServiceResult.success(
            {
                "detectors": [entry.as_dict() for entry in gate],
                "alerting": [e.detector for e in gate.alerting_detectors()],
                "note": (
                    "A detector may raise alerts only at validated maturity. "
                    "None has a measured error rate, so none alerts."
                ),
            }
        )

    def skills(self) -> ServiceResult:
        """Implemented skills, and the data source each unbuilt one needs."""
        from skills import default_registry

        registry = default_registry()
        return ServiceResult.success(
            {
                "implemented": list(registry.catalog()),
                "planned": list(registry.planned()),
            }
        )

    def chains(self) -> ServiceResult:
        """
        Every registered chain, what A01 can observe on it, and what bounds it.

        Offline by construction: this reads the measured capability table rather
        than probing. A route that probed fifteen chains would take as long as
        the slowest of them and would turn a status page into a load generator.
        The table carries its own measurement date so a reader can judge how
        stale it is, and ``knowledge.chains.probe()`` re-measures on demand.
        """
        from knowledge.chains import summary

        return ServiceResult.success(summary())

    def labels(self, chain: str = "") -> ServiceResult:
        """
        What address labels are loaded, and who says so.

        Reported per source rather than as one total. Two lists disagreeing
        about an address is a fact about the lists, and a single number hides
        which one an attribution came from.
        """
        from database import Database
        from tiers.ledger import LabelRepository

        if not self.has_storage:
            return ServiceResult.failure("no database configured", status=503)

        with Database(self._database_path) as database:
            repository = LabelRepository(database)
            payload = repository.summary()
            payload["entities"] = list(repository.entities(chain=chain))
            payload["note"] = (
                "A label is an external assertion, never inferred from "
                "behaviour. An unverified one bounds every conclusion drawn "
                "from it."
            )

        return ServiceResult.success(payload)

    def flows(self, chain: str = "ethereum") -> ServiceResult:
        """
        Exchange deposits and withdrawals over stored history.

        Runs the same :class:`ExchangeFlowSkill` the CLI and the composer use,
        so the three surfaces cannot drift into three different answers. An
        undetermined result is returned as a success carrying its reason: "no
        labels are loaded" is an answer about A01, not a server fault.
        """
        from database import Database, SqliteAnalyticsRepository
        from skills.base import SkillRequest
        from skills.exchange_flow import ExchangeFlowSkill

        if not self.has_storage:
            return ServiceResult.failure("no database configured", status=503)

        with Database(self._database_path) as database:
            result = ExchangeFlowSkill().run(
                SkillRequest(chain=chain), SqliteAnalyticsRepository(database)
            )

        return ServiceResult.success(
            {
                "chain": chain,
                "determined": result.determined,
                "reason": result.reason,
                "coverage": result.coverage.as_dict(),
                "flow": result.data,
            }
        )

    def coverage(self, chain: str = "ethereum") -> ServiceResult:
        """
        How much history is stored for a chain, and what it licenses.

        The question a caller should ask before trusting any negative answer,
        so it is available without running an investigation to find out.
        """
        from database import Database, SqliteAnalyticsRepository
        from skills.base import Coverage

        if not self.has_storage:
            return ServiceResult.failure("no database configured", status=503)

        with Database(self._database_path) as database:
            window = SqliteAnalyticsRepository(database).window(chain)

        return ServiceResult.success(Coverage(window=window).as_dict())

    # -- investigation ----------------------------------------------------

    def investigate(
        self,
        *,
        chain: str = "ethereum",
        address: str | None = None,
        subject: dict[str, Any] | None = None,
    ) -> ServiceResult:
        """
        Run the full path: compose from storage, analyse, decide.

        ``subject`` supplements what storage cannot answer — a balance, a
        circulating supply. It is applied after composition so an operator
        override is theirs, and is not mistaken for something A01 established.
        """
        from intelligence.core.engine import IntelligenceEngine

        composed: dict[str, Any] = {"chain": chain}
        composition_report: dict[str, Any] | None = None

        if self.has_storage:
            result = self._compose(chain=chain, address=address)
            if not result.ok:
                return result
            composed = dict(result.data["subject"])
            composition_report = result.data["composition"]
        elif address:
            composed["address"] = address

        if subject:
            composed.update(subject)

        if not composed.get("address") and not composition_report:
            return ServiceResult.failure(
                "no subject: supply an address, a subject body, or configure a database",
                status=400,
            )

        package = IntelligenceEngine().run(composed)
        decision = self._decisions.decide(package)

        # The narrative goes through NarrativeService rather than being built
        # here, so that if a model provider is ever configured its output still
        # passes the grounding check on the way to this payload.
        evidence = [
            artifact
            for chain in getattr(package, "evidence_chains", ())
            for artifact in getattr(chain, "artifacts", ())
        ]
        publication = self._narrative.publish(decision, evidence=evidence)

        payload: dict[str, Any] = {
            "package": package.to_dict(),
            "decision": decision.as_dict(),
            "narrative": publication.as_dict(),
            "generated_at": datetime.now(UTC).isoformat(),
        }
        if composition_report is not None:
            payload["composition"] = composition_report
        return ServiceResult.success(payload)

    def _compose(self, *, chain: str, address: str | None) -> ServiceResult:
        """Build a subject from stored history via the skills layer."""
        from database import Database, SqliteAnalyticsRepository
        from intelligence.engines import SubjectComposer

        try:
            with Database(self._database_path) as database:
                composition = SubjectComposer().compose(
                    SqliteAnalyticsRepository(database),
                    chain=chain,
                    address=address,
                )
        except Exception as exc:  # noqa: BLE001 - storage boundary
            logger.warning("composition failed: %s", exc)
            return ServiceResult.failure(f"storage unavailable: {exc}", status=503)

        if not composition.usable and composition.limitations:
            # A composition that produced nothing usually means a rejected
            # address or an empty database, and both are the caller's problem
            # to fix rather than a server fault.
            if any("address rejected" in note for note in composition.limitations):
                return ServiceResult.failure(
                    "; ".join(composition.limitations), status=400
                )

        return ServiceResult.success(
            {"subject": composition.subject, "composition": composition.as_dict()}
        )

    def observe(self, registry: Any) -> None:
        """
        Record current state into a metrics registry.

        Pull-based: the registry is filled when something asks, rather than the
        service holding a reference and writing continuously. A metrics client
        that stops scraping should cost nothing, and an agent that is idle
        should not be doing work on its behalf.
        """
        from database import Database, SqliteAnalyticsRepository
        from skills.base import Coverage

        registry.gauge(
            "storage_available",
            1.0 if self.has_storage else 0.0,
            "1 when a chain database is configured and present",
        )
        registry.gauge(
            "detectors_alerting",
            len(self._decisions.gate.alerting_detectors()),
            "Detectors permitted to raise alerts",
        )

        if not self.has_storage:
            return

        with Database(self._database_path) as database:
            health = database.health()
            registry.gauge(
                "stored_blocks", health["rows"]["blocks"], "Blocks in storage",
                labels={"chain": "ethereum"},
            )
            registry.gauge(
                "stored_transactions",
                health["rows"]["transactions"],
                "Transactions in storage",
                labels={"chain": "ethereum"},
            )
            registry.gauge(
                "withdrawn_blocks",
                health["withdrawn_blocks"],
                "Blocks withdrawn by a reorg",
                labels={"chain": "ethereum"},
            )
            window = SqliteAnalyticsRepository(database).window("ethereum")
            registry.observe_coverage(Coverage(window=window))

    def metrics(self) -> ServiceResult:
        """Current metrics, refreshed on request."""
        from telemetry import REGISTRY

        self.observe(REGISTRY)
        return ServiceResult.success(REGISTRY.as_dict())

    # -- diagnostics ------------------------------------------------------

    def health(self) -> ServiceResult:
        """Operational status, for doctor and for a REST liveness check."""
        from skills import default_registry

        payload: dict[str, Any] = {
            "agent": "A01 Blockchain Intelligence",
            "read_only": True,
            "storage": {
                "configured": self._database_path is not None,
                "available": self.has_storage,
                "path": str(self._database_path) if self._database_path else None,
            },
            "skills": len(default_registry()),
            "decision": self._decisions.health(),
            "narrative": self._narrative.health(),
            "checked_at": datetime.now(UTC).isoformat(),
        }

        if self.has_storage:
            from database import Database

            with Database(self._database_path) as database:
                payload["storage"].update(database.health())

        return ServiceResult.success(payload)

    def __repr__(self) -> str:
        return f"IntelligenceService(storage={self._database_path!s})"


__all__ = ["IntelligenceService", "ServiceResult"]
