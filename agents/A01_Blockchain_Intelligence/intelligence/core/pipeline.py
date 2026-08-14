"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.core.pipeline

Purpose:
    Ordered orchestration of intelligence pipeline stages.

    Supports both synchronous and asynchronous stage functions, records
    per-stage timings, and isolates stage failures so a single broken
    stage does not abort the entire investigation. A hard timeout
    applies to every stage — synchronous stages run in a worker
    executor so a blocking call cannot stall the pipeline.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import logging
import time

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..schemas.intelligence import IntelligencePipeline, PipelineStage
from ..utils.constants import DEFAULT_PIPELINE_TIMEOUT_SECONDS
from .context import IntelligenceContext

logger = logging.getLogger("a01.intelligence.core")

StageFn = Callable[[IntelligenceContext], Any]


@dataclass(slots=True)
class StageResult:
    """
    Outcome of executing a single pipeline stage.
    """

    stage: str
    ok: bool
    duration_seconds: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "ok": self.ok,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
        }


class AnalysisPipeline:
    """
    Runs an ordered sequence of stage functions over a context.

    Stages are executed in registration order. A failing stage is
    recorded and skipped without aborting subsequent stages. Results
    are scoped per execution: calling :meth:`run` (or :meth:`arun`)
    again starts from an empty result set.
    """

    def __init__(self, timeout_seconds: float = DEFAULT_PIPELINE_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout_seconds
        self._stages: list[tuple[PipelineStage | str, StageFn]] = []
        self._results: dict[str, StageResult] = {}

    def add(
        self,
        stage: PipelineStage | str,
        fn: StageFn,
    ) -> "AnalysisPipeline":
        """Register a stage function (sync or async)."""
        self._stages.append((stage, fn))
        return self

    @property
    def stages(self) -> list[tuple[PipelineStage | str, StageFn]]:
        """Registered stage functions."""
        return list(self._stages)

    @property
    def stage_count(self) -> int:
        """Number of registered stages."""
        return len(self._stages)

    async def _invoke(
        self,
        fn: StageFn,
        context: IntelligenceContext,
        loop: asyncio.AbstractEventLoop,
    ) -> object:
        """
        Run a stage under the configured timeout.

        Coroutine functions are awaited directly; synchronous stages
        execute in a thread so blocking calls stay time-bounded.
        """
        if inspect.iscoroutinefunction(fn):
            return await asyncio.wait_for(fn(context), timeout=self._timeout)
        return await asyncio.wait_for(
            loop.run_in_executor(None, fn, context),
            timeout=self._timeout,
        )

    def run(self, context: IntelligenceContext) -> IntelligencePipeline:
        """
        Execute all stages over the context in registration order.

        Returns an ``IntelligencePipeline`` description with per-stage
        timings and completion metadata. Failures are recorded per stage
        rather than raised.
        """
        timings: dict[str, float] = {}
        self.clear_results()
        loop = asyncio.new_event_loop()

        try:
            for stage, fn in self._stages:
                start = time.monotonic()
                try:
                    loop.run_until_complete(self._invoke(fn, context, loop))
                    self._record(stage, ok=True, duration=time.monotonic() - start)
                    logger.debug("stage %s ok", stage)
                except asyncio.TimeoutError:
                    self._record(
                        stage,
                        ok=False,
                        duration=time.monotonic() - start,
                        error=f"timed out after {self._timeout}s",
                    )
                except asyncio.CancelledError:
                    self._record(
                        stage,
                        ok=False,
                        duration=time.monotonic() - start,
                        error="cancelled",
                    )
                except Exception as exc:  # noqa: BLE001 - stage boundary
                    logger.warning("stage %s failed: %s", stage, exc)
                    self._record(
                        stage,
                        ok=False,
                        duration=time.monotonic() - start,
                        error=str(exc),
                    )
                finally:
                    timings[str(stage)] = time.monotonic() - start
        finally:
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()

        failures = sum(1 for r in self._results.values() if not r.ok)
        return IntelligencePipeline(
            stage_timings=timings,
            completed_at=None,
            metadata={
                "stage_results": [r.to_dict() for r in self._results.values()],
                "failure_count": failures,
            },
        )

    def _record(
        self,
        stage: PipelineStage | str,
        *,
        ok: bool,
        duration: float,
        error: str | None = None,
    ) -> None:
        self._results[str(stage)] = StageResult(
            stage=str(stage),
            ok=ok,
            duration_seconds=round(duration, 6),
            error=error,
        )

    async def arun(self, context: IntelligenceContext) -> IntelligencePipeline:
        """
        Async variant of :meth:`run` for use inside a running loop.

        Prefer this when the caller already owns the event loop, to
        avoid nesting event loops.
        """
        timings: dict[str, float] = {}
        self.clear_results()
        loop = asyncio.get_running_loop()

        for stage, fn in self._stages:
            start = time.monotonic()
            try:
                await self._invoke(fn, context, loop)
                self._record(stage, ok=True, duration=time.monotonic() - start)
            except asyncio.TimeoutError:
                self._record(
                    stage,
                    ok=False,
                    duration=time.monotonic() - start,
                    error=f"timed out after {self._timeout}s",
                )
            except asyncio.CancelledError:
                self._record(
                    stage,
                    ok=False,
                    duration=time.monotonic() - start,
                    error="cancelled",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("stage %s failed: %s", stage, exc)
                self._record(
                    stage,
                    ok=False,
                    duration=time.monotonic() - start,
                    error=str(exc),
                )
            finally:
                timings[str(stage)] = time.monotonic() - start

        return IntelligencePipeline(
            stage_timings=timings,
            metadata={
                "stage_results": [r.to_dict() for r in self._results.values()],
                "failure_count": sum(1 for r in self._results.values() if not r.ok),
            },
        )

    def clear_results(self) -> None:
        """Reset recorded stage results (not the stage list)."""
        self._results.clear()
