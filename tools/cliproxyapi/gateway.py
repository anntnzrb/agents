"""Private inference facade: CLIProxyAPI chat and native System One classification.

Run with an installed JSON config. This listener trusts its private network;
public access must pass through the separately authenticated gateway.
"""

from __future__ import annotations

import argparse
import http.client
import io
import json
import select
import socket
import time
from dataclasses import dataclass
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import TypeGuard, final, override
from urllib.parse import SplitResult, unquote, urlsplit

BODY_LIMIT = 16 * 1024 * 1024
IO_TIMEOUT = 120
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


@dataclass(frozen=True, slots=True)
class ApiKeyEntry:
    api_key: str
    weight: int


@dataclass(frozen=True, slots=True)
class Config:
    host: str
    port: int
    upstream: str
    system_one_url: str
    api_key_entries: tuple[ApiKeyEntry, ...]
    models: frozenset[str]


def endpoint(value: object, *, origin_only: bool = False) -> str:
    """Validate configured fixed destinations, never client-provided URLs."""
    if not isinstance(value, str):
        raise TypeError("Upstream URL must be a string")
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
        raise ValueError("Upstream must be an HTTP(S) URL without credentials or query")
    _ = parsed.port
    return value.rstrip("/")


def decode_json(value: str | bytes) -> object:
    """Contain stdlib's untyped decode result at the JSON boundary."""
    # Stdlib returns Any; callers receive unknown data and narrow it immediately.
    return json.loads(value)  # pyright: ignore[reportAny]


def is_object(value: object) -> TypeGuard[dict[str, object]]:
    # JSON decoding guarantees that object keys are strings.
    return isinstance(value, dict)


def is_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def is_strings(value: object) -> TypeGuard[list[str]]:
    return is_list(value) and all(isinstance(item, str) for item in value)


def read_key_entry(value: object) -> ApiKeyEntry:
    """Validate each key and weight before building the request pool."""
    if not is_object(value):
        raise ValueError("systemOne.apiKeyEntries entries must be objects")
    key, weight = value.get("apiKey"), value.get("weight", 1)
    if (
        not isinstance(key, str)
        or not key
        or any(not 33 <= ord(char) <= 126 for char in key)
    ):
        raise ValueError(
            "systemOne.apiKeyEntries keys must be nonempty printable ASCII tokens"
        )
    if (
        isinstance(weight, bool)
        or not isinstance(weight, int)
        or not 1 <= weight <= 1_000_000
    ):
        raise ValueError(
            "systemOne.apiKeyEntries weights must be integers from 1 to 1000000"
        )
    return ApiKeyEntry(key, weight)


def read_config(path: Path) -> Config:
    """Narrow the installed config once before opening a listener."""
    raw = decode_json(path.read_text(encoding="utf-8"))
    if not is_object(raw):
        raise TypeError("Gateway config must be an object")
    listen = raw.get("listen")
    classifier = raw.get("systemOne")
    if not is_object(listen) or not is_object(classifier):
        raise TypeError("Gateway requires listen and systemOne objects")
    host, port = listen.get("host"), listen.get("port")
    entries = classifier.get("apiKeyEntries")
    models = classifier.get("models")
    if not isinstance(host, str) or not host:
        raise ValueError("listen.host must be a nonempty string")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("listen.port must be an integer from 0 to 65535")
    if not is_list(entries) or not entries:
        raise ValueError("systemOne.apiKeyEntries must be a nonempty list")
    key_entries = tuple(read_key_entry(entry) for entry in entries)
    if len({entry.api_key for entry in key_entries}) != len(key_entries):
        raise ValueError("systemOne.apiKeyEntries must contain unique keys")
    if not is_strings(models) or not models or not all(models):
        raise ValueError("systemOne.models must be a nonempty list of model names")
    system_url = endpoint(classifier.get("baseUrl"))
    parsed = urlsplit(system_url)
    if parsed.scheme != "https" and parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ValueError("System One requires HTTPS except for loopback tests")
    if len(set(models)) != len(models) or any(
        model.strip() != model or any(char.isspace() for char in model)
        for model in models
    ):
        raise ValueError("System One model names must be unique and whitespace-free")
    return Config(
        host,
        port,
        endpoint(raw.get("upstream"), origin_only=True),
        system_url + "/systemone",
        key_entries,
        frozenset(models),
    )


def excluded_headers(headers: Message) -> frozenset[str]:
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
        self.entries = entries
        self.current = [0 for _ in entries]
        self.total = sum(entry.weight for entry in entries)
        self.lock = Lock()

    def pick(self) -> str:
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
    def __init__(self, config: Config) -> None:
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
        super().__init__(sock, debuglevel, method, url)
        self.fp.close()
        self.fp: io.BufferedReader = io.BufferedReader(
            sock.makefile("rb", buffering=0), buffer_size=1
        )


@final
class ProxyHandler(BaseHTTPRequestHandler):
    rbufsize = 0
    connection: socket.socket

    @override
    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(IO_TIMEOUT)

    def error(self, status: int, message: str) -> None:
        payload = json.dumps({"error": {"message": message}}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        _ = self.wfile.write(payload)

    def body(self, *, classifier: bool) -> bytes | None:
        lengths = self.headers.get_all("Content-Length", [])
        encodings = self.headers.get_all("Transfer-Encoding", [])
        chunked = len(encodings) == 1 and encodings[0].strip().lower() == "chunked"
        if len(lengths) > 1 or (encodings and (not chunked or lengths)):
            self.error(400, "Unsupported or ambiguous request framing")
            return None
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
                    raise ValueError("Incomplete request body")
                received.extend(piece)
            return bytes(received)

        def line() -> bytes:
            budget()
            value = self.rfile.readline(8193)
            if len(value) > 8192 or not value.endswith(b"\r\n"):
                raise ValueError("Invalid chunk framing")
            return value

        try:
            received = bytearray()
            if chunked:
                while True:
                    size_text = line().split(b";", 1)[0].strip()
                    if not size_text or any(
                        char not in b"0123456789abcdefABCDEF" for char in size_text
                    ):
                        raise ValueError("Invalid chunk size")
                    size = int(size_text, 16)
                    if classifier and len(received) + size > BODY_LIMIT:
                        self.error(413, "Request body exceeds 16 MiB")
                        return None
                    if not size:
                        trailer_size = 0
                        while trailer := line():
                            trailer_size += len(trailer)
                            if trailer_size > 65536:
                                raise ValueError("Trailers exceed 64 KiB")
                            if trailer == b"\r\n":
                                break
                        break
                    received.extend(exact(size))
                    if exact(2) != b"\r\n":
                        raise ValueError("Invalid chunk terminator")
            else:
                length = int(lengths[0]) if lengths else 0
                if length < 0:
                    raise ValueError("Invalid Content-Length")
                if classifier and length > BODY_LIMIT:
                    self.error(413, "Request body exceeds 16 MiB")
                    return None
                received.extend(exact(length))
            self.connection.settimeout(IO_TIMEOUT)
            return bytes(received)
        except TimeoutError:
            self.error(408, "Request body timed out")
        except ValueError as error:
            self.error(400, str(error))
        return None

    def forward(self) -> None:
        parsed = urlsplit(self.path)
        classifier = self.command == "POST" and self.path == "/v1/systemone"
        decoded_path = unquote(parsed.path)
        safe_path = (
            not any(part in {".", ".."} for part in decoded_path.split("/"))
            and "\\" not in decoded_path
            and "%" not in decoded_path
        )
        ordinary = (
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
            or not (classifier or ordinary)
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
            raise TypeError("Expected GatewayServer")
        config = server.config
        if classifier:
            try:
                payload = decode_json(body)
            except (ValueError, UnicodeError):
                self.error(400, "System One body must be JSON")
                return
            if not is_object(payload) or not isinstance(payload.get("model"), str):
                self.error(400, "System One requires a string model")
                return
            if payload["model"] not in config.models:
                self.error(403, "System One model is not allowed")
                return
            url = config.system_one_url
            headers = {
                "Authorization": f"Bearer {server.key_pool.pick()}",
                "Content-Type": "application/json",
            }
        else:
            url = config.upstream + self.path
            excluded = excluded_headers(self.headers) | {
                "host",
                "content-length",
                "authorization",
                "cookie",
                "x-api-key",
            }
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in excluded
            }
            headers["Authorization"] = "Bearer keyless"
            if websocket:
                headers["Connection"] = "Upgrade"
                headers["Upgrade"] = "websocket"
        self.relay(urlsplit(url), body, headers, websocket=websocket)

    def relay(
        self, url: SplitResult, body: bytes, headers: dict[str, str], *, websocket: bool
    ) -> None:
        connection_type = (
            http.client.HTTPSConnection
            if url.scheme == "https"
            else http.client.HTTPConnection
        )
        # http.client never follows redirects and ignores ambient proxy settings.
        connection = connection_type(url.hostname or "", url.port, timeout=IO_TIMEOUT)
        connection.response_class = UnbufferedResponse
        upstream_socket = None
        started = False
        try:
            target = url.path + ("?" + url.query if url.query else "")
            connection.request(self.command, target, body=body, headers=headers)
            upstream_socket = connection.sock
            with connection.getresponse() as response:
                upgraded = websocket and response.status == 101
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
                started = True
                if upgraded and upstream_socket is not None:
                    self.wfile.flush()
                    self.tunnel(upstream_socket)
                    return
                # HTTP/1.0 close delimits the body after stripping chunk framing.
                while chunk := response.read1(65536):
                    _ = self.wfile.write(chunk)
                    self.wfile.flush()
        except (OSError, http.client.HTTPException):
            if not started:
                _ = self.error(502, "Inference upstream is unavailable")
        finally:
            connection.close()
            if upstream_socket is not None:
                _ = upstream_socket.close()

    def tunnel(self, upstream: socket.socket) -> None:
        """Relay opaque frames with bounded idle and write waits."""
        peers = {self.connection: upstream, upstream: self.connection}
        while ready := select.select(list(peers), [], [], IO_TIMEOUT)[0]:
            for source in ready:
                chunk = source.recv(65536)
                if not chunk:
                    return
                _ = peers[source].sendall(chunk)

    def do_GET(self) -> None:
        self.forward()

    def do_POST(self) -> None:
        self.forward()

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST
    do_HEAD = do_GET
    do_OPTIONS = do_GET

    @override
    def log_message(self, format: str, *args: object) -> None:
        pass


@final
class Arguments(argparse.Namespace):
    config: object = None


def main() -> None:
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
        print(json.dumps({"host": config.host, "port": server.server_port}), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
