"""
CIE-OS
A02 News Intelligence Agent

Module:
    core.observability

Purpose:
    Structured logging, metrics, and health checks.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

# ==============================================================================
# STRUCTURED LOGGING
# ==============================================================================


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add extra fields
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)
        
        # Add exception info
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data, ensure_ascii=False)


class ContextFilter(logging.Filter):
    """Adds context (request_id, etc.) to log records."""
    
    def __init__(self):
        super().__init__()
        self.context: dict[str, Any] = {}
    
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in self.context.items():
            setattr(record, key, value)
        return True
    
    def set_context(self, **kwargs: Any) -> None:
        self.context.update(kwargs)
    
    def clear_context(self) -> None:
        self.context.clear()
    
    @contextmanager
    def context_manager(self, **kwargs: Any):
        old_context = self.context.copy()
        self.context.update(kwargs)
        try:
            yield
        finally:
            self.context = old_context


# Global context filter
_context_filter = ContextFilter()


def get_context_filter() -> ContextFilter:
    return _context_filter


def setup_logging(
    level: str = "INFO",
    json_format: bool = True,
    log_file: str | None = None,
) -> logging.Logger:
    """Configure structured logging for the application."""
    
    logger = logging.getLogger("a02")
    logger.setLevel(getattr(logging, level.upper()))
    logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    if json_format:
        console_handler.setFormatter(JsonFormatter())
    else:
        console_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        )
    console_handler.addFilter(_context_filter)
    logger.addHandler(console_handler)
    
    # File handler (optional)
    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFormatter())
        file_handler.addFilter(_context_filter)
        logger.addHandler(file_handler)
    
    return logger


# ==============================================================================
# METRICS
# ==============================================================================


@dataclass
class MetricPoint:
    """A single metric data point."""
    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metric_type: str = "gauge"  # gauge, counter, histogram


class MetricsCollector:
    """Collects and exports metrics."""
    
    def __init__(self):
        self._metrics: dict[str, list[MetricPoint]] = {}
        self._counters: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
    
    def gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Set a gauge value."""
        point = MetricPoint(
            name=name,
            value=value,
            labels=labels or {},
            metric_type="gauge",
        )
        self._metrics.setdefault(name, []).append(point)
    
    def counter(self, name: str, increment: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """Increment a counter."""
        key = name + "|" + "|".join(f"{k}={v}" for k, v in sorted((labels or {}).items()))
        self._counters[key] = self._counters.get(key, 0) + increment
        
        point = MetricPoint(
            name=name,
            value=self._counters[key],
            labels=labels or {},
            metric_type="counter",
        )
        self._metrics.setdefault(name, []).append(point)
    
    def histogram(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Record a histogram value."""
        key = name + "|" + "|".join(f"{k}={v}" for k, v in sorted((labels or {}).items()))
        self._histograms.setdefault(key, []).append(value)
        
        point = MetricPoint(
            name=name,
            value=value,
            labels=labels or {},
            metric_type="histogram",
        )
        self._metrics.setdefault(name, []).append(point)
    
    def timing(self, name: str, duration_seconds: float, labels: dict[str, str] | None = None) -> None:
        """Record a timing (in seconds)."""
        self.histogram(name + "_seconds", duration_seconds, labels)
    
    def get_metrics(self) -> dict[str, Any]:
        """Get all metrics in Prometheus-compatible format."""
        output = {}
        for name, points in self._metrics.items():
            if not points:
                continue
            latest = points[-1]
            output[name] = {
                "value": latest.value,
                "labels": latest.labels,
                "type": latest.metric_type,
                "timestamp": latest.timestamp.isoformat(),
            }
        return output
    
    def get_prometheus_format(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = []
        for name, points in self._metrics.items():
            if not points:
                continue
            latest = points[-1]
            labels_str = "{" + ",".join(f'{k}="{v}"' for k, v in latest.labels.items()) + "}"
            lines.append(f"# TYPE {name} {latest.metric_type}")
            lines.append(f"{name}{labels_str} {latest.value} {int(latest.timestamp.timestamp() * 1000)}")
        return "\n".join(lines)
    
    def reset(self) -> None:
        self._metrics.clear()
        self._counters.clear()
        self._histograms.clear()


# Global metrics collector
_metrics_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    return _metrics_collector


# ==============================================================================
# HEALTH CHECKS
# ==============================================================================


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    name: str
    status: str  # healthy, degraded, unhealthy
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float = 0.0


class HealthCheck:
    """Base class for health checks."""
    
    def __init__(self, name: str):
        self.name = name
    
    async def check(self) -> HealthCheckResult:
        start = time.perf_counter()
        try:
            result = await self._check()
            duration = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name=self.name,
                status=result.get("status", "healthy"),
                message=result.get("message", ""),
                details=result.get("details", {}),
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name=self.name,
                status="unhealthy",
                message=str(e),
                duration_ms=duration,
            )
    
    async def _check(self) -> dict:
        raise NotImplementedError


class DatabaseHealthCheck(HealthCheck):
    """Health check for database connectivity."""
    
    def __init__(self, db_path: str):
        super().__init__("database")
        self.db_path = db_path
    
    async def _check(self) -> dict:
        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("SELECT 1")
            await db.execute("SELECT COUNT(*) FROM items")
        return {"status": "healthy", "message": "Database connected"}


class ExternalServiceHealthCheck(HealthCheck):
    """Health check for external API."""
    
    def __init__(self, name: str, url: str, timeout: float = 5.0):
        super().__init__(name)
        self.url = url
        self.timeout = timeout
    
    async def _check(self) -> dict:
        import urllib.request
        try:
            req = urllib.request.Request(self.url, headers={"User-Agent": "A02-HealthCheck"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if 200 <= resp.status < 300:
                    return {"status": "healthy", "message": f"HTTP {resp.status}"}
                else:
                    return {"status": "degraded", "message": f"HTTP {resp.status}"}
        except Exception as e:
            return {"status": "unhealthy", "message": str(e)}


class HealthCheckRegistry:
    """Registry for all health checks."""
    
    def __init__(self):
        self._checks: list[HealthCheck] = []
    
    def register(self, check: HealthCheck) -> None:
        self._checks.append(check)
    
    async def run_all(self) -> dict[str, HealthCheckResult]:
        results = {}
        for check in self._checks:
            results[check.name] = await check.check()
        return results
    
    async def get_overall_status(self) -> str:
        results = await self.run_all()
        if any(r.status == "unhealthy" for r in results.values()):
            return "unhealthy"
        if any(r.status == "degraded" for r in results.values()):
            return "degraded"
        return "healthy"


# ==============================================================================
# REQUEST TRACING
# ==============================================================================


class RequestTracer:
    """Distributed request tracing (simplified)."""
    
    def __init__(self):
        self._spans: dict[str, dict] = {}
    
    @contextmanager
    def trace(self, operation: str, **attributes):
        trace_id = str(uuid4())[:8]
        span_id = str(uuid4())[:8]
        start = time.perf_counter()
        
        span = {
            "trace_id": trace_id,
            "span_id": span_id,
            "operation": operation,
            "start_time": datetime.now(UTC).isoformat(),
            "attributes": attributes,
            "events": [],
        }
        self._spans[trace_id] = span
        
        try:
            yield span
            span["status"] = "ok"
        except Exception as e:
            span["status"] = "error"
            span["error"] = str(e)
            raise
        finally:
            span["duration_ms"] = (time.perf_counter() - span.get("_start", time.perf_counter())) * 1000
            span["end_time"] = datetime.now(UTC).isoformat()
    
    def add_event(self, trace_id: str, name: str, **attributes):
        if trace_id in self._spans:
            self._spans[trace_id]["events"].append({
                "name": name,
                "timestamp": datetime.now(UTC).isoformat(),
                "attributes": attributes,
            })
    
    def get_trace(self, trace_id: str) -> dict | None:
        return self._spans.get(trace_id)


# Global instances
_tracer = RequestTracer()


def get_tracer() -> RequestTracer:
    return _tracer


__all__ = [
    "JsonFormatter",
    "ContextFilter",
    "get_context_filter",
    "setup_logging",
    "MetricPoint",
    "MetricsCollector",
    "get_metrics_collector",
    "HealthCheckResult",
    "HealthCheck",
    "DatabaseHealthCheck",
    "ExternalServiceHealthCheck",
    "HealthCheckRegistry",
    "RequestTracer",
    "get_tracer",
]