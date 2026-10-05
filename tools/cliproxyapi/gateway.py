# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: INP001 - standalone installed script, not an importable package
"""Private facade: CLIProxyAPI chat and panel, plus native System One classification.

Run with an installed JSON config. This listener trusts its private network;
public access must pass through the separately authenticated gateway, which
rejects the management routes this facade forwards to the private network.
"""

from __future__ import annotations

import argparse
import http
import http.client
import io
import json
import select
import signal
import socket
import time
from contextlib import suppress
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, TypeGuard, final, override
from urllib.parse import SplitResult, unquote, urlsplit

if TYPE_CHECKING:
    from collections.abc import Callable
    from email.message import Message

BODY_LIMIT = 16 * 1024 * 1024
IO_TIMEOUT = 120
MIN_TOKEN_CHAR = 33
MAX_TOKEN_CHAR = 126
MAX_KEY_WEIGHT = 1_000_000
MAX_PORT = 65535
CHUNK_LINE_LIMIT = 8192
TRAILER_LIMIT = 65536
HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
# CLIProxyAPI's management surface (its server_middleware.go). The panel sends its
# own management key, which CLIProxyAPI checks, so these keep their credentials.
MANAGEMENT_PREFIXES = ("/v0/management/", "/v8/management/", "/v0/resource/plugins/")
MANAGEMENT_PATHS = frozenset({"/management.html", "/v0/management", "/v8/management"})
MANAGEMENT_CREDENTIALS = frozenset({"authorization", "x-management-key"})
MODEL_LIST_PATH = "/v1/models"
# CLIProxyAPI's Codex-shaped catalog carries per-model context windows that its
# OpenAI model list omits. An empty client version requests unfiltered metadata
# without identifying the gateway as a particular harness.
CODEX_CATALOG_PATH = "/v1/models?client_version="
# Owners whose Claude models CLIProxyAPI serves natively at /v1/messages. Other
# pools translate Claude through their own protocol and may reject it there.
ANTHROPIC_NATIVE_OWNERS = frozenset({"anthropic", "claude"})


@dataclass(frozen=True, slots=True)
class ApiKeyEntry:
    """One upstream credential and its routing weight."""

    api_key: str
    weight: int


@dataclass(frozen=True, slots=True)
class Config:
    """Validated listener, upstream destinations, and classifier policy."""

    host: str
    port: int
    upstream: str
    system_one_url: str
    api_key_entries: tuple[ApiKeyEntry, ...]
    models: frozenset[str]


def endpoint(value: object, *, origin_only: bool = False) -> str:
    """Validate configured fixed destinations, never client-provided URLs."""
    if not isinstance(value, str):
        msg = "Upstream URL must be a string"
        raise TypeError(msg)
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (origin_only and parsed.path not in {"", "/"})
    ):
        msg = "Upstream must be an HTTP(S) URL without credentials or query"
        raise ValueError(msg)
    _ = parsed.port
    return value.rstrip("/")


def decode_json(value: str | bytes) -> object:
    """Contain stdlib's untyped decode result at the JSON boundary."""
    # Stdlib returns Any; callers receive unknown data and narrow it immediately.
    return json.loads(value)  # pyright: ignore[reportAny]


def is_object(value: object) -> TypeGuard[dict[str, object]]:
    """Narrow a decoded JSON object."""
    # JSON decoding guarantees that object keys are strings.
    return isinstance(value, dict)


def is_list(value: object) -> TypeGuard[list[object]]:
    """Narrow a decoded JSON array."""
    return isinstance(value, list)


def is_strings(value: object) -> TypeGuard[list[str]]:
    """Check that every array element is a string."""
    return is_list(value) and all(isinstance(item, str) for item in value)


def read_key_entry(value: object) -> ApiKeyEntry:
    """Validate each key and weight before building the request pool."""
    if not is_object(value):
        msg = "systemOne.apiKeyEntries entries must be objects"
        raise ValueError(msg)
    key, weight = value.get("apiKey"), value.get("weight", 1)
    if (
        not isinstance(key, str)
        or not key
        or any(not MIN_TOKEN_CHAR <= ord(char) <= MAX_TOKEN_CHAR for char in key)
    ):
        msg = "systemOne.apiKeyEntries keys must be nonempty printable ASCII tokens"
        raise ValueError(msg)
    if (
        isinstance(weight, bool)
        or not isinstance(weight, int)
        or not 1 <= weight <= MAX_KEY_WEIGHT
    ):
        msg = "systemOne.apiKeyEntries weights must be integers from 1 to 1000000"
        raise ValueError(msg)
    return ApiKeyEntry(key, weight)


def read_config(path: Path) -> Config:
    """Narrow the installed config once before opening a listener."""
    raw = decode_json(path.read_text(encoding="utf-8"))
    if not is_object(raw):
        msg = "Gateway config must be an object"
        raise TypeError(msg)
    listen = raw.get("listen")
    classifier = raw.get("systemOne")
    if not is_object(listen) or not is_object(classifier):
        msg = "Gateway requires listen and systemOne objects"
        raise TypeError(msg)
    host, port = listen.get("host"), listen.get("port")
    entries = classifier.get("apiKeyEntries")
    models = classifier.get("models")
    if not isinstance(host, str) or not host:
        msg = "listen.host must be a nonempty string"
        raise ValueError(msg)
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= MAX_PORT:
        msg = "listen.port must be an integer from 0 to 65535"
        raise ValueError(msg)
    if not is_list(entries) or not entries:
        msg = "systemOne.apiKeyEntries must be a nonempty list"
        raise ValueError(msg)
    key_entries = tuple(read_key_entry(entry) for entry in entries)
    if len({entry.api_key for entry in key_entries}) != len(key_entries):
        msg = "systemOne.apiKeyEntries must contain unique keys"
        raise ValueError(msg)
    if not is_strings(models) or not models or not all(models):
        msg = "systemOne.models must be a nonempty list of model names"
        raise ValueError(msg)
    system_url = endpoint(classifier.get("baseUrl"))
    parsed = urlsplit(system_url)
    if parsed.scheme != "https" and parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        msg = "System One requires HTTPS except for loopback tests"
        raise ValueError(msg)
    if len(set(models)) != len(models) or any(
        model.strip() != model or any(char.isspace() for char in model)
        for model in models
    ):
        msg = "System One model names must be unique and whitespace-free"
        raise ValueError(msg)
    return Config(
        host,
        port,
        endpoint(raw.get("upstream"), origin_only=True),
        system_url + "/systemone",
        key_entries,
        frozenset(models),
    )


def fetch_json(url: str, headers: dict[str, str]) -> object | None:
    """GET a JSON document from CLIProxyAPI; None on any transport or HTTP failure."""
    parts = urlsplit(url)
    connection_type = (
        http.client.HTTPSConnection
        if parts.scheme == "https"
        else http.client.HTTPConnection
    )
    connection = connection_type(parts.hostname or "", parts.port, timeout=IO_TIMEOUT)
    try:
        target = parts.path + ("?" + parts.query if parts.query else "")
        # http.client does not decompress; internal reads need identity encoding.
        json_headers = {
            key: value
            for key, value in headers.items()
            if key.lower() != "accept-encoding"
        }
        connection.request(
            "GET", target, headers=json_headers | {"Accept-Encoding": "identity"}
        )
        with connection.getresponse() as response:
            if response.status != http.HTTPStatus.OK:
                return None
            return decode_json(response.read())
    except (OSError, http.client.HTTPException, ValueError, UnicodeError):
        return None
    finally:
        connection.close()


def context_windows(catalog: object) -> dict[str, int]:
    """Map model ids to positive context windows from the Codex catalog."""
    models = catalog.get("models") if is_object(catalog) else None
    windows: dict[str, int] = {}
    for model in models if is_list(models) else []:
        if not is_object(model):
            continue
        slug = model.get("slug")
        window = model.get("context_window")
        if isinstance(slug, str) and type(window) is int and window > 0:
            windows[slug] = window
    return windows


def enrich_model_list(listing: object, catalog: object) -> object:
    """Add `context_length` and `supported_endpoint_types` to each listed model."""
    data = listing.get("data") if is_object(listing) else None
    if not is_object(listing) or not is_list(data):
        return listing
    windows = context_windows(catalog)
    enriched: list[object] = []
    for model in data:
        if not is_object(model) or not isinstance(model.get("id"), str):
            enriched.append(model)
            continue
        model_id = str(model["id"])
        entry = dict(model)
        if model_id in windows:
            entry["context_length"] = windows[model_id]
        owner = model.get("owned_by")
        native = (
            model_id.startswith("claude-")
            and isinstance(owner, str)
            and owner in ANTHROPIC_NATIVE_OWNERS
        )
        entry["supported_endpoint_types"] = (
            ["anthropic", "openai"] if native else ["openai"]
        )
        enriched.append(entry)
    return {**listing, "data": enriched}


def excluded_headers(headers: Message) -> frozenset[str]:
    """Combine hop-by-hop headers with those nominated by Connection."""
    nominated = {
        token.strip().lower()
        for value in headers.get_all("Connection", [])
        for token in value.split(",")
    }
    return HOP_HEADERS | nominated


@final
class KeyPool:
    """Smooth weighted round robin; one atomic turn per accepted classification."""

    def __init__(self, entries: tuple[ApiKeyEntry, ...]) -> None:
        """Initialize weighted routing state and its lock."""
        self.entries = entries
        self.current = [0 for _ in entries]
        self.total = sum(entry.weight for entry in entries)
        self.lock = Lock()

    def pick(self) -> str:
        """Consume one weighted routing turn atomically."""
        with self.lock:
            self.current = [
                current + entry.weight
                for current, entry in zip(self.current, self.entries, strict=True)
            ]
            selected = max(range(len(self.entries)), key=self.current.__getitem__)
            self.current[selected] -= self.total
            return self.entries[selected].api_key


@final
class GatewayServer(ThreadingHTTPServer):
    """Private listener with shared classifier credentials."""

    # server_close waits for active requests after the listener is closed.
    daemon_threads = False

    def __init__(self, config: Config) -> None:
        """Bind the configured address and initialize the credential pool."""
        self.config = config
        self.key_pool = KeyPool(config.api_key_entries)
        if ":" in config.host:
            self.address_family = socket.AF_INET6
        super().__init__((config.host, config.port), ProxyHandler)


class UnbufferedResponse(http.client.HTTPResponse):
    """Keep bytes after an upgrade handshake in the socket for tunneling."""

    def __init__(
        self,
        sock: socket.socket,
        debuglevel: int = 0,
        method: str | None = None,
        url: str | None = None,
    ) -> None:
        """Minimize buffering so upgrade frames remain available to the tunnel."""
        super().__init__(sock, debuglevel, method, url)
        self.fp.close()
        self.fp: io.BufferedReader = io.BufferedReader(
            sock.makefile("rb", buffering=0), buffer_size=1
        )


@final
class ProxyHandler(BaseHTTPRequestHandler):
    """Validate incoming routes and relay their HTTP or WebSocket traffic."""

    rbufsize = 0
    connection: socket.socket

    @override
    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(IO_TIMEOUT)

    def error(self, status: int, message: str) -> None:
        """Send a JSON error response."""
        payload = json.dumps({"error": {"message": message}}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        _ = self.wfile.write(payload)

    def body(self, *, classifier: bool) -> bytes | None:
        """Read bounded classifier bodies or unrestricted ordinary uploads."""
        lengths = self.headers.get_all("Content-Length", [])
        encodings = self.headers.get_all("Transfer-Encoding", [])
        chunked = len(encodings) == 1 and encodings[0].strip().lower() == "chunked"
        if len(lengths) > 1 or (encodings and (not chunked or lengths)):
            self.error(400, "Unsupported or ambiguous request framing")
            return None
        try:
            received = self._read_body(lengths, chunked=chunked, classifier=classifier)
        except TimeoutError:
            self.error(408, "Request body timed out")
        except ValueError as error:
            self.error(400, str(error))
        else:
            if received is not None:
                self.connection.settimeout(IO_TIMEOUT)
            return received
        return None

    def _read_body(
        self, lengths: list[str], *, chunked: bool, classifier: bool
    ) -> bytes | None:
        deadline = time.monotonic() + IO_TIMEOUT

        def budget() -> None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            self.connection.settimeout(remaining)

        def exact(length: int) -> bytes:
            received = bytearray()
            while len(received) < length:
                budget()
                piece = self.rfile.read(length - len(received))
                if not piece:
                    msg = "Incomplete request body"
                    raise ValueError(msg)
                received.extend(piece)
            return bytes(received)

        def line() -> bytes:
            budget()
            value = self.rfile.readline(CHUNK_LINE_LIMIT + 1)
            if len(value) > CHUNK_LINE_LIMIT or not value.endswith(b"\r\n"):
                msg = "Invalid chunk framing"
                raise ValueError(msg)
            return value

        if chunked:
            return self._chunked_body(line, exact, classifier=classifier)
        return self._fixed_body(lengths, exact, classifier=classifier)

    def _fixed_body(
        self, lengths: list[str], exact: Callable[[int], bytes], *, classifier: bool
    ) -> bytes | None:
        length = int(lengths[0]) if lengths else 0
        if length < 0:
            msg = "Invalid Content-Length"
            raise ValueError(msg)
        if classifier and length > BODY_LIMIT:
            self.error(413, "Request body exceeds 16 MiB")
            return None
        return exact(length)

    def _chunked_body(
        self,
        line: Callable[[], bytes],
        exact: Callable[[int], bytes],
        *,
        classifier: bool,
    ) -> bytes | None:
        received = bytearray()
        while True:
            size_text = line().split(b";", 1)[0].strip()
            if not size_text or any(
                char not in b"0123456789abcdefABCDEF" for char in size_text
            ):
                msg = "Invalid chunk size"
                raise ValueError(msg)
            size = int(size_text, 16)
            if classifier and len(received) + size > BODY_LIMIT:
                self.error(413, "Request body exceeds 16 MiB")
                return None
            if not size:
                self._consume_trailers(line)
                return bytes(received)
            received.extend(exact(size))
            if exact(2) != b"\r\n":
                msg = "Invalid chunk terminator"
                raise ValueError(msg)

    @staticmethod
    def _consume_trailers(line: Callable[[], bytes]) -> None:
        trailer_size = 0
        while trailer := line():
            trailer_size += len(trailer)
            if trailer_size > TRAILER_LIMIT:
                msg = "Trailers exceed 64 KiB"
                raise ValueError(msg)
            if trailer == b"\r\n":
                break

    def forward(self) -> None:
        """Validate the route and dispatch discovery, classification, or relay."""
        parsed = urlsplit(self.path)
        classifier = self.command == "POST" and self.path == "/v1/systemone"
        discovery = self.command == "GET" and self.path == "/v1/systemone/models"
        decoded_path = unquote(parsed.path)
        safe_path = (
            not any(part in {".", ".."} for part in decoded_path.split("/"))
            and "\\" not in decoded_path
            and "%" not in decoded_path
        )
        management = safe_path and (
            parsed.path in MANAGEMENT_PATHS
            or parsed.path.startswith(MANAGEMENT_PREFIXES)
        )
        ordinary = management or (
            safe_path
            and (
                parsed.path.startswith(
                    ("/v1/", "/v1beta/", "/backend-api/codex/", "/openai/v1/")
                )
                or parsed.path in {"/responses", "/responses/compact"}
            )
            and decoded_path.split("/")[2:3] != ["management"]
        )
        websocket = (
            ordinary
            and self.command == "GET"
            and self.headers.get("Upgrade", "").lower() == "websocket"
        )
        if decoded_path.startswith("/v1/systemone") and not classifier:
            ordinary = websocket = False
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or not (classifier or discovery or ordinary)
        ):
            self.error(404, "Unknown inference route")
            return
        if self.headers.get("Upgrade") is not None and not websocket:
            self.error(400, "Unsupported protocol upgrade")
            return
        body = self.body(classifier=classifier)
        if body is None:
            return
        server = self.server
        if not isinstance(server, GatewayServer):
            msg = "Expected GatewayServer"
            raise TypeError(msg)
        config = server.config
        if discovery:
            payload = json.dumps(
                {
                    "object": "list",
                    "data": [{"id": model} for model in sorted(config.models)],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            _ = self.wfile.write(payload)
            return
        if classifier:
            if not self._valid_classification(body, config):
                return
            url = config.system_one_url
            headers = {
                "Authorization": f"Bearer {server.key_pool.pick()}",
                "Content-Type": "application/json",
            }
        else:
            url = config.upstream + self.path
            headers = self._relay_headers(management=management, websocket=websocket)
        if self.command == "GET" and self.path == MODEL_LIST_PATH:
            self.model_list(config.upstream, headers)
        else:
            self.relay(urlsplit(url), body, headers, websocket=websocket)

    def _valid_classification(self, body: bytes, config: Config) -> bool:
        try:
            payload = decode_json(body)
        except (ValueError, UnicodeError):
            self.error(400, "System One body must be JSON")
            return False
        if not is_object(payload) or not isinstance(payload.get("model"), str):
            self.error(400, "System One requires a string model")
            return False
        if payload["model"] not in config.models:
            self.error(403, "System One model is not allowed")
            return False
        return True

    def _relay_headers(self, *, management: bool, websocket: bool) -> dict[str, str]:
        excluded = excluded_headers(self.headers) | {
            "host",
            "content-length",
            "authorization",
            "cookie",
            "x-api-key",
        }
        if management:
            excluded -= MANAGEMENT_CREDENTIALS
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in excluded
        }
        if not management:
            headers["Authorization"] = "Bearer keyless"
        if websocket:
            headers["Connection"] = "Upgrade"
            headers["Upgrade"] = "websocket"
        return headers

    def model_list(self, upstream: str, headers: dict[str, str]) -> None:
        """Serve the OpenAI model list enriched with protocol metadata.

        `context_length` comes from the Codex catalog, and
        `supported_endpoint_types` marks Claude models that /v1/messages serves
        natively. A failed metadata fetch leaves context limits absent; a failed
        listing fetch falls back to the normal relay.
        """
        listing = fetch_json(upstream + MODEL_LIST_PATH, headers)
        if listing is None:
            self.relay(urlsplit(upstream + self.path), b"", headers, websocket=False)
            return
        catalog = fetch_json(upstream + CODEX_CATALOG_PATH, headers)
        payload = json.dumps(enrich_model_list(listing, catalog)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        _ = self.wfile.write(payload)

    def relay(
        self, url: SplitResult, body: bytes, headers: dict[str, str], *, websocket: bool
    ) -> None:
        """Stream one upstream response without following redirects."""
        connection_type = (
            http.client.HTTPSConnection
            if url.scheme == "https"
            else http.client.HTTPConnection
        )
        # http.client never follows redirects and ignores ambient proxy settings.
        connection = connection_type(url.hostname or "", url.port, timeout=IO_TIMEOUT)
        connection.response_class = UnbufferedResponse
        upstream_socket = None
        try:
            try:
                target = url.path + ("?" + url.query if url.query else "")
                connection.request(self.command, target, body=body, headers=headers)
                upstream_socket = connection.sock
                response = connection.getresponse()
            except (OSError, http.client.HTTPException):
                # Only upstream failures before response headers warrant a 502.
                with suppress(OSError):
                    self.error(502, "Inference upstream is unavailable")
                return
            with response:
                upgraded = (
                    websocket and response.status == http.HTTPStatus.SWITCHING_PROTOCOLS
                )
                if upgraded:
                    self.protocol_version = "HTTP/1.1"
                    self.close_connection = True
                self.send_response(response.status)
                excluded = excluded_headers(response.headers) | {"content-length"}
                for key, value in response.headers.items():
                    if key.lower() not in excluded:
                        self.send_header(key, value)
                if upgraded:
                    self.send_header("Connection", "Upgrade")
                    self.send_header("Upgrade", "websocket")
                self.end_headers()
                if upgraded and upstream_socket is not None:
                    self.wfile.flush()
                    self.tunnel(upstream_socket)
                    return
                # HTTP/1.0 close delimits the body after stripping chunk framing.
                while chunk := response.read1(65536):
                    _ = self.wfile.write(chunk)
                    self.wfile.flush()
        except (OSError, http.client.HTTPException):
            # A client disconnect or a truncated started response closes the
            # stream; neither can be repaired by writing another HTTP response.
            self.close_connection = True
        finally:
            connection.close()
            if upstream_socket is not None:
                _ = upstream_socket.close()

    def tunnel(self, upstream: socket.socket) -> None:
        """Relay opaque frames until EOF, retaining bounded socket write waits."""
        peers = {self.connection: upstream, upstream: self.connection}
        while True:
            ready = select.select(list(peers), [], [], IO_TIMEOUT)[0]
            for source in ready:
                chunk = source.recv(65536)
                if not chunk:
                    return
                _ = peers[source].sendall(chunk)

    def do_GET(self) -> None:
        """Handle GET through the shared route validator."""
        self.forward()

    def do_POST(self) -> None:
        """Handle POST through the shared route validator."""
        self.forward()

    do_PUT = do_POST  # noqa: N815 - BaseHTTPRequestHandler dispatch names
    do_PATCH = do_POST  # noqa: N815 - BaseHTTPRequestHandler dispatch names
    do_DELETE = do_POST  # noqa: N815 - BaseHTTPRequestHandler dispatch names
    do_HEAD = do_GET  # noqa: N815 - BaseHTTPRequestHandler dispatch names
    do_OPTIONS = do_GET  # noqa: N815 - BaseHTTPRequestHandler dispatch names

    @override
    def log_message(self, format: str, *args: object) -> None:
        pass


@final
class Arguments(argparse.Namespace):
    """CLI values narrowed before listener startup."""

    config: object = None


def stop_listener(_signum: int, _frame: object) -> None:
    """Leave the accept loop, then drain active request threads on server close."""
    _ = signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise KeyboardInterrupt


def main() -> None:
    """Load installed configuration and serve until interrupted."""
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(namespace=Arguments())
    config_path = args.config
    if not isinstance(config_path, Path):
        parser.error("--config must be a path")
    try:
        config = read_config(config_path)
    except (TypeError, ValueError, OSError) as error:
        parser.error(str(error))
    with GatewayServer(config) as server:
        _ = signal.signal(signal.SIGTERM, stop_listener)
        print(  # noqa: T201 - readiness record consumed by process-level clients
            json.dumps({"host": config.host, "port": server.server_port}), flush=True
        )
        with suppress(KeyboardInterrupt):
            server.serve_forever()


if __name__ == "__main__":
    main()
