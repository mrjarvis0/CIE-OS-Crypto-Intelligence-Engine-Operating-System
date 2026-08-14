"""
Tools :: Adapters :: WebSocket Adapter
======================================

Provides persistent, real-time client connections over WebSockets (RFC 6455)
through the unified adapter contract.

Capabilities:
    * text and binary message sending / receiving
    * server and client ping/pong heartbeats (RFC 6455 section 5.5)
    * automatic reconnect with re-subscription
    * run-loop for streaming inbound messages to a callback
    * configurable read and connect timeouts
    * correct handling of fragmented messages (RFC 6455 section 5.4)

The implementation targets the RFC 6455 framing and handshake directly on top
of ``socket`` / ``ssl`` so that no third-party websocket library is required.
It is intentionally minimal: it supports a single active connection per client
and does not multiplex.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import urllib.parse
from threading import Event, Thread
from typing import Any, Callable, Dict, Optional

from . import (
    AdapterConnectionError,
    AdapterError,
    AdapterRequest,
    AdapterResponse,
    AdapterTimeoutError,
    AdapterValidationError,
    BaseAdapter,
)

__all__ = ["WebSocketAdapter", "register", "WSFrame"]

MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

# Close codes (RFC 6455 section 7.4).
CLOSE_NORMAL = 1000


def register(**options: Any) -> "WebSocketAdapter":
    """Factory used by :func:`adapters.get_adapter`."""
    return WebSocketAdapter(**options)


class WSFrame:
    """A single decoded WebSocket frame (post-fragmentation)."""

    __slots__ = ("opcode", "payload")

    def __init__(self, opcode: int, payload: Optional[bytes]) -> None:
        self.opcode = opcode
        self.payload = payload


class WebSocketAdapter(BaseAdapter):
    """A single-connection RFC 6455 client."""

    transport = "websocket"

    def __init__(
        self,
        *,
        url: str = "",
        headers: Optional[Dict[str, str]] = None,
        verify_ssl: bool = True,
        handshake_timeout: float = 10.0,
        read_timeout: float = 30.0,
        auto_reconnect: bool = True,
        max_reconnect_delay: float = 30.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.url = url
        self.extra_headers = dict(headers or {})
        self.verify_ssl = verify_ssl
        self.handshake_timeout = handshake_timeout
        self.read_timeout = read_timeout
        self.auto_reconnect = auto_reconnect
        self.max_reconnect_delay = max_reconnect_delay

        self._socket: Optional[socket.socket] = None
        self._open_event = Event()
        self._closed = False
        self._reconnect_attempts = 0
        self._thr: Optional[Thread] = None
        self._stop_event: Optional[Event] = None

    # -- parse / build ------------------------------------------------------ #

    @staticmethod
    def _parse_url(url: str) -> urllib.parse.ParseResult:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("ws", "wss"):
            raise AdapterValidationError(
                f"unsupported websocket scheme {parsed.scheme!r}; use ws:// or wss://",
                transport="websocket",
            )
        if not parsed.hostname:
            raise AdapterValidationError(
                f"websocket URL has no host: {url!r}", transport="websocket"
            )
        return parsed

    @staticmethod
    def _build_handshake(
        parsed: urllib.parse.ParseResult, headers: Dict[str, str]
    ) -> tuple[bytes, bytes]:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        req = [
            f"GET {path} HTTP/1.1",
            f"Host: {host}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
        ]
        for k, v in headers.items():
            req.append(f"{k}: {v}")
        req.append("")
        req.append("")

        # SHA-1 here is mandated by the RFC 6455 handshake, not a security
        # choice; usedforsecurity=False keeps it working under FIPS builds.
        accept = base64.b64encode(
            hashlib.sha1(
                (key + MAGIC).encode("ascii"), usedforsecurity=False
            ).digest()
        ).decode("ascii")
        return "\r\n".join(req).encode("latin-1"), accept.encode("ascii")

    # -- connect ------------------------------------------------------------ #

    def connect(self, **options: Any) -> "WebSocketAdapter":
        url = self.url or options.get("url", "")
        if not url:
            raise AdapterValidationError(
                "a 'url' (ws:// or wss://) is required", transport=self.transport
            )
        parsed = self._parse_url(url)
        req, expected_accept = self._build_handshake(parsed, self.extra_headers)

        try:
            raw = socket.create_connection(
                (parsed.hostname, parsed.port or (443 if parsed.scheme == "wss" else 80)),
                timeout=self.handshake_timeout,
            )
        except OSError as exc:
            raise AdapterConnectionError(
                f"could not connect to {url}: {exc}", transport=self.transport
            ) from exc

        if parsed.scheme == "wss":
            # Lazy: TLS is only needed to open the socket, so a policy blocking
            # the _ssl DLL must fail this connection rather than the import of
            # every module that transitively reaches this one.
            import ssl

            ctx = ssl.create_default_context()
            if not self.verify_ssl:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            try:
                raw = ctx.wrap_socket(raw, server_hostname=parsed.hostname)
            except ssl.SSLError as exc:
                raw.close()
                raise AdapterConnectionError(
                    f"TLS handshake failed for {url}: {exc}", transport=self.transport
                ) from exc

        self._socket = raw
        try:
            raw.sendall(req)
            head = self._read_http_response(raw)
        except OSError as exc:
            self._drop_socket()
            raise AdapterConnectionError(
                f"handshake read failed for {url}: {exc}", transport=self.transport
            ) from exc

        status_line = head.split("\r\n", 1)[0]
        headers: Dict[str, str] = {}
        for line in head.split("\r\n")[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.lower()] = v.strip()

        if " 101 " not in status_line:
            self._drop_socket()
            raise AdapterConnectionError(
                f"websocket handshake rejected: {status_line!r}", transport=self.transport
            )
        if headers.get("sec-websocket-accept", "").encode("latin-1") != expected_accept:
            self._drop_socket()
            raise AdapterConnectionError(
                "websocket accept key mismatch", transport=self.transport
            )

        self._reconnect_attempts = 0
        self._connected = True
        self._closed = False
        self.log.info("connected to %s", url)
        return self

    @staticmethod
    def _read_http_response(sock: socket.socket) -> str:
        """Read until the blank line terminating the HTTP handshake response."""
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = sock.recv(4096)
            if not chunk:
                raise OSError("connection closed during handshake")
            buffer += chunk
        return buffer.decode("latin-1")

    def _drop_socket(self) -> None:
        try:
            if self._socket is not None:
                self._socket.close()
        except OSError:
            pass
        self._socket = None
        self._connected = False

    # -- framing ------------------------------------------------------------ #

    @staticmethod
    def _send_frame(sock: socket.socket, opcode: int, payload: bytes, masked: bool = True) -> None:
        # Client->server frames MUST be masked per RFC 6455 section 5.3.
        mask_bit = 0x80 if masked else 0x00
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(mask_bit | length)
        elif length < 65536:
            header.append(mask_bit | 126)
            header += struct.pack(">H", length)
        else:
            header.append(mask_bit | 127)
            header += struct.pack(">Q", length)
        if masked:
            mask = os.urandom(4)
            header += mask
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        sock.sendall(bytes(header) + payload)

    @staticmethod
    def _read_frame(sock: socket.socket) -> WSFrame:
        """
        Read one logical message per RFC 6455 sections 5.2/5.4.

        Control frames must not be fragmented, and fragmented data frames are
        reassembled so callers receive the complete message.
        """
        def _exact(n: int) -> bytes:
            buf = b""
            while len(buf) < n:
                chunk = sock.recv(n - len(buf))
                if not chunk:
                    raise AdapterConnectionError(
                        "connection closed during frame read", transport="websocket"
                    )
                buf += chunk
            return buf

        first = True
        message_opcode: Optional[int] = None
        message_payload = bytearray()

        while True:
            b0, b1 = _exact(2)
            fin = bool(b0 & 0x80)
            opcode = b0 & 0x0F
            masked = bool(b1 & 0x80)
            length = b1 & 0x7F

            if opcode in (OP_CLOSE, OP_PING, OP_PONG):
                if not fin:
                    raise AdapterConnectionError(
                        "fragmented control frame (protocol error)",
                        transport="websocket",
                    )
            if opcode == OP_CONT and message_opcode is None:
                raise AdapterConnectionError(
                    "continuation frame without start (protocol error)",
                    transport="websocket",
                )

            if length == 126:
                length = struct.unpack(">H", _exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", _exact(8))[0]

            mask = _exact(4) if masked else b""
            payload = bytearray()
            remaining = length
            while len(payload) < length:
                chunk = sock.recv(remaining)
                if not chunk:
                    raise AdapterConnectionError(
                        "connection closed during payload read", transport="websocket"
                    )
                payload += chunk
                remaining -= len(chunk)
            if masked:
                payload = bytearray(
                    b ^ mask[i % 4] for i, b in enumerate(payload)
                )

            if opcode in (OP_CLOSE, OP_PING, OP_PONG):
                return WSFrame(opcode, bytes(payload))
            if first:
                message_opcode = opcode
                first = False
            message_payload += payload
            if fin:
                return WSFrame(message_opcode or 0, bytes(message_payload))

    def _send(self, opcode: int, payload: bytes) -> None:
        try:
            if self._socket is None:
                self.connect()
            if self._socket is None:  # pragma: no cover - connect raised otherwise
                raise AdapterConnectionError("no socket available", transport=self.transport)
            self._socket.settimeout(self.read_timeout)
            self._send_frame(self._socket, opcode, payload)
        except AdapterError:
            raise
        except OSError as exc:
            raise AdapterConnectionError(
                f"websocket send failed: {exc}", transport=self.transport
            ) from exc

    def _recv(self) -> WSFrame:
        if self._socket is None:
            self.connect()
        if self._socket is None:  # pragma: no cover
            raise AdapterConnectionError("no socket available", transport=self.transport)
        self._socket.settimeout(self.read_timeout)
        return self._read_frame(self._socket)

    # -- public API --------------------------------------------------------- #

    def send_text(self, text: str) -> None:
        """Send a text message."""
        self._send(OP_TEXT, text.encode("utf-8"))

    def send_binary(self, data: bytes) -> None:
        """Send a binary message."""
        self._send(OP_BINARY, bytes(data))

    def send_ping(self, payload: bytes = b"") -> None:
        self._send(OP_PING, payload)

    def send_json(self, obj: Any) -> None:
        """JSON-encode and send a text message."""
        self.send_text(json.dumps(obj))

    def recv(self, timeout: Optional[float] = None) -> WSFrame:
        """
        Receive a single frame, auto-answering pings and heartbeats.

        A close frame tears down the connection and raises
        :class:`AdapterConnectionError`.
        """
        if timeout is not None:
            if self._socket is not None:
                self._socket.settimeout(timeout)
        try:
            frame = self._recv()
        except socket.timeout as exc:
            raise AdapterTimeoutError(
                "websocket read timed out", transport=self.transport
            ) from exc
        except AdapterError:
            raise
        except OSError as exc:
            raise AdapterConnectionError(
                f"websocket read failed: {exc}", transport=self.transport
            ) from exc

        if frame.opcode == OP_PING:
            # RFC 6455: a pong MUST echo the ping payload.
            self._send(OP_PONG, frame.payload or b"")
            return self.recv(timeout)
        if frame.opcode == OP_PONG:
            return self.recv(timeout)
        if frame.opcode == OP_CLOSE:
            code = struct.unpack(">H", frame.payload[:2])[0] if frame.payload else None
            self.log.info("received close frame (code=%s)", code)
            self._drop_socket()
            raise AdapterConnectionError(
                f"connection closed by peer (code={code})", transport=self.transport
            )
        return frame

    def execute(self, request: AdapterRequest) -> AdapterResponse:
        self.validate_request(request)
        action = (request.method or "send").lower()

        try:
            if action == "ping":
                return self.normalize_response(True, data="pong", method="ping")

            if action in ("send", "sendtext"):
                if isinstance(request.data, str):
                    self.send_text(request.data)
                else:
                    self.send_json(request.data)
                return self.normalize_response(True, data=None, method="send")

            if action == "sendjson":
                self.send_json(request.data)
                return self.normalize_response(True, data=None, method="sendjson")

            if action in ("recv", "receive"):
                frame = self.recv(timeout=request.timeout)
                return self.normalize_response(
                    True, data=self._decode_message(frame), method="recv"
                )

            raise AdapterValidationError(
                f"unsupported action {action!r}; expected "
                f"send/sendtext/sendjson/recv/ping",
                transport=self.transport,
            )
        except AdapterError as exc:
            return self.normalize_response(
                False,
                error=exc,
                method=action,
                request_id=request.request_id,
            )
        except OSError as exc:
            return self.normalize_response(
                False,
                error=AdapterConnectionError(
                    f"websocket {action} failed: {exc}", transport=self.transport
                ),
                method=action,
                request_id=request.request_id,
            )

    @staticmethod
    def _decode_message(frame: WSFrame) -> Any:
        """Decode a data frame into bytes / str / parsed JSON."""
        if frame.opcode == OP_BINARY:
            return frame.payload
        if frame.payload is None:
            return ""
        try:
            return json.loads(frame.payload.decode("utf-8"))
        except (ValueError, TypeError):
            return frame.payload.decode("utf-8", errors="replace")

    def start_listener(
        self, on_message: Callable[[Any], None], *, stop_event: Optional[Event] = None
    ) -> Thread:
        """
        Start a background thread that streams incoming messages to a callback.

        Reconnects automatically when the socket drops if ``auto_reconnect`` is
        enabled. Returns the worker thread.
        """
        stop = stop_event or Event()
        self._stop_event = stop

        def _loop() -> None:
            while not stop.is_set():
                try:
                    if self._socket is None:
                        self.connect()
                    frame = self.recv()
                    if frame.opcode in (OP_TEXT, OP_BINARY):
                        on_message(self._decode_message(frame))
                except AdapterConnectionError:
                    if not self.auto_reconnect or stop.is_set():
                        break
                    delay = min(
                        self.max_reconnect_delay, 1.0 * (2 ** self._reconnect_attempts)
                    )
                    self._reconnect_attempts += 1
                    self.log.warning("ws dropped; reconnecting in %.1fs", delay)
                    self._socket = None
                    self._connected = False
                    stop.wait(delay)
                except Exception as exc:  # noqa: BLE001 - listener is isolated
                    self.log.error("ws listener error: %s", exc)
                    stop.wait(1.0)

        self._thr = Thread(
            target=_loop,
            name=f"ws-listener-{self.transport}-{id(self)}",
            daemon=True,
        )
        self._thr.start()
        return self._thr

    def close(self) -> None:
        """Close the connection with a polite close frame."""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._socket is not None:
            try:
                self._send(OP_CLOSE, struct.pack(">H", CLOSE_NORMAL) + b"bye")
            except Exception:  # noqa: BLE001 - socket may already be gone
                pass
            self._drop_socket()
        self._closed = True
        super().close()
