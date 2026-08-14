"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.logging

Purpose:
    Structured, correlation-friendly logging configuration for the A01 agent.

Design goals:
    - JSON structured logs by default
    - Correlation IDs for traceability
    - Optional OpenTelemetry trace/span enrichment
    - Environment-aware configuration
    - No business logic
    - Safe to import anywhere
"""

from __future__ import annotations

import contextvars
import json
import logging
import logging.config
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Final, Mapping


# ==============================================================================
# CONTEXT VARIABLES
# ==============================================================================

correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id",
    default=None,
)

trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "trace_id",
    default=None,
)

span_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "span_id",
    default=None,
)

chain_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "chain_id",
    default=None,
)

component_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "component",
    default=None,
)


# ==============================================================================
# CONSTANTS
# ==============================================================================

LOG_TIME_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%S.%fZ"
DEFAULT_LOG_FORMAT: Final[str] = "json"
DEFAULT_LOG_LEVEL: Final[str] = "INFO"
DEFAULT_LOGGER_NAME: Final[str] = "a01"
DEFAULT_STREAM = sys.stdout


# ==============================================================================
# OPTIONAL OPENTELEMETRY SUPPORT
# ==============================================================================

def _extract_otel_context() -> tuple[str | None, str | None]:
    """
    Try to read active OpenTelemetry trace/span context.

    OpenTelemetry integration is optional. If the package is unavailable or no
    active span exists, this returns (None, None).
    """
    try:
        from opentelemetry import trace  # type: ignore
    except Exception:
        return None, None

    span = trace.get_current_span()
    if span is None:
        return None, None

    ctx = span.get_span_context()
    if ctx is None or not ctx.is_valid:
        return None, None

    trace_id = format(ctx.trace_id, "032x")
    span_id = format(ctx.span_id, "016x")
    return trace_id, span_id


# ==============================================================================
# LOG RECORD ENRICHMENT
# ==============================================================================

class ContextFilter(logging.Filter):
    """
    Inject request-scoped context into every log record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get()
        record.trace_id = trace_id_var.get()
        record.span_id = span_id_var.get()
        record.chain_id = chain_id_var.get()
        record.component = component_var.get()
        return True


# ==============================================================================
# FORMATTERS
# ==============================================================================

class JsonFormatter(logging.Formatter):
    """
    Structured JSON log formatter.

    Emits stable schema fields suitable for indexing and correlation.
    """

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            LOG_TIME_FORMAT
        )

        base: dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "process": record.process,
            "thread": record.threadName,
            "correlation_id": getattr(record, "correlation_id", None),
            "trace_id": getattr(record, "trace_id", None),
            "span_id": getattr(record, "span_id", None),
            "chain_id": getattr(record, "chain_id", None),
            "component": getattr(record, "component", None),
        }

        if record.exc_info:
            base["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "extra") and isinstance(record.extra, dict):
            base["extra"] = record.extra

        return json.dumps(base, ensure_ascii=False, separators=(",", ":"))


class TextFormatter(logging.Formatter):
    """
    Human-readable formatter for console debugging.
    """

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            LOG_TIME_FORMAT
        )
        correlation_id = getattr(record, "correlation_id", None)
        chain_id = getattr(record, "chain_id", None)
        component = getattr(record, "component", None)

        prefix = (
            f"{timestamp} | {record.levelname:<8} | "
            f"{record.name} | cid={correlation_id} | "
            f"chain={chain_id} | component={component}"
        )
        message = record.getMessage()

        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"

        return f"{prefix} | {message}"


# ==============================================================================
# SETTINGS
# ==============================================================================

@dataclass(frozen=True, slots=True)
class LoggingConfig:
    """
    Immutable logging configuration.
    """

    level: str = DEFAULT_LOG_LEVEL
    json_logs: bool = True
    enable_otel_context: bool = True
    logger_name: str = DEFAULT_LOGGER_NAME
    stream: Any = DEFAULT_STREAM
    propagate: bool = False


# ==============================================================================
# CONTEXT API
# ==============================================================================

def set_correlation_id(value: str | None) -> None:
    correlation_id_var.set(value)


def set_trace_context(trace_id: str | None, span_id: str | None) -> None:
    trace_id_var.set(trace_id)
    span_id_var.set(span_id)


def set_chain_id(value: str | None) -> None:
    chain_id_var.set(value)


def set_component(value: str | None) -> None:
    component_var.set(value)


def clear_log_context() -> None:
    correlation_id_var.set(None)
    trace_id_var.set(None)
    span_id_var.set(None)
    chain_id_var.set(None)
    component_var.set(None)


# ==============================================================================
# LOGGER ADAPTER
# ==============================================================================

class A01LoggerAdapter(logging.LoggerAdapter):
    """
    LoggerAdapter that injects standard A01 context fields.
    """

    def process(self, msg: Any, kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        extra = kwargs.get("extra", {})
        if not isinstance(extra, dict):
            extra = {}

        extra.setdefault("correlation_id", correlation_id_var.get())
        extra.setdefault("trace_id", trace_id_var.get())
        extra.setdefault("span_id", span_id_var.get())
        extra.setdefault("chain_id", chain_id_var.get())
        extra.setdefault("component", component_var.get())

        kwargs["extra"] = extra
        return msg, kwargs


# ==============================================================================
# CONFIGURATION
# ==============================================================================

def _build_handler(config: LoggingConfig) -> logging.Handler:
    handler = logging.StreamHandler(config.stream)
    handler.addFilter(ContextFilter())
    if config.json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter())
    return handler


def configure_logging(config: LoggingConfig | None = None) -> None:
    """
    Configure application logging.

    This is the application entrypoint for logging setup.
    """
    config = config or LoggingConfig()

    level = getattr(logging, config.level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    handler = _build_handler(config)
    root_logger.addHandler(handler)

    # Reduce noise from noisy third-party libraries unless application overrides.
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("web3").setLevel(logging.INFO)

    # Optional: enrich with current OpenTelemetry trace/span once at setup time.
    if config.enable_otel_context:
        trace_id, span_id = _extract_otel_context()
        if trace_id or span_id:
            set_trace_context(trace_id, span_id)


# ==============================================================================
# LOGGER FACTORY
# ==============================================================================

def get_logger(
    name: str | None = None,
    *,
    component: str | None = None,
) -> A01LoggerAdapter:
    """
    Return a logger adapter with standard A01 context.
    """
    logger_name = name or DEFAULT_LOGGER_NAME
    logger = logging.getLogger(logger_name)

    if component is not None:
        set_component(component)

    return A01LoggerAdapter(logger, {})


# ==============================================================================
# AUDIT LOGGING
# ==============================================================================

def audit_event(
    logger: logging.Logger | A01LoggerAdapter,
    event: str,
    *,
    details: Mapping[str, Any] | None = None,
    level: int = logging.INFO,
) -> None:
    """
    Emit an audit-style structured log message.
    """
    payload = {
        "event": event,
        "details": dict(details or {}),
    }
    logger.log(level, event, extra={"extra": payload})


# ==============================================================================
# EXPORTS
# ==============================================================================

__all__ = [
    "LoggingConfig",
    "JsonFormatter",
    "TextFormatter",
    "ContextFilter",
    "A01LoggerAdapter",
    "configure_logging",
    "get_logger",
    "set_correlation_id",
    "set_trace_context",
    "set_chain_id",
    "set_component",
    "clear_log_context",
    "audit_event",
]