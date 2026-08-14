"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    interfaces.rest

Purpose:
    A read-only HTTP surface over :class:`IntelligenceService`.

Design goals:
    - Loopback by default; a public bind must be asked for explicitly
    - GET only, because there is nothing here to mutate
    - Every route delegates; no logic lives in the transport
    - Errors as JSON with a sane status, never a traceback
    - Standard library only, so the API adds no dependency

Notes:
    Built on ``http.server`` rather than a framework. A01's dependency policy is
    free-first and the API is a handful of read-only routes over a facade that
    already exists, so a framework would add a supply-chain surface and a
    version to track in exchange for routing sugar. ``ThreadingHTTPServer``
    handles concurrent readers, which is the whole concurrency requirement:
    SQLite in WAL mode serves readers while the operator's ingestion writes.

    **The bind address is the security boundary.** There is no authentication
    here, because A01 has no user model and inventing one badly is worse than
    not having it. An unauthenticated service on ``0.0.0.0`` publishes whatever
    the operator has ingested to the network. So the default is ``127.0.0.1``,
    and :func:`serve` logs a warning naming the exposure when asked for anything
    else — the operator can still do it, and cannot do it without being told.

    Only GET is routed. A01 is read-only by architecture, and the ingestion
    write path is deliberately unexposed: a POST that triggered a fetch would
    put an unbounded, rate-limited, externally-triggered job behind a request.
"""

from __future__ import annotations

import json
import logging

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Final
from urllib.parse import parse_qs, urlparse

from .service import IntelligenceService, ServiceResult

logger = logging.getLogger(__name__)

#: Loopback. Changing this default would expose an unauthenticated service.
DEFAULT_HOST: Final[str] = "127.0.0.1"
DEFAULT_PORT: Final[int] = 8801

#: Cap on a request line's query, so a malformed client cannot force a large
#: parse. Generous for the parameters these routes actually take.
MAX_QUERY_LENGTH: Final[int] = 2_048


def _first(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    return values[0] if values else None


class Router:
    """
    Maps a path to a handler over the service.

    Exact-match only. A path template language would be the first piece of
    framework to reimplement, and these routes take their arguments from the
    query string.
    """

    def __init__(self, service: IntelligenceService) -> None:
        self._service = service
        self._routes: dict[str, Callable[[dict[str, list[str]]], ServiceResult]] = {
            "/health": lambda _: service.health(),
            "/detectors": lambda _: service.detectors(),
            "/skills": lambda _: service.skills(),
            "/metrics": lambda _: service.metrics(),
            # What A01 can observe, before a caller asks it to observe anything.
            # Served from the measured capability table rather than a live
            # probe: fifteen chains behind one request would make a status page
            # into a load generator.
            "/chains": lambda _: service.chains(),
            "/labels": lambda q: service.labels(chain=_first(q, "chain") or ""),
            "/flows": lambda q: service.flows(
                chain=_first(q, "chain") or "ethereum"
            ),
            "/coverage": lambda q: service.coverage(
                chain=_first(q, "chain") or "ethereum"
            ),
            "/investigate": lambda q: service.investigate(
                chain=_first(q, "chain") or "ethereum",
                address=_first(q, "address"),
            ),
        }

    @property
    def service(self) -> IntelligenceService:
        return self._service

    def paths(self) -> tuple[str, ...]:
        return tuple(sorted(self._routes))

    def dispatch(self, path: str, params: dict[str, list[str]]) -> ServiceResult:
        handler = self._routes.get(path.rstrip("/") or "/health")
        if handler is None:
            return ServiceResult.failure(
                f"no such route: {path}; available: {', '.join(self.paths())}",
                status=HTTPStatus.NOT_FOUND,
            )
        try:
            return handler(params)
        except Exception as exc:  # noqa: BLE001 - transport boundary
            # The last line of defence. A traceback reaching a client is both an
            # information disclosure and a useless response; it belongs in the
            # log, where the operator can see it.
            logger.exception("unhandled error serving %s", path)
            return ServiceResult.failure(
                f"internal error handling {path}",
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )


class _Handler(BaseHTTPRequestHandler):
    """Request handler. Holds no logic beyond decoding and encoding."""

    router: Router
    server_version = "A01/1.0"
    #: Suppress the Python version banner; it tells a scanner what to try.
    sys_version = ""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)

        if len(parsed.query) > MAX_QUERY_LENGTH:
            self._respond(
                ServiceResult.failure(
                    "query string too long", status=HTTPStatus.REQUEST_URI_TOO_LONG
                )
            )
            return

        params = parse_qs(parsed.query)
        self._respond(self.router.dispatch(parsed.path, params))

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        """
        Refused, always.

        A01 is read-only by architecture. Answering 405 rather than 404 states
        that the resource exists and mutation is not offered, which is the
        accurate thing to say.
        """
        self._respond(
            ServiceResult.failure(
                "A01 is read-only; no endpoint accepts a write",
                status=HTTPStatus.METHOD_NOT_ALLOWED,
            )
        )

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST

    # -- plumbing ---------------------------------------------------------

    def _respond(self, result: ServiceResult) -> None:
        body = json.dumps(result.as_dict(), indent=2, default=str).encode("utf-8")

        self.send_response(int(result.status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # No caching: a coverage or health answer that is minutes stale is
        # misleading in exactly the way this system tries not to be.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Route access logs through logging instead of stderr."""
        logger.info("%s - %s", self.address_string(), format % args)


def build_server(
    service: IntelligenceService,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> ThreadingHTTPServer:
    """
    Construct the server without starting it.

    Separated from :func:`serve` so a test can bind an ephemeral port, make
    requests, and shut down without a signal handler or a sleep.
    """
    if host not in {"127.0.0.1", "localhost", "::1"}:
        logger.warning(
            "binding %s: A01's REST API is unauthenticated, so this publishes "
            "all ingested data to anything that can reach the interface",
            host,
        )

    router = Router(service)
    handler = type("_BoundHandler", (_Handler,), {"router": router})
    return ThreadingHTTPServer((host, port), handler)


def serve(
    service: IntelligenceService | None = None,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    database_path: str | None = None,
) -> None:
    """Run the API until interrupted."""
    active = service or IntelligenceService(database_path=database_path)
    server = build_server(active, host=host, port=port)

    logger.info("A01 REST API listening on http://%s:%d", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("shutting down")
    finally:
        server.shutdown()
        server.server_close()


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "MAX_QUERY_LENGTH",
    "Router",
    "build_server",
    "serve",
]
