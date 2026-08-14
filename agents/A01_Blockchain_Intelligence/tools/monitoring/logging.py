"""
Tools :: Monitoring :: Logging
==============================

Structured logging with JSON records and mandatory correlation IDs.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, Mapping, Optional, Sequence

__all__ = ["LogRecord", "StructuredLogger"]

_LEVELS = ("debug", "info", "warning", "error", "critical")


class LogRecord:
    """One structured log entry."""

    def __init__(
        self,
        level: str,
        message: str,
        *,
        correlation_id: str = "",
        source: str = "",
        event: str = "",
        **fields: Any,
    ) -> None:
        self.level = level
        self.message = message
        self.correlation_id = correlation_id or uuid.uuid4().hex
        self.source = source
        self.event = event
        self.fields = dict(fields)
        self.timestamp = time.time()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "message": self.message,
            "correlation_id": self.correlation_id,
            "source": self.source,
            "event": self.event,
            "timestamp": self.timestamp,
            **self.fields,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict())


class StructuredLogger:
    """In-memory structured logger; sink hook for real backends."""

    def __init__(self, *, source: str = "tools", sink: Optional[callable] = None) -> None:
        self.source = source
        self.sink = sink
        self._records: list[LogRecord] = []

    # -- writing ------------------------------------------------------------------ #

    def log(
        self,
        level: str,
        message: str,
        *,
        correlation_id: str = "",
        event: str = "",
        **fields: Any,
    ) -> LogRecord:
        record = LogRecord(
            level=level,
            message=message,
            correlation_id=correlation_id,
            source=self.source,
            event=event,
            **fields,
        )
        self._records.append(record)
        if self.sink is not None:
            self.sink(record)
        return record

    def debug(self, message: str, **kwargs: Any) -> LogRecord:
        return self.log("debug", message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> LogRecord:
        return self.log("info", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> LogRecord:
        return self.log("warning", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> LogRecord:
        return self.log("error", message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> LogRecord:
        return self.log("critical", message, **kwargs)

    # -- reading ------------------------------------------------------------------- #

    def records(self, *, level: str = "", correlation_id: str = "", limit: int = 500) -> list[LogRecord]:
        result = self._records
        if level:
            result = [r for r in result if r.level == level]
        if correlation_id:
            result = [r for r in result if r.correlation_id == correlation_id]
        return list(result[-max(1, int(limit)):])

    def errors(self, limit: int = 100) -> list[LogRecord]:
        return self.records(level="error", limit=limit) + self.records(level="critical", limit=limit)

    def export(self) -> str:
        return "\n".join(record.to_json() for record in self._records)