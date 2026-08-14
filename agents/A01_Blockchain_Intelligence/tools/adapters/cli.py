"""
Tools :: Adapters :: CLI Adapter
================================

Executes *trusted* command-line applications through the unified adapter
contract, layered on top of :class:`SubprocessAdapter`.

Use cases:
    * git, docker CLI, ffmpeg, foundry, hardhat, security scanners
    * any operator-approved binary invoked with a controlled argument list

The CLI adapter adds a **command allow-list** on top of the raw subprocess
adapter. This is the security boundary that distinguishes "run any shell
command" from "run approved tools only". Shell interpretation is always
disabled for allow-listed commands.
"""

from __future__ import annotations

import os
import shutil
from typing import Any, Optional, Tuple

from . import AdapterRequest, AdapterResponse, AdapterValidationError
from .subprocess import SubprocessAdapter

__all__ = ["CLIAdapter", "register"]


def register(**options: Any) -> "CLIAdapter":
    """Factory used by :func:`adapters.get_adapter`."""
    return CLIAdapter(**options)


class CLIAdapter(SubprocessAdapter):
    """
    Allow-list gated CLI runner.

    ``allowed_commands`` is a set of executable base names (e.g. {"git",
    "docker", "ffmpeg"}). Requests that reference a binary outside the set are
    rejected before any process is spawned. The check uses the *basename*
    without extension, so ``/usr/bin/git`` or ``git.exe`` both match ``git``.
    """

    transport = "cli"

    def __init__(
        self,
        *,
        allowed_commands: Optional[Tuple[str, ...]] = None,
        resolve_executable: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.allowed_commands = set(allowed_commands or ())
        self.resolve_executable = resolve_executable

    def connect(self, **options: Any) -> "CLIAdapter":
        super().connect(**options)
        return self

    @staticmethod
    def _base_name(argv0: str) -> str:
        """Normalize an executable path to its plain basename without extension."""
        name = os.path.basename(argv0.replace("\\", "/"))
        if name.lower().endswith(".exe"):
            name = name[:-4]
        return name

    def _resolve(self, argv: Any) -> Tuple[str, list]:
        """Extract the base command, verify it is allow-listed, resolve its path."""
        if isinstance(argv, str):
            raise AdapterValidationError(
                "CLI adapter requires an argument list, not a raw shell string; "
                "use params['argv']",
                transport=self.transport,
            )
        if not argv:
            raise AdapterValidationError("argv must not be empty", transport=self.transport)

        argv_list = [str(a) for a in argv]
        base_name = self._base_name(argv_list[0])
        if self.allowed_commands and base_name not in self.allowed_commands:
            raise AdapterValidationError(
                f"command {base_name!r} is not in the allow-list "
                f"{sorted(self.allowed_commands)}",
                transport=self.transport,
            )

        if self.resolve_executable:
            resolved = shutil.which(base_name) or shutil.which(argv_list[0])
            if resolved is None:
                raise AdapterValidationError(
                    f"executable {base_name!r} not found on PATH",
                    transport=self.transport,
                )
            argv_list[0] = resolved
        return argv_list[0], argv_list

    def execute(self, request: AdapterRequest) -> AdapterResponse:
        self.validate_request(request)
        params = dict(request.params or {})
        argv: Any = params.get("argv") or params.get("args") or request.data
        if argv is None:
            raise AdapterValidationError(
                "params['argv'] is required", transport=self.transport
            )

        try:
            _, argv_list = self._resolve(argv)
        except AdapterValidationError as exc:
            return self.normalize_response(False, error=exc, method="run")

        # Never allow shell=true through the CLI boundary.
        params["argv"] = argv_list
        params["shell"] = False
        return super().execute(
            AdapterRequest(
                method="run",
                params=params,
                data=request.data,
                headers=request.headers,
                timeout=request.timeout,
                retries=request.retries,
                request_id=request.request_id,
            )
        )
