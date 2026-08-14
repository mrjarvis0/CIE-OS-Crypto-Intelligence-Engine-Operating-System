"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    blockchain.transport.dispatch

Purpose:
    Turn "read this from this chain" into an actual request against a live
    endpoint, and report honestly when it cannot.

Design goals:
    - One place where a chain read happens
    - Endpoint health drives selection; failures feed back
    - Budget and cache consulted before the network
    - Missing capability reported, never worked around
    - Provenance on every result

Notes:
    The distinction this module exists to preserve is between "the chain says
    no" and "A01 could not ask". Both arrive as an empty result, and the
    evidence standard treats them completely differently: the first is a
    finding, the second is an absence of data that must not be reported as a
    finding. So a call that fails, is throttled, or needs archive access that
    no available endpoint provides returns a CallResult marked undetermined
    with a reason, rather than an empty list that reads like a clean negative.

    Capability is checked before dispatch rather than after failure. A
    non-archive endpoint asked for historical state does not always error --
    some return the latest value, which is a wrong answer wearing the costume
    of a right one.

    **Spend is reported, not recorded.** A provider's day/month allowance is
    ledgered in ``pipeline.budget``, which is storage, and the transport must
    not grow a storage dependency to reach it. So this module counts what it
    actually sent, per provider, and hands the count to a callable the caller
    supplies. The transport knows how many requests left the process; the
    caller knows where that fact belongs.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Final, Mapping, Sequence

from config.rpc.chains import ChainName, get_chain
from config.rpc.rpc_config import build_default_rpc_registry
from config.rpc.rpc_manager import RpcManager
from tools.adapters import AdapterRequest
from tools.adapters.rest import RESTAdapter
from tools.adapters.rpc import RPCAdapter

from ..providers import Endpoint, Protocol, ProviderCatalog, ProviderRole, default_catalog
from ..rate_limit.bucket import RateLimiter
from .cache import ResponseCache, Volatility, cache_key, resolve_volatility

logger = logging.getLogger(__name__)

#: Endpoints tried for one logical read before giving up.
DEFAULT_MAX_ATTEMPTS: Final[int] = 3

_JSON_RPC_PROTOCOLS: Final[frozenset[Protocol]] = frozenset(
    {Protocol.EVM_JSON_RPC, Protocol.SOLANA_JSON_RPC}
)

#: Called as ``sink(chain, provider, calls)`` once per provider that actually
#: received a request during one logical read.
#:
#: Deliberately three primitives rather than a budget object: the type is what
#: keeps the transport free of a storage import, and a signature made of
#: strings and an int cannot quietly acquire one.
SpendSink = Callable[[str, str, int], None]


class Outcome(StrEnum):
    """Why a call ended the way it did."""

    OK = "ok"
    CACHED = "cached"
    #: No endpoint offers the capability the call requires.
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    #: Every candidate endpoint is throttled or out of budget.
    BUDGET_EXHAUSTED = "budget_exhausted"
    #: Endpoints existed and all of them failed.
    ALL_ENDPOINTS_FAILED = "all_endpoints_failed"
    #: The chain has no usable endpoint at all.
    NO_ENDPOINT = "no_endpoint"
    #: The provider answered, and its answer was an error.
    PROVIDER_ERROR = "provider_error"


@dataclass(frozen=True, slots=True)
class CallResult:
    """
    The result of one chain read, with enough provenance to cite it.

    ``determined`` is the field that matters. False means A01 did not learn
    the answer, which is not the same as learning that the answer is empty.
    Callers that collapse the two produce a confident negative out of a
    network failure.
    """

    outcome: Outcome
    value: Any = None
    provider: str = ""
    endpoint_url: str = ""
    chain: str = ""
    method: str = ""
    duration_ms: float = 0.0
    attempts: int = 0
    from_cache: bool = False
    reason: str = ""
    #: Providers tried and the error each gave, for doctor and for triage.
    failures: tuple[tuple[str, str], ...] = ()
    #: Requests that actually left the process, per provider.
    #:
    #: Not derivable from ``failures``: that list also holds candidates skipped
    #: because the local limiter refused them, and a request that was never
    #: sent costs the provider nothing. Summing this gives ``attempts``.
    provider_attempts: tuple[tuple[str, int], ...] = ()

    @property
    def determined(self) -> bool:
        """True only when A01 actually obtained the answer."""
        return self.outcome in {Outcome.OK, Outcome.CACHED}

    @property
    def ok(self) -> bool:
        return self.determined

    def provenance(self) -> dict[str, Any]:
        """
        Provenance record for an evidence artifact.

        Never includes the endpoint URL: a keyed URL carries the credential in
        its path, and evidence records are written to disk and rendered into
        reports. The provider name is the citable identity.
        """
        return {
            "source": self.provider,
            "chain": self.chain,
            "method": self.method,
            "outcome": self.outcome.value,
            "from_cache": self.from_cache,
            "attempts": self.attempts,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "determined": self.determined,
            "provider": self.provider,
            "chain": self.chain,
            "method": self.method,
            "duration_ms": round(self.duration_ms, 2),
            "attempts": self.attempts,
            "from_cache": self.from_cache,
            "reason": self.reason,
            "failures": [{"provider": p, "error": e} for p, e in self.failures],
            "provider_attempts": dict(self.provider_attempts),
        }


@dataclass(slots=True)
class _Attempt:
    """Bookkeeping for one endpoint try."""

    endpoint: Endpoint
    url: str


class ChainDispatcher:
    """
    Executes chain reads across the provider catalog.

    Owns the retry loop deliberately rather than delegating to RPCAdapter's
    built-in failover. The adapter would rotate endpoints blind, so a dead
    provider would be retried on every future call; routing each attempt at
    exactly one endpoint is what lets success and failure be recorded against
    that endpoint and the circuit breaker actually open.
    """

    def __init__(
        self,
        *,
        catalog: ProviderCatalog | None = None,
        rpc_manager: RpcManager | None = None,
        limiter: RateLimiter | None = None,
        cache: ResponseCache | None = None,
        environ: Mapping[str, str] | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        verify_ssl: bool = True,
        on_spend: SpendSink | None = None,
    ) -> None:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be > 0")

        self._catalog = catalog or default_catalog()
        self._environ = environ
        self._max_attempts = max_attempts
        self._verify_ssl = verify_ssl
        self._on_spend = on_spend

        self._limiter = limiter if limiter is not None else RateLimiter()
        self._cache = cache if cache is not None else ResponseCache()

        if rpc_manager is None:
            registry = build_default_rpc_registry(
                overrides=self._catalog.rpc_overrides(self._environ)
            )
            rpc_manager = RpcManager(rpc_registry=registry)
        self._rpc = rpc_manager

        #: One adapter per endpoint URL, so HTTP connections are reused.
        self._adapters: dict[str, RPCAdapter | RESTAdapter] = {}

        #: Latest known head per chain, used to decide whether a block-pinned
        #: read is deep enough to be immutable.
        self._head_blocks: dict[str, int] = {}

        for endpoint in self._catalog.endpoints:
            self._limiter.register(endpoint.provider, endpoint.rate_limit_per_minute)

    # -- accessors -------------------------------------------------------

    @property
    def catalog(self) -> ProviderCatalog:
        return self._catalog

    @property
    def cache(self) -> ResponseCache:
        return self._cache

    @property
    def limiter(self) -> RateLimiter:
        return self._limiter

    @property
    def rpc_manager(self) -> RpcManager:
        return self._rpc

    # -- capability ------------------------------------------------------

    def supports_archive(self, chain: ChainName | str) -> bool:
        """Whether historical state is reachable on this chain right now."""
        return bool(
            self._catalog.available(chain, require_archive=True, environ=self._environ)
        )

    def capability_report(self, chain: ChainName | str) -> dict[str, Any]:
        """
        What this chain can and cannot answer, and what would fix it.

        Detectors consult this to decide between running and declining, so it
        names the missing credential rather than only reporting the gap.
        """
        available = self._catalog.available(chain, environ=self._environ)
        archive = self._catalog.available(chain, require_archive=True, environ=self._environ)
        logs = self._catalog.available(chain, require_logs=True, environ=self._environ)

        report: dict[str, Any] = {
            "chain": str(chain),
            "endpoints": len(available),
            "archive": bool(archive),
            "logs": bool(logs),
            "reachable": bool(available),
        }
        if not archive:
            dormant = [
                entry
                for entry in self._catalog.dormant_providers(self._environ)
                if entry["unlocks_archive"]
            ]
            report["archive_blocked_by"] = "no archive endpoint available"
            report["archive_unlocked_by"] = [entry["env_var"] for entry in dormant[:3]]
        return report

    # -- dispatch --------------------------------------------------------

    def call(
        self,
        chain: ChainName | str,
        method: str,
        params: Any = None,
        *,
        require_archive: bool = False,
        require_logs: bool = False,
        timeout: float | None = None,
        use_cache: bool = True,
    ) -> CallResult:
        """
        Execute one chain read.

        Never raises for an expected failure. A caller that has to distinguish
        "no result" from "could not ask" cannot do so through an exception
        that looks identical to a bug, so every outcome comes back as a
        CallResult.
        """
        chain_name = chain.value if isinstance(chain, ChainName) else str(chain)
        params = [] if params is None else params
        started = time.monotonic()

        key = cache_key(chain_name, method, params)
        if use_cache:
            found, value = self._cache.get(key)
            if found:
                return CallResult(
                    outcome=Outcome.CACHED,
                    value=value,
                    provider=self._cache.provider_for(key) or "cache",
                    chain=chain_name,
                    method=method,
                    duration_ms=(time.monotonic() - started) * 1000.0,
                    from_cache=True,
                )

        candidates = self._catalog.available(
            chain,
            require_archive=require_archive,
            require_logs=require_logs,
            environ=self._environ,
        )

        if not candidates:
            return self._unavailable(
                chain_name, method, started, require_archive, require_logs
            )

        result = self._dispatch(
            chain_name, method, params, candidates, key, started, timeout, use_cache
        )
        self._report_spend(result)
        return result

    def _report_spend(self, result: CallResult) -> None:
        """
        Tell the caller's sink what this read cost, per provider.

        On the return path rather than before each request, so one logical read
        is one ledger write per provider instead of one per endpoint try. The
        cost of that choice is a process killed mid-flight: those requests
        reached the provider and are never counted. The cost of the alternative
        is a write on the hot path of every retry, and the undercount is
        bounded by one read rather than unbounded by a crash loop.

        A sink that raises must not turn an answered chain read into a failed
        one -- the answer is already in hand, and losing it to a bookkeeping
        error would be the worse trade. It is logged rather than swallowed,
        because a ledger that silently stops recording reports headroom that
        does not exist.
        """
        if self._on_spend is None:
            return
        for provider, calls in result.provider_attempts:
            try:
                self._on_spend(result.chain, provider, calls)
            except Exception:  # noqa: BLE001 - see docstring
                logger.exception(
                    "spend sink failed for %s (%d call(s) on %s); "
                    "the ledger is now short by that much",
                    provider,
                    calls,
                    result.chain,
                )

    def _unavailable(
        self,
        chain_name: str,
        method: str,
        started: float,
        require_archive: bool,
        require_logs: bool,
    ) -> CallResult:
        """Build the result for a call no endpoint can serve."""
        any_endpoint = self._catalog.available(chain_name, environ=self._environ)
        duration = (time.monotonic() - started) * 1000.0

        if not any_endpoint:
            return CallResult(
                outcome=Outcome.NO_ENDPOINT,
                chain=chain_name,
                method=method,
                duration_ms=duration,
                reason=f"no usable endpoint catalogued for {chain_name}",
            )

        missing = "archive" if require_archive else "log-range" if require_logs else "requested"
        report = self.capability_report(chain_name)
        unlocks = report.get("archive_unlocked_by") or []
        hint = f"; set one of {', '.join(unlocks)}" if unlocks and require_archive else ""

        return CallResult(
            outcome=Outcome.CAPABILITY_UNAVAILABLE,
            chain=chain_name,
            method=method,
            duration_ms=duration,
            reason=(
                f"{chain_name} is reachable but no available endpoint offers "
                f"{missing} access{hint}"
            ),
        )

    def _dispatch(
        self,
        chain_name: str,
        method: str,
        params: Any,
        candidates: Sequence[Endpoint],
        key: str,
        started: float,
        timeout: float | None,
        use_cache: bool,
    ) -> CallResult:
        """Try candidates in order until one answers."""
        failures: list[tuple[str, str]] = []
        # Insertion-ordered so the report reads in the order the providers were
        # tried, which is also the order the catalog prefers them.
        sent: dict[str, int] = {}
        attempts = 0
        throttled = 0

        for endpoint in candidates:
            if attempts >= self._max_attempts:
                break

            url = endpoint.render_url(self._environ)
            if url is None:  # pragma: no cover - available() already filtered
                continue

            if not self._limiter.try_acquire(endpoint.provider):
                throttled += 1
                failures.append(
                    (
                        endpoint.provider,
                        f"rate limited locally, {self._limiter.wait_time(endpoint.provider):.1f}s",
                    )
                )
                continue

            attempts += 1
            # Counted here, before the response is known. The provider meters
            # the request on arrival, so a call that then times out has still
            # been spent, and counting only what succeeded would undercount
            # precisely during the 429 storms that burn the most allowance.
            sent[endpoint.provider] = sent.get(endpoint.provider, 0) + 1
            response = self._execute(endpoint, url, method, params, timeout)

            if response.ok:
                self._rpc.record_success(chain_name, url)
                self._note_head(chain_name, method, response.data)

                if use_cache:
                    volatility = self._volatility(chain_name, method, params)
                    self._cache.put(key, response.data, volatility, provider=endpoint.provider)

                return CallResult(
                    outcome=Outcome.OK,
                    value=response.data,
                    provider=endpoint.provider,
                    endpoint_url=url,
                    chain=chain_name,
                    method=method,
                    duration_ms=(time.monotonic() - started) * 1000.0,
                    attempts=attempts,
                    failures=tuple(failures),
                    provider_attempts=tuple(sent.items()),
                )

            message = str(response.error) if response.error else "unknown error"
            failures.append((endpoint.provider, message))

            if self._is_throttle(message):
                # The provider's own 429 outranks its documented ceiling.
                self._limiter.penalise(endpoint.provider)
            self._rpc.record_failure(chain_name, url)

        duration = (time.monotonic() - started) * 1000.0

        if attempts == 0 and throttled:
            # Nothing left the process, so nothing is owed. This is the one
            # outcome that must never reach the ledger: charging for a call the
            # local limiter refused would make throttling look like usage and
            # close the budget on a chain that was never read.
            return CallResult(
                outcome=Outcome.BUDGET_EXHAUSTED,
                chain=chain_name,
                method=method,
                duration_ms=duration,
                reason=f"all {throttled} candidate providers are rate limited",
                failures=tuple(failures),
            )

        return CallResult(
            outcome=Outcome.ALL_ENDPOINTS_FAILED,
            chain=chain_name,
            method=method,
            duration_ms=duration,
            attempts=attempts,
            reason=f"{attempts} endpoint(s) tried, none answered",
            failures=tuple(failures),
            provider_attempts=tuple(sent.items()),
        )

    # -- execution -------------------------------------------------------

    def _execute(
        self,
        endpoint: Endpoint,
        url: str,
        method: str,
        params: Any,
        timeout: float | None,
    ) -> Any:
        """Dispatch to the adapter matching the endpoint's protocol."""
        effective_timeout = timeout or float(endpoint.timeout_seconds)
        adapter = self._adapter_for(endpoint, url)

        if endpoint.protocol in _JSON_RPC_PROTOCOLS:
            request = AdapterRequest(
                method=method,
                params={"params": params},
                timeout=effective_timeout,
                retries=0,  # failover is this class's job, not the adapter's
            )
        else:
            # REST endpoints address a path and query, not a JSON-RPC method.
            request = AdapterRequest(
                method="GET",
                path=method,
                params=dict(params) if isinstance(params, Mapping) else {},
                timeout=effective_timeout,
                retries=0,
            )

        try:
            return adapter.execute(request)
        except Exception as exc:  # pragma: no cover - adapters normalize their own
            logger.warning("adapter raised for %s: %s", endpoint.provider, exc)

            class _Failed:
                ok = False
                data = None
                error = exc

            return _Failed()

    def _adapter_for(self, endpoint: Endpoint, url: str) -> RPCAdapter | RESTAdapter:
        """One cached adapter per URL, so connections are reused."""
        adapter = self._adapters.get(url)
        if adapter is not None:
            return adapter

        headers = {
            "Accept": "application/json",
            "User-Agent": "CIE-OS-A01/1.0.0",
            **endpoint.auth_headers(self._environ),
        }

        if endpoint.protocol in _JSON_RPC_PROTOCOLS:
            adapter = RPCAdapter(
                url=url,
                headers=headers,
                verify_ssl=self._verify_ssl,
                default_timeout=float(endpoint.timeout_seconds),
                max_retries=0,
            )
        else:
            adapter = RESTAdapter(
                base_url=url,
                headers=headers,
                verify_ssl=self._verify_ssl,
                default_timeout=float(endpoint.timeout_seconds),
                max_retries=0,
            )

        self._adapters[url] = adapter
        return adapter

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _is_throttle(message: str) -> bool:
        lowered = message.lower()
        return "429" in lowered or "too many requests" in lowered or "rate limit" in lowered

    def _note_head(self, chain_name: str, method: str, data: Any) -> None:
        """Track the chain head so block-pinned reads can be judged final."""
        if method != "eth_blockNumber" or not isinstance(data, str):
            return
        try:
            self._head_blocks[chain_name] = int(data, 16)
        except ValueError:  # pragma: no cover - malformed provider response
            pass

    def _volatility(self, chain_name: str, method: str, params: Any) -> Volatility:
        try:
            confirmations = get_chain(chain_name).confirmations
        except (KeyError, ValueError):  # pragma: no cover - unknown chain
            confirmations = 12
        return resolve_volatility(
            method,
            params,
            head_block=self._head_blocks.get(chain_name),
            confirmations=confirmations,
        )

    # -- reporting -------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Combined transport health, for doctor."""
        return {
            "cache": self._cache.snapshot(),
            "rate_limits": self._limiter.snapshot(),
            "throttled": list(self._limiter.throttled_providers()),
            "endpoints": self._rpc.health_report(),
        }


__all__ = [
    "Outcome",
    "CallResult",
    "ChainDispatcher",
    "SpendSink",
    "DEFAULT_MAX_ATTEMPTS",
]
