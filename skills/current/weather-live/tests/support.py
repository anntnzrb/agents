"""Typed loopback service and CLI helpers for behavioral tests."""

import os
import subprocess
import sys
import threading
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import override
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
type Params = dict[str, list[str]]
type Request = tuple[str, Params, str | None]
type Handler = Callable[[str, Params], tuple[int, bytes]]


@contextmanager
def service(handler: Handler) -> Generator[tuple[list[Request], dict[str, str]]]:
    """Serve fixture responses on loopback and return recorded requests."""
    requests: list[Request] = []

    class Server(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            """Handle a fixture request."""
            path = urlparse(self.path)
            params = parse_qs(path.query)
            requests.append((path.path, params, self.headers.get("User-Agent")))
            status, payload = handler(path.path, params)
            self.send_response(status)
            self.end_headers()
            if payload:
                _ = self.wfile.write(payload)

        @override
        def log_message(self, format: str, *args: object) -> None:
            """Silence HTTP server logs."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        yield (
            requests,
            os.environ
            | dict.fromkeys(
                ("WEATHER_GEOCODE_URL", "WEATHER_FORECAST_URL", "WEATHER_AWC_URL"), base
            ),
        )
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def fixture(name: str) -> bytes:
    """Load a recorded service response."""
    return (ROOT / "tests" / "fixtures" / f"{name}.json").read_bytes()


def run(env: Mapping[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the actual CLI in the test interpreter."""
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "cli.py"), *args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
