"""Wire-level tests; all listeners and upstreams are isolated loopback fakes."""

import http.client
import json
import queue
import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "gateway.py"
MODEL = "typesafe/jev-1.13"


@contextmanager
def upstream():
    requests = queue.Queue()
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def respond(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.put((self.command, self.path, dict(self.headers), body))
            if self.headers.get("Upgrade") == "websocket":
                self.wfile.write(
                    b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: fake-accept\r\n\r\n"
                    + b"\x81\x02hi"
                )
                self.wfile.flush()
                self.wfile.write(self.rfile.read(8))
                self.wfile.flush()
            elif self.path.endswith("/systemone"):
                payload = json.loads(body)
                mode = payload.get("state", "ok")
                status = {"budget": 402, "rate": 429, "redirect": 307}.get(mode, 200)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", "17")
                self.send_header("Location", "/stolen-secret")
                self.send_header("Connection", "X-Upstream-Private")
                self.send_header("X-Upstream-Private", "hidden")
                self.end_headers()
                self.wfile.write(
                    b'{"answers":{"spam":{"type":"noul","noul":0.75}},"usage":{"input_tokens":12,"output_tokens":0,"cost":0.000042}}'
                )
            elif self.path.startswith("/v1/models"):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"data":[{"id":"chat-model"}]}')
            elif self.path.startswith("/v1/chat/completions"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b"data: fir")
                self.wfile.flush()
                release.wait(5)
                self.wfile.write(b"st\n\ndata: [DONE]\n\n")
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ordinary")

        do_POST = respond
        do_GET = respond

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", requests, release
        finally:
            release.set()
            server.shutdown()
            thread.join()


@pytest.fixture
def gateway(tmp_path, request):
    with (
        upstream() as (cpa, cpa_requests, release),
        upstream() as (router, router_requests, _),
    ):
        config = tmp_path / "gateway.json"
        config.write_text(
            json.dumps(
                {
                    "listen": {
                        "host": "127.0.0.1"
                        if isinstance(getattr(request, "param", None), list)
                        else getattr(request, "param", "127.0.0.1"),
                        "port": 0,
                    },
                    "upstream": cpa,
                    "systemOne": {
                        "baseUrl": router + "/api/v1",
                        "apiKeyEntries": getattr(request, "param", None)
                        if isinstance(getattr(request, "param", None), list)
                        else [{"apiKey": "server-secret"}],
                        "models": [MODEL],
                    },
                }
            ),
            encoding="utf-8",
        )
        with subprocess.Popen(
            [sys.executable, str(SCRIPT), "--config", str(config)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as process:
            ready = queue.Queue()
            threading.Thread(
                target=lambda: ready.put(process.stdout.readline()), daemon=True
            ).start()
            try:
                line = ready.get(timeout=5)
                assert line, (
                    process.stderr.read()
                    if process.poll() is not None
                    else "Gateway did not start"
                )
                address = json.loads(line)
                yield address["port"], cpa_requests, router_requests, release
            finally:
                process.terminate()
                process.wait(timeout=5)


def request(port, method, path, body=None, headers=None):
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as client:
        client.request(method, path, body=body, headers=headers or {})
        response = client.getresponse()
        return response.status, dict(response.headers), response.read()


def test_native_protocol_and_credentials(gateway):
    port, _, router, _ = gateway
    body = b'{ "model": "typesafe/jev-1.13", "state": "ok", "questions": {"spam":{"type":"noul","description":"Is this spam?"}} }'
    status, headers, result = request(
        port,
        "POST",
        "/v1/systemone",
        body,
        {
            "Authorization": "Bearer client-secret",
            "Cookie": "session=private",
            "X-API-Key": "other-secret",
            "HTTP-Referer": "https://client.invalid",
            "Connection": "X-Private",
            "X-Private": "hidden",
        },
    )
    assert status == 200
    assert json.loads(result) == {
        "answers": {"spam": {"type": "noul", "noul": 0.75}},
        "usage": {"input_tokens": 12, "output_tokens": 0, "cost": 0.000042},
    }
    assert "X-Upstream-Private" not in headers
    method, path, sent, payload = router.get(timeout=1)
    assert (method, path, payload) == ("POST", "/api/v1/systemone", body)
    assert sent["Authorization"] == "Bearer server-secret"
    assert (
        "Cookie" not in sent
        and "X-API-Key" not in sent
        and "Http-Referer" not in sent
        and "X-Private" not in sent
    )


@pytest.mark.parametrize(
    "body,status",
    [
        (b"{", 400),
        (b"[]", 400),
        (b"{}", 400),
        (b'{"model":1}', 400),
        (b'{"model":"other"}', 403),
    ],
)
def test_invalid_classifier_requests(gateway, body, status):
    port, _, router, _ = gateway
    assert request(port, "POST", "/v1/systemone", body)[0] == status
    assert router.empty()


@pytest.mark.parametrize(
    "mode,status", [("budget", 402), ("rate", 429), ("redirect", 307)]
)
def test_native_errors_and_redirects(gateway, mode, status):
    port, _, router, _ = gateway
    actual, headers, body = request(
        port, "POST", "/v1/systemone", json.dumps({"model": MODEL, "state": mode})
    )
    assert actual == status
    assert headers["Retry-After"] == "17"
    assert json.loads(body)["usage"]["cost"] == 0.000042
    assert router.get(timeout=1)[1] == "/api/v1/systemone"
    assert router.empty()


def test_catalog_and_sse_passthrough(gateway):
    port, cpa, _, release = gateway
    assert (
        request(port, "GET", "/v1/models?client_version=1")[2]
        == b'{"data":[{"id":"chat-model"}]}'
    )
    assert cpa.get(timeout=1)[1] == "/v1/models?client_version=1"
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=2)) as client:
        client.request(
            "POST",
            "/v1/chat/completions?x=1",
            b"{}",
            {
                "Authorization": "Bearer client-secret",
                "Connection": "X-Private",
                "X-Private": "hidden",
                "Cookie": "private",
            },
        )
        response = client.getresponse()
        assert response.status == 200
        assert response.read(9) == b"data: fir"
        release.set()
        assert response.read() == b"st\n\ndata: [DONE]\n\n"
    _, path, headers, body = cpa.get(timeout=1)
    assert (path, body) == ("/v1/chat/completions?x=1", b"{}")
    assert headers["Authorization"] == "Bearer keyless"
    assert "X-Private" not in headers and "Cookie" not in headers


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/v0/management/config"),
        ("POST", "/v1/management/config"),
        ("GET", "/management.html"),
        ("GET", "/v1/../v0/management/config"),
        ("GET", "/v1/%2e%2e/v0/management/config"),
        ("POST", "/v1/systemone?upstream=evil"),
        ("POST", "/v1/systemone/"),
        ("GET", "/v1/systemone"),
    ],
)
def test_non_inference_routes_rejected(gateway, method, path):
    port, cpa, router, _ = gateway
    assert request(port, method, path, b"{}")[0] == 404
    assert cpa.empty() and router.empty()


def test_unsupported_framing_and_oversized_body(gateway):
    port, cpa, router, _ = gateway
    assert (
        request(port, "POST", "/v1/systemone", b"", {"Transfer-Encoding": "gzip"})[0]
        == 400
    )
    assert (
        request(port, "POST", "/v1/systemone", b"", {"Content-Length": "999999999"})[0]
        == 413
    )
    assert cpa.empty() and router.empty()


@pytest.mark.parametrize(
    "path",
    [
        "/v1/responses?model=chat",
        "/v1/realtime?model=chat",
        "/v1/live/call-123",
        "/v1/realtime/calls/call-123",
    ],
)
def test_websocket_upgrade_preserves_early_frames(gateway, path):
    port, cpa, router, _ = gateway
    # Send handshake and masked frame together to catch buffered-reader loss.
    frame = b"\x81\x82abcd\x09\x0b"
    with socket.create_connection(("127.0.0.1", port), timeout=3) as client:
        client.sendall(
            (
                f"GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nAuthorization: Bearer client\r\nSec-WebSocket-Key: fake-key\r\nSec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
            + frame
        )
        received = b""
        while b"\r\n\r\n" not in received:
            received += client.recv(4096)
        header, body = received.split(b"\r\n\r\n", 1)
        assert b"101 Switching Protocols" in header
        while len(body) < 12:
            body += client.recv(4096)
        assert body == b"\x81\x02hi" + frame
    _, sent_path, headers, _ = cpa.get(timeout=1)
    assert sent_path == path and headers["Authorization"] == "Bearer keyless"
    assert headers["Sec-WebSocket-Key"] == "fake-key"
    assert router.empty()


@pytest.mark.parametrize("gateway", ["::1"], indirect=True)
def test_ipv6_listener(gateway):
    port, cpa, _, _ = gateway
    with closing(http.client.HTTPConnection("::1", port, timeout=3)) as client:
        client.request("GET", "/v1/models")
        response = client.getresponse()
        assert response.status == 200
        assert response.read() == b'{"data":[{"id":"chat-model"}]}'
    assert cpa.get(timeout=1)[1] == "/v1/models"


def test_chunked_cpa_upload(gateway):
    port, cpa, _, _ = gateway
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=3)) as client:
        client.request("POST", "/v1/responses", body=[b"{", b"}"], encode_chunked=True)
        response = client.getresponse()
        assert response.status == 200
        assert response.read() == b"ordinary"
    _, path, headers, body = cpa.get(timeout=1)
    assert path == "/v1/responses" and body == b"{}"
    assert headers["Content-Length"] == "2"
    assert "Transfer-Encoding" not in headers


@pytest.mark.parametrize(
    "wire", [b"zz\r\n", b"1\r\nxNO", b"2\r\nx", b"0\r\nunterminated"]
)
def test_malformed_chunked_body(gateway, wire):
    port, cpa, router, _ = gateway
    with socket.create_connection(("127.0.0.1", port), timeout=3) as client:
        client.sendall(
            b"POST /v1/responses HTTP/1.1\r\nHost: localhost\r\nTransfer-Encoding: chunked\r\n\r\n"
            + wire
        )
        client.shutdown(socket.SHUT_WR)
        assert client.recv(4096).startswith(b"HTTP/1.0 400")
    assert cpa.empty() and router.empty()


def test_large_cpa_upload_preserved(gateway):
    port, cpa, _, _ = gateway
    payload = b"x" * (16 * 1024 * 1024 + 1)
    status, _, result = request(port, "POST", "/v1/images/edits", payload)
    assert status == 200 and result == b"ordinary"
    assert cpa.get(timeout=1)[3] == payload


@pytest.mark.parametrize(
    "gateway",
    [[{"apiKey": "first-key", "weight": 2}, {"apiKey": "second-key"}]],
    indirect=True,
)
def test_weighted_key_pool_is_thread_safe(gateway):
    port, _, router, _ = gateway

    def classify(_index):
        return request(port, "POST", "/v1/systemone", json.dumps({"model": MODEL}))[0]

    with ThreadPoolExecutor(max_workers=8) as workers:
        assert list(workers.map(classify, range(30))) == [200] * 30
    keys = [router.get(timeout=1)[2]["Authorization"] for _ in range(30)]
    assert keys.count("Bearer first-key") == 20
    assert keys.count("Bearer second-key") == 10


@pytest.mark.parametrize(
    "gateway", [[{"apiKey": "first-key"}, {"apiKey": "second-key"}]], indirect=True
)
def test_rejected_request_does_not_consume_pool_turn(gateway):
    port, _, router, _ = gateway
    payload = json.dumps({"model": MODEL})
    assert request(port, "POST", "/v1/systemone", payload)[0] == 200
    assert request(port, "POST", "/v1/systemone", b'{"model":"forbidden"}')[0] == 403
    assert request(port, "POST", "/v1/systemone", payload)[0] == 200
    assert [router.get(timeout=1)[2]["Authorization"] for _ in range(2)] == [
        "Bearer first-key",
        "Bearer second-key",
    ]


@pytest.mark.parametrize(
    "entries",
    [
        [],
        [{"apiKey": ""}],
        [{"apiKey": "key\r\ninjection"}],
        [{"apiKey": "key\x00"}],
        [{"apiKey": "nonascii-é"}],
        [{"apiKey": "key", "weight": True}],
        [{"apiKey": "key", "weight": 0}],
        [{"apiKey": "key", "weight": 1000001}],
        [{"apiKey": "key", "weight": 1.5}],
        [{"apiKey": "same"}, {"apiKey": "same"}],
    ],
)
def test_invalid_key_pool_rejected_before_listening(tmp_path, entries):
    config = tmp_path / "gateway.json"
    config.write_text(
        json.dumps(
            {
                "listen": {"host": "127.0.0.1", "port": 0},
                "upstream": "http://127.0.0.1:1",
                "systemOne": {
                    "baseUrl": "http://127.0.0.1:1/api/v1",
                    "apiKeyEntries": entries,
                    "models": [MODEL],
                },
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--config", str(config)],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    assert result.returncode == 2
    assert not result.stdout
    assert "apiKeyEntries" in result.stderr
