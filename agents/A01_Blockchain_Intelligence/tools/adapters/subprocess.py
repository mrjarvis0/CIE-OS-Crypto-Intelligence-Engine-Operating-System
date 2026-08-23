"""
Tools :: Adapters :: Subprocess Adapter
========================================

Low-level execution of external programs through the unified adapter contract.

Capabilities:
    * process creation with argument lists or shell commands
    * custom environment variables and working directory
    * user-supplied stdin
    * signal handling (SIGTERM / SIGKILL on timeout, graceful on Windows)
    * exit-code processing and error translation
    * synchronous timeout enforcement via a watchdog thread
    * (optional) streaming of stdout/stderr line by line

Note: this adapter performs *no* allow-list gating. For operator-approved
binaries use :class:`tools.adapters.cli.CLIAdapter`, which layers the security
boundary on top of this class.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from typing import Any, Dict, Iterable, Optional

from . import (
    AdapterConnectionError,
    AdapterError,
    AdapterExecutionError,
    AdapterRequest,
    AdapterResponse,
    AdapterTimeoutError,
    AdapterValidationError,
    BaseAdapter,
)

__all__ = ["SubprocessAdapter", "register"]


def register(**options: Any) -> "SubprocessAdapter":
    """Factory used by :func:`adapters.get_adapter`."""
    return SubprocessAdapter(**options)


class SubprocessAdapter(BaseAdapter):
    """Execute external programs and capture their output."""

    transport = "subprocess"

    def __init__(
        self,
        *,
        timeout: float = 60.0,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        shell: bool = False,
        input_encoding: str = "utf-8",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.default_timeout = timeout
        self.base_env = dict(env or {})
        self.default_cwd = cwd
        self.shell = shell
        self.input_encoding = input_encoding

    def connect(self, **options: Any) -> "SubprocessAdapter":
        """Subprocesses are transient; nothing to keep open."""
        self._connected = True
        return self

    def _terminate(self, proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        if sys.platform == "win32":
            proc.terminate()
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()

    def _spawn(self, params: Dict[str, Any]) -> subprocess.Popen:
        argv: Any = params.get("argv") or params.get("args") or params.get("command")
        if argv is None:
            raise AdapterValidationError(
                "params['argv'] (command list) is required", transport=self.transport
            )
        command: Any = argv if isinstance(argv, str) else [str(a) for a in argv]

        env = {**os.environ, **self.base_env, **dict(params.get("env", {}))}
        cwd = params.get("cwd") or self.default_cwd
        use_shell = bool(params.get("shell") or self.shell)
        stdin_text = params.get("stdin") or ""

        try:
            start_new_session = sys.platform != "win32"
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE if stdin_text else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=cwd,
                shell=use_shell,
                text=True,
                encoding=self.input_encoding,
                errors="replace",
                start_new_session=start_new_session,
            )
        except (OSError, ValueError) as exc:
            raise AdapterExecutionError(
                f"failed to start process {command!r}: {exc}",
                transport=self.transport,
            ) from exc
        return proc

    def execute(self, request: AdapterRequest) -> AdapterResponse:
        self.validate_request(request)
        method = (request.method or "run").lower()
        if method == "ping":
            return self.normalize_response(True, data="pong", method="ping")
        if method not in ("run", "exec"):
            return self.normalize_response(
                False,
                error=AdapterValidationError(
                    f"unsupported method {method!r}; expected 'run' or 'ping'",
                    transport=self.transport,
                ),
                method=method,
            )

        params = request.params or {}
        try:
            proc = self._spawn(params)
        except AdapterValidationError as exc:
            return self.normalize_response(False, error=exc, method=method)

        timeout = float(params.get("timeout") or request.timeout or self.default_timeout)
        stdin_text = params.get("stdin") or ""

        result: Dict[str, Any] = {}
        error: Optional[BaseException] = None
        watch_dogged = False

        def _communicate() -> None:
            nonlocal result, error
            try:
                out, err = proc.communicate(input=(stdin_text or None), timeout=timeout + 5)
                result = {"stdout": out, "stderr": err, "returncode": proc.returncode}
            except subprocess.TimeoutExpired as exc:
                error = AdapterTimeoutError(
                    f"process exceeded {timeout}s timeout", transport=self.transport
                )
                proc.kill()
                try:
                    proc.communicate(timeout=5)
                except Exception:  # noqa: BLE001 - best-effort cleanup
                    pass
            except BaseException as exc:  # noqa: BLE001 - translated below
                error = exc

        thread = threading.Thread(
            target=_communicate, name=f"subproc-{proc.pid}", daemon=True
        )
        thread.start()

        # Watchdog enforcing the strict caller timeout.
        thread.join(timeout=timeout)
        if thread.is_alive():
            watch_dogged = True
            self._terminate(proc)
            thread.join(timeout=5)
            outcome = {
                "stdout": "",
                "stderr": "<terminated on timeout>",
                "returncode": -9,
            }
        else:
            outcome = result

        if error is not None:
            return self.normalize_response(
                False,
                error=error,
                method=method,
                request_id=request.request_id,
            )

        if watch_dogged:
            # The watchdog had to kill the process: report a timeout even if the
            # worker thread completed normally with a non-zero exit after kill.
            to_err = AdapterTimeoutError(
                f"process exceeded {timeout}s timeout",
                transport=self.transport,
                request_id=request.request_id,
            )
            return self.normalize_response(
                False,
                data={
                    "returncode": outcome.get("returncode", -9),
                    "stdout": outcome.get("stdout", ""),
                    "stderr": outcome.get("stderr", ""),
                    "success": False,
                },
                error=to_err,
                method=method,
                request_id=request.request_id,
            )

        returncode = outcome.get("returncode")
        ok = returncode == 0
        data = {
            "returncode": returncode,
            "stdout": outcome.get("stdout", ""),
            "stderr": outcome.get("stderr", ""),
            "success": ok,
        }
        if not ok:
            err = AdapterExecutionError(
                f"process exited with code {returncode}",
                transport=self.transport,
                request_id=request.request_id,
            )
            return self.normalize_response(
                False, data=data, error=err, method=method, request_id=request.request_id
            )
        return self.normalize_response(
            True, data=data, method=method, request_id=request.request_id
        )

    def stream(self, request: AdapterRequest) -> Iterable[str]:
        """Stream stdout lines as they are produced."""
        self.validate_request(request)
        params = request.params or {}
        try:
            proc = self._spawn(params)
        except AdapterError as exc:
            raise exc
        if proc.stdout is None:  # pragma: no cover - stdout is always PIPE here
            raise AdapterExecutionError(
                "process was started without stdout capture",
                transport=self.transport,
            )
        try:
            for line in proc.stdout:
                yield line.rstrip("\n")
            proc.wait()
        except OSError as exc:
            raise AdapterConnectionError(
                f"process pipe closed unexpectedly: {exc}", transport=self.transport
            ) from exc
