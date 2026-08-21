"""
Tools :: Security :: Sandbox

Subprocess runner for untrusted code paths (plugins, scripts, tools), with a
time budget, a confined working directory and a scrubbed environment.

What this actually enforces
---------------------------
* **A time budget.** The child is killed when it overruns.
* **A working directory** under one of the policy's ``file_roots``.
* **An environment allow-list.** The child sees a named set of variables and
  nothing else.

What it does **not** enforce -- read this before trusting it
------------------------------------------------------------
The child is an ordinary OS process. It can read and write any path its user
can reach, and it can open any socket. ``cwd`` sets where relative paths
start; it is not a jail. So ``IsolationPolicy.file_roots`` and ``.hosts``
constrain *this module's own* decisions -- which directory it creates, what
:func:`~tools.security.isolation.host_allowed` answers -- and they do not
constrain the child.

The module docstring previously said the child "receives read access to the
allowed roots via explicit arguments", which described an argument this code
never passed. A reader who believed it would have handed untrusted code to a
sandbox that was not one. For a real boundary, run the platform inside a
container or a user namespace; the API here stays identical either way.

Environment scrubbing is an **allow-list**
------------------------------------------
It used to be a deny-list: drop any variable whose name contains "secret",
"token", "key", "password" or "credential". That misses the shape secrets
actually take on this project -- ``ALCHEMY_URL`` and ``DATABASE_URL`` carry
credentials inside the URL and match none of those words. A deny-list over
names an attacker or an operator chooses is not a boundary, so the child now
receives only what a Python process needs to start.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, Final, FrozenSet, List, Mapping, Optional, Sequence

from .isolation import IsolationPolicy

__all__ = [
    "SandboxResult",
    "Sandbox",
    "run_sandboxed",
    "SandboxError",
    "BASE_ENV_ALLOWLIST",
]

#: Environment variables a child is allowed to inherit.
#:
#: Chosen as the minimum a Python interpreter needs to start on Windows and
#: POSIX. Anything not named here is dropped, including every variable this
#: project uses to carry a provider credential.
BASE_ENV_ALLOWLIST: Final[FrozenSet[str]] = frozenset(
    {
        # POSIX
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TMPDIR",
        # Windows
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        # Python, behaviour-only. PYTHONPATH is deliberately absent: it would
        # let the parent's import path decide what the child executes.
        "PYTHONIOENCODING",
        "PYTHONUTF8",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONHASHSEED",
    }
)


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

    def _resolved_workdir(self) -> str:
        """
        The working directory, checked against the policy when one is set.

        An explicit ``workdir`` outside every allowed root is refused rather
        than used: the caller asked for a confinement and named a directory
        outside it, and silently honouring the second would discard the first.
        """
        if self._workdir is None:
            return self._temp_workdir()

        if self.policy.file_roots and not self.policy.allows_path(self._workdir):
            raise SandboxError(
                f"workdir {self._workdir!r} is outside the policy's file_roots"
            )
        return self._workdir

    def _scrubbed_env(self) -> Dict[str, str]:
        """
        The child's environment: the allow-list, plus explicit additions.

        Variables passed as ``env=`` to the constructor are the caller's
        deliberate choice and are always included -- that is the supported way
        to hand the child something it needs.
        """
        scrubbed = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in BASE_ENV_ALLOWLIST
        }
        scrubbed.update(self.env)
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
        workdir = self._resolved_workdir()

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