"""
Memory Synchronization Coordination

Top-level synchronization orchestration and reporting: status
summaries, full pipelines, and checkpoints over a
``MemoryManager``-like source.
"""

from __future__ import annotations

from typing import Any

ReportSource = Any
ManagerSource = Any


class SyncReporter:
    """
    Build human- and machine-readable sync reports.

    Responsibilities:
        * Produce a status report from a memory source
        * Summarize boolean status dictionaries
        * Render a short human-readable summary
    """

    def __init__(self) -> None:
        pass

    async def report(self, source: ReportSource) -> dict[str, Any]:
        method = getattr(source, "synchronization_report", None)
        if not callable(method):
            return self._from_synchronize(source)
        result = method()
        payload = (
            await result if hasattr(result, "__await__") else result
        )
        if not isinstance(payload, dict):
            raise TypeError(
                "synchronization_report() must return a dict."
            )
        return payload

    async def _from_synchronize(
        self,
        source: ReportSource,
    ) -> dict[str, Any]:
        synchronize = getattr(source, "synchronize", None)
        if not callable(synchronize):
            return {}
        result = synchronize()
        payload = (
            await result if hasattr(result, "__await__") else result
        )
        if isinstance(payload, dict):
            return payload
        return {"synchronized": True}

    def summarize(
        self,
        status: dict[str, bool],
    ) -> dict[str, Any]:
        entries = list(status.items())
        total = len(entries)
        successful = sum(1 for _, ok in entries if ok)
        failed = total - successful
        return {
            "total": total,
            "successful": successful,
            "failed": failed,
            "successful_names": sorted(
                name for name, ok in entries if ok
            ),
            "failed_names": sorted(
                name for name, ok in entries if not ok
            ),
            "all_successful": failed == 0,
        }

    def format(
        self,
        status: dict[str, bool],
    ) -> str:
        summary = self.summarize(status)
        if summary["total"] == 0:
            return "no sync sources"
        return (
            f"{summary['successful']}/{summary['total']} synced"
            + (
                f"; failed: {', '.join(summary['failed_names'])}"
                if summary["failed"]
                else ""
            )
        )


class SyncCoordinatorError(Exception):
    pass


class SyncCoordinator:
    """
    Top-level synchronization orchestrator.

    Responsibilities:
        * Synchronize all registered memories
        * Synchronize a namespace or a single backend
        * Run the full pipeline and report the outcome
        * Create synchronization checkpoints
    """

    def __init__(self, manager: ManagerSource) -> None:
        self._manager = manager

    @property
    def manager(self) -> ManagerSource:
        return self._manager

    async def synchronize(self) -> dict[str, bool]:
        return await self._invoke("synchronize", {})

    async def synchronize_namespace(
        self,
        namespace: str,
    ) -> dict[str, bool]:
        return await self._invoke(
            "synchronize_namespace", {}, namespace=namespace
        )

    async def synchronize_backend(self, backend_name: str) -> bool:
        result = await self._invoke(
            "synchronize_backend",
            False,
            backend_name=backend_name,
        )
        return bool(result)

    async def synchronize_all_backends(self) -> dict[str, bool]:
        return await self._invoke("synchronize_all_backends", {})

    async def run_pipeline(self) -> dict[str, Any]:
        result = await self._invoke("synchronize_pipeline", {})
        if not isinstance(result, dict):
            raise SyncCoordinatorError(
                "synchronize_pipeline() must return a dict."
            )
        return result

    async def run_if_needed(self) -> bool:
        result = await self._invoke("synchronize_if_needed", False)
        return bool(result)

    async def checkpoint(self) -> dict[str, Any]:
        result = await self._invoke("checkpoint", {})
        if not isinstance(result, dict):
            raise SyncCoordinatorError(
                "checkpoint() must return a dict."
            )
        return result

    async def _invoke(
        self,
        name: str,
        default: Any,
        **kwargs: Any,
    ) -> Any:
        method = getattr(self._manager, name, None)
        if not callable(method):
            return default
        result = method(**kwargs)
        if hasattr(result, "__await__"):
            return await result
        return result
