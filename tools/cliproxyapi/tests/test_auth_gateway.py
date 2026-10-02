"""Wire-level tests for the public Funnel gate; listeners are isolated loopback fakes."""

import http.client
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "auth-gateway.py"
TOKEN = "funnel-" + "0" * 32


def free_port():
    with closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def gate():
    seen = queue.Queue()

    class Upstream(BaseHTTPRequestHandler):
        def respond(self):
            seen.put((self.command, self.path, dict(self.headers)))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"upstream")

        do_GET = do_POST = do_PUT = do_DELETE = respond

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Upstream) as upstream:
        thread = threading.Thread(target=upstream.serve_forever)
        thread.start()
        port = free_port()
        env = {
            **os.environ,
            "GATEWAY_SECRET": TOKEN,
            "CLIPROXY_UPSTREAM": f"http://127.0.0.1:{upstream.server_port}",
            "GATEWAY_PORT": str(port),
        }
        with subprocess.Popen([sys.executable, str(SCRIPT)], env=env) as process:
            try:
                deadline = time.monotonic() + 10
                while True:
                    try:
                        with closing(socket.create_connection(("127.0.0.1", port), 0.2)):
                            break
                    except OSError:
                        if time.monotonic() > deadline or process.poll() is not None:
                            raise
                        time.sleep(0.05)
                yield port, seen
            finally:
                process.terminate()
                process.wait(5)
                upstream.shutdown()
                thread.join()


def request(port, method, path, token=TOKEN):
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as client:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        client.request(method, path, body=b"{}" if method == "POST" else None, headers=headers)
        response = client.getresponse()
        return response.status, response.read()


def test_inference_is_forwarded_with_the_token(gate):
    port, seen = gate
    assert request(port, "POST", "/v1/chat/completions")[0] == 200
    method, path, headers = seen.get(timeout=1)
    assert (method, path) == ("POST", "/v1/chat/completions")
    assert headers["Authorization"] == "Bearer keyless"


def test_inference_without_the_token_is_unauthorized(gate):
    port, seen = gate
    assert request(port, "GET", "/v1/models", token=None)[0] == 401
    assert seen.empty()


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/management.html"),
        ("GET", "/management.html?safe-mode=configure"),
        ("GET", "/v0/management/config"),
        ("PUT", "/v0/management/config"),
        ("POST", "/v8/management/requests/api-call"),
        ("GET", "/v8/management"),
        ("GET", "/v0/resource/plugins/quota/card.js"),
        ("GET", "//v0/management/config"),
        ("GET", "/v0//management/config"),
        ("GET", "/%76%30/management/config"),
        ("GET", "/v0/management%2Fconfig"),
    ],
)
def test_management_routes_never_leave_the_tailnet(gate, method, path):
    """A valid client token still cannot reach the panel from the internet."""
    port, seen = gate
    assert request(port, method, path)[0] == 404
    assert seen.empty()
