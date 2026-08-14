"""
Tools :: Adapters :: Docker Adapter
===================================

Manages and runs containers via the Docker Engine HTTP API, using only the
standard library ``http.client`` client (no ``docker`` SDK requirement).

Capabilities:
    * image pulls
    * container create / start / stop / remove
    * resource limits (memory, CPUs)
    * volume bind-mounts and network attachments
    * log retrieval with multiplexed-stream decoding (raw-stream demux)
    * wait for exit status
    * running untrusted workloads in isolated containers

The adapter talks to the Docker Engine over its REST API, which is exposed on
a local TCP socket (``http://localhost:2375``) or a named pipe. The transport
is supplied via ``base_url``.
"""

from __future__ import annotations

import http.client
import json
import struct
import time
import urllib.parse
from typing import Any, Dict, List, Optional

from . import (
    AdapterConnectionError,
    AdapterError,
    AdapterExecutionError,
    AdapterRequest,
    AdapterResponse,
    AdapterValidationError,
    BaseAdapter,
)

__all__ = ["DockerAdapter", "register"]


def register(**options: Any) -> "DockerAdapter":
    """Factory used by :func:`adapters.get_adapter`."""
    return DockerAdapter(**options)


class DockerAdapter(BaseAdapter):
    """Minimal Docker Engine REST client."""

    transport = "docker"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:2375",
        api_version: str = "v1.43",
        default_timeout: float = 60.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self.default_timeout = default_timeout

    def connect(self, **options: Any) -> "DockerAdapter":
        self._connected = True
        return self

    # -- low-level HTTP ----------------------------------------------------- #

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        parsed = urllib.parse.urlparse(self.base_url)
        if parsed.scheme not in ("http", "https"):
            raise AdapterValidationError(
                f"unsupported docker transport {parsed.scheme!r}",
                transport=self.transport,
            )
        if not parsed.hostname:
            raise AdapterValidationError(
                f"docker base_url has no host: {self.base_url!r}",
                transport=self.transport,
            )

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if parsed.scheme == "https":
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                parsed.hostname, port, timeout=timeout or self.default_timeout
            )
        else:
            conn = http.client.HTTPConnection(
                parsed.hostname, port, timeout=timeout or self.default_timeout
            )

        url = f"/{self.api_version}{path}"
        payload: Optional[bytes] = None
        hdrs: Dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "CIE-OS/adapters-docker",
        }
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
        if headers:
            hdrs.update(headers)

        try:
            conn.request(method, url, body=payload, headers=hdrs)
            resp = conn.getresponse()
            raw = resp.read()
            status = resp.status
            ctype = resp.headers.get("Content-Type", "")
        except (OSError, http.client.HTTPException) as exc:
            raise AdapterConnectionError(
                f"docker engine unreachable at {self.base_url}: {exc}",
                transport=self.transport,
            ) from exc
        finally:
            conn.close()

        text = raw.decode("utf-8", errors="replace")
        if "application/json" in ctype or text.startswith(("{", "[")):
            try:
                data: Any = json.loads(text)
            except ValueError:
                data = text
        else:
            data = text

        if status >= 400:
            msg = data.get("message", text) if isinstance(data, dict) else text
            raise AdapterExecutionError(
                f"docker {method} {url} -> HTTP {status}: {msg}",
                transport=self.transport,
            )
        return {"status": status, "data": data}

    # -- images ------------------------------------------------------------- #

    def pull_image(self, image: str, *, tag: str = "latest") -> Dict[str, Any]:
        """Pull an image from a registry."""
        ref = f"{image}:{tag}" if ":" not in image else image
        query = f"/images/create?fromImage={urllib.parse.quote(ref, safe='/:')}"
        return self._request("POST", query)

    def list_images(self) -> List[Any]:
        result = self._request("GET", "/images/json")
        return result["data"] if isinstance(result["data"], list) else []

    def image_exists(self, image: str, *, tag: str = "latest") -> bool:
        ref = f"{image}:{tag}" if ":" not in image else image
        try:
            self._request("GET", f"/images/{urllib.parse.quote(ref, safe='/:')}/json")
            return True
        except AdapterExecutionError:
            return False

    # -- containers --------------------------------------------------------- #

    def create(
        self,
        image: str,
        *,
        name: Optional[str] = None,
        command: Optional[List[str]] = None,
        env: Optional[List[str]] = None,
        volumes: Optional[Dict[str, Dict[str, str]]] = None,
        memory: Optional[int] = None,
        nano_cpus: Optional[int] = None,
        network: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create (but do not start) a container. Returns its id."""
        host_config: Dict[str, Any] = {"AutoRemove": False}
        if memory:
            host_config["Memory"] = int(memory)
        if nano_cpus:
            host_config["NanoCpus"] = int(nano_cpus)
        if network:
            host_config["NetworkMode"] = network

        payload: Dict[str, Any] = {"Image": image, "HostConfig": host_config}
        if command:
            payload["Cmd"] = command
        if env:
            payload["Env"] = env
        if volumes:
            payload["Volumes"] = volumes

        # The container name is a query parameter on /containers/create, never
        # a body field.
        query = "/containers/create"
        if name:
            query += f"?name={urllib.parse.quote(name)}"
        result = self._request("POST", query, body=payload)
        return result["data"]  # {"Id": "...", "Warnings": [...]}

    def start(self, container_id: str) -> None:
        self._request("POST", f"/containers/{container_id}/start")

    def stop(self, container_id: str, *, timeout: Optional[int] = None) -> None:
        query = f"/containers/{container_id}/stop"
        if timeout is not None:
            query += f"?t={int(timeout)}"
        self._request("POST", query)

    def remove(self, container_id: str, *, force: bool = True) -> None:
        query = f"/containers/{container_id}?force={str(force).lower()}&v=1"
        self._request("DELETE", query)

    def wait(self, container_id: str, *, timeout: float = 60.0) -> Dict[str, Any]:
        """Waits until the container stops and returns its exit code."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                result = self._request("GET", f"/containers/{container_id}/json")
                state = result["data"].get("State", {})
                if state.get("Running") is False:
                    return {"ExitCode": state.get("ExitCode", 0), "Running": False}
            except AdapterExecutionError:
                pass
            if time.monotonic() > deadline:
                return {"ExitCode": -1, "Running": True, "TimedOut": True}
            time.sleep(1.0)

    def logs(
        self,
        container_id: str,
        *,
        tail: int = 100,
        stdout: bool = True,
        stderr: bool = True,
    ) -> str:
        query = (
            f"/containers/{container_id}/logs?stdout={str(stdout).lower()}"
            f"&stderr={str(stderr).lower()}&tail={int(tail)}"
        )
        result = self._request("GET", query)
        raw = result["data"]
        if isinstance(raw, str):
            # The engine returns an application/vnd.docker.raw-stream body with
            # an 8-byte header per frame: [stream_type, 0,0,0, len_uint32].
            if raw.startswith("\x01\x00\x00\x00") or raw.startswith("\x02\x00\x00\x00"):
                return self._demux_stream(raw.encode("latin-1"))
            return raw
        return ""

    @staticmethod
    def _demux_stream(raw: bytes) -> str:
        """Decode Docker's multiplexed stdio stream into plain text."""
        parts: List[str] = []
        offset = 0
        while offset + 8 <= len(raw):
            _stream_type = raw[offset]
            frame_len = struct.unpack(">I", raw[offset + 4 : offset + 8])[0]
            start, end = offset + 8, offset + 8 + frame_len
            if end > len(raw):
                break
            parts.append(raw[start:end].decode("utf-8", errors="replace"))
            offset = end
        return "".join(parts) if parts else raw.decode("utf-8", errors="replace")

    # -- unified execution -------------------------------------------------- #

    def execute(self, request: AdapterRequest) -> AdapterResponse:
        self.validate_request(request)
        params = dict(request.params or {})
        action = (request.method or "run").lower()

        if action == "ping":
            return self.normalize_response(True, data="pong", method="ping")

        if action not in (
            "pull", "run", "start", "stop", "remove", "wait", "logs", "list", "ls",
        ):
            return self.normalize_response(
                False,
                error=AdapterValidationError(
                    f"unsupported docker action {action!r}", transport=self.transport
                ),
                method=action,
                request_id=request.request_id,
            )

        image = params.get("image")

        try:
            if action == "pull":
                data = self.pull_image(image, tag=params.get("tag", "latest"))
                return self.normalize_response(
                    True, data=data, method=action, request_id=request.request_id
                )

            if action == "run":
                if image is None:
                    raise AdapterValidationError(
                        "params['image'] is required to run", transport=self.transport
                    )
                created = self.create(
                    image,
                    name=params.get("name"),
                    command=params.get("command"),
                    env=params.get("env"),
                    memory=params.get("memory"),
                    nano_cpus=params.get("nano_cpus"),
                    network=params.get("network"),
                )
                cid = created.get("Id")
                if cid is None:
                    raise AdapterExecutionError(
                        f"docker create returned no container id: {created}",
                        transport=self.transport,
                    )
                self.start(cid)
                wait_result = self.wait(
                    cid, timeout=float(params.get("timeout") or request.timeout or 60.0)
                )
                output_log = self.logs(cid, tail=params.get("tail", 100))
                if params.get("remove", True):
                    self.remove(cid)
                data = {"container_id": cid, **wait_result, "logs": output_log}
                return self.normalize_response(
                    True, data=data, method="run", request_id=request.request_id
                )

            if action == "start":
                self.start(params["container_id"])
                return self.normalize_response(True, data=None, method=action)
            if action == "stop":
                self.stop(params["container_id"], timeout=params.get("timeout"))
                return self.normalize_response(True, data=None, method=action)
            if action == "remove":
                self.remove(params["container_id"], force=params.get("force", True))
                return self.normalize_response(True, data=None, method=action)
            if action == "wait":
                return self.normalize_response(
                    True, data=self.wait(params["container_id"]), method=action
                )
            if action == "logs":
                return self.normalize_response(
                    True,
                    data=self.logs(
                        params["container_id"], tail=params.get("tail", 100)
                    ),
                    method=action,
                )
            if action in ("list", "ls"):
                return self.normalize_response(
                    True, data=self.list_images(), method=action
                )
        except KeyError as exc:
            return self.normalize_response(
                False,
                error=AdapterValidationError(
                    f"missing required parameter: {exc}", transport=self.transport
                ),
                method=action,
                request_id=request.request_id,
            )
        except AdapterError as exc:
            return self.normalize_response(
                False, error=exc, method=action, request_id=request.request_id
            )

        # Unreachable: every known action returns above.
        raise AdapterValidationError(  # pragma: no cover - defensive
            f"unsupported docker action {action!r}", transport=self.transport
        )
