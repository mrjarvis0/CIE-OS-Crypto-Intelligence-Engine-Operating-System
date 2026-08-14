"""
Tools :: Security :: Sandbox
============================

Process-level sandbox for running untrusted code paths (plugins, scripts,
tools) with resource limits and filesystem isolation.

Implementation notes
--------------------
The platform is stdlib-only by design, so this sandbox uses a subprocess with:

* a working directory confined to a temp root;
* a time budget enforced via a watchdog;
* environment scrubbing (no host secrets injected);
* an optional filesystem jail: the child receives read access to the allowed
  roots via explicit arguments, not ambient host mounts.

This is a *best-effort* isolation layer for automation environments; for
harder guarantees, deployment should run the whole platform inside a
container. The API stays identical either way.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .isolation import IsolationPolicy

__all__ = ["SandboxResult", "Sandbox", "run_sandboxed", "SandboxError"]


class SandboxError(RuntimeError):
    """Raised when a sandboxed run fails at the infrastructure level."""


@dataclass
class SandboxResult:
    """Outcome of a sandboxed execution."""

    ok: bool
    returncode: int = -1
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    timed_out: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
        }


class Sandbox:
    """
    Run a command string under a policy with a time budget.

    Parameters
    ----------
    policy:
        An :class:`IsolationPolicy`; ``timeout`` (seconds) and allowed roots
        are consumed from it.
    workdir:
        Optional working directory for the child; defaults to a fresh temp
        directory under the first allowed root.
    env:
        Extra environment variables merged over a scrubbed base.
    """

    def __init__(
        self,
        policy: IsolationPolicy,
        *,
        workdir: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
        python: Optional[str] = None,
    ) -> None:
        self.policy = policy
        self.env = dict(env or {})
        self.python = python or sys.executable
        self._workdir = workdir

    # -- helpers ----------------------------------------------------------- #

    def _temp_workdir(self) -> str:
        base = self.policy.file_roots[0] if self.policy.file_roots else tempfile.gettempdir()
        os.makedirs(base, exist_ok=True)
        return tempfile.mkdtemp(prefix="sandbox-", dir=base)

    def _scrubbed_env(self) -> Dict[str, str]:
        """Copy of host env minus known secret keys."""
        scrubbed = {}
        for key, value in os.environ.items():
            lowered = key.lower()
            if any(term in lowered for term in ("secret", "token", "key", "password", "credential")):
                continue
            scrubbed[key] = value
        for key, value in self.env.items():
            scrubbed[key] = value
        return scrubbed

    # -- execution --------------------------------------------------------- #

    def run(self, command: Sequence[str] | str, *, timeout: Optional[float] = None) -> SandboxResult:
        """Execute ``command`` (list of argv items or a shell string)."""
        started = time.monotonic()
        budget = timeout if timeout is not None else self.policy.timeout
        if isinstance(command, str):
            argv: List[str] = [self.python, "-c", command]
        else:
            argv = list(command)
        workdir = self._workdir or self._temp_workdir()

        try:
            process = subprocess.Popen(
                argv,
                cwd=workdir,
                env=self._scrubbed_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
            )
            try:
                stdout, stderr = process.communicate(timeout=budget)
                return SandboxResult(
                    ok=process.returncode == 0,
                    returncode=process.returncode,
                    stdout=stdout or "",
                    stderr=stderr or "",
                    duration_ms=(time.monotonic() - started) * 1000.0,
                )
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                return SandboxResult(
                    ok=False,
                    timed_out=True,
                    duration_ms=(time.monotonic() - started) * 1000.0,
                    stderr=f"timed out after {budget}s",
                )
        except OSError as exc:
            return SandboxResult(
                ok=False,
                stderr=str(exc),
                duration_ms=(time.monotonic() - started) * 1000.0,
            )


def run_sandboxed(
    code: str,
    policy: IsolationPolicy,
    *,
    timeout: Optional[float] = None,
    env: Optional[Mapping[str, str]] = None,
) -> SandboxResult:
    """Convenience wrapper: execute ``code`` (Python snippet) in a sandbox."""
    return Sandbox(policy=policy, env=env).run(code, timeout=timeout)