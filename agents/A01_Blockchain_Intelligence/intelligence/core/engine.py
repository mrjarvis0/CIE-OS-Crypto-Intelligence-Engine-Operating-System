"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.core.engine

Purpose:
    Top-level intelligence engine entry point.

    Orchestrates a full intelligence investigation for a subject by
    driving the analysis pipeline through its lifecycle states and
    producing an evidence-backed ``IntelligencePackage``. Evidence
    artifacts collected on the context are grouped by claim and
    aggregated into evidence chains carried by the package.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..evidence.chain import EvidenceChainBuilder
from ..schemas.evidence import EvidenceArtifact
from ..schemas.intelligence import IntelligencePackage
from ..utils.helpers import new_id, now_utc
from .configuration import IntelligenceConfig
from .context import IntelligenceContext
from .pipeline import AnalysisPipeline
from .runtime import IntelligenceRuntime
from .state import EngineState, InvalidTransitionError

logger = logging.getLogger("a01.intelligence.core")


class IntelligenceEngine:
    """
    Orchestrates a full intelligence investigation for a subject.

    Responsibilities:
        * Begin an investigation in a fresh runtime/context
        * Drive the pipeline through lifecycle states
        * Produce a transportable IntelligencePackage
    """

    def __init__(
        self,
        config: IntelligenceConfig | None = None,
        *,
        register_defaults: bool = True,
    ) -> None:
        self.config = config or IntelligenceConfig()
        self.runtime = IntelligenceRuntime()
        self.pipeline = AnalysisPipeline(timeout_seconds=self.config.pipeline_timeout_seconds)
        self._chain_builder = EvidenceChainBuilder()

        # Without stages the engine runs to completion and returns an empty
        # package, which is indistinguishable from "nothing was found". Wire
        # the defaults unless the caller is composing its own pipeline.
        if register_defaults:
            from .stages import register_default_stages

            register_default_stages(self.pipeline)

    def start(self, subject: dict) -> IntelligenceContext:
        """
        Begin an investigation, returning a new context.

        The runtime is initialized to the COLLECTING state.
        """
        self.runtime.begin()
        try:
            self.runtime.transition(EngineState.COLLECTING)
        except InvalidTransitionError:
            logger.debug("runtime not in idle; continuing with current state")
        context = IntelligenceContext(
            subject=subject,
            context_id=new_id("ctx"),
        )
        logger.info("started investigation ctx=%s subject=%s", context.context_id, subject)
        return context

    def build_evidence_chains(
        self,
        context: IntelligenceContext,
    ) -> tuple[Any, ...]:
        """
        Aggregate context evidence into chains grouped by claim.

        Artifacts with the same claim are combined into a single
        evidence chain with source-weighted confidence.
        """
        by_claim: dict[str, list[EvidenceArtifact]] = {}
        for artifact in context.evidence:
            by_claim.setdefault(artifact.claim, []).append(artifact)
        return tuple(
            self._chain_builder.build(claim, artifacts)
            for claim, artifacts in by_claim.items()
        )

    def run(
        self,
        subject: dict,
        context: IntelligenceContext | None = None,
    ) -> IntelligencePackage:
        """
        Run the full pipeline for a subject and produce a package.

        When ``context`` is provided it is reused (so callers retain
        the populated context); otherwise a fresh context is created.

        Parameters
        ----------
        subject
            Subject descriptor (address, entity id, or arbitrary data).
        context
            Optional pre-existing investigation context to run on.

        Returns
        -------
        IntelligencePackage
            The complete transportable output of the investigation.
        """
        if context is None:
            context = self.start(subject)
        else:
            # The lifecycle must be driven even when an existing
            # context is reused, so the runtime reaches COMPLETED
            # rather than staying IDLE.
            self.runtime.begin()
            try:
                self.runtime.transition(EngineState.COLLECTING)
            except InvalidTransitionError:
                logger.debug("runtime not in idle; continuing with current state")
        started = time.monotonic()
        pipeline_result = self.pipeline.run(context)

        self.runtime.time_stage("pipeline", time.monotonic() - started)
        self.runtime.finish()

        package = IntelligencePackage(
            package_id=new_id("pkg"),
            subject=subject,
            pipeline=pipeline_result,
            evidence_chains=self.build_evidence_chains(context),
            scores=tuple(context.scores),
            created_at=now_utc(),
            metadata={
                "context_id": context.context_id,
                "state": self.runtime.state.value,
                "total_duration_seconds": round(time.monotonic() - started, 6),
                "findings": context.findings,
            },
        )
        logger.info(
            "completed investigation pkg=%s stages=%d evidence=%d",
            package.package_id,
            self.pipeline.stage_count,
            len(context.evidence),
        )
        return package

    async def arun(
        self,
        subject: dict,
        context: IntelligenceContext | None = None,
    ) -> IntelligencePackage:
        """
        Async variant of :meth:`run` using :meth:`AnalysisPipeline.arun`.

        Prefer this inside an existing event loop.
        """
        if context is None:
            context = self.start(subject)
        else:
            self.runtime.begin()
            try:
                self.runtime.transition(EngineState.COLLECTING)
            except InvalidTransitionError:
                logger.debug("runtime not in idle; continuing with current state")
        started = time.monotonic()
        pipeline_result = await self.pipeline.arun(context)

        self.runtime.time_stage("pipeline", time.monotonic() - started)
        self.runtime.finish()

        return IntelligencePackage(
            package_id=new_id("pkg"),
            subject=subject,
            pipeline=pipeline_result,
            evidence_chains=self.build_evidence_chains(context),
            scores=tuple(context.scores),
            created_at=now_utc(),
            metadata={
                "context_id": context.context_id,
                "state": self.runtime.state.value,
                "total_duration_seconds": round(time.monotonic() - started, 6),
                "findings": context.findings,
            },
        )
