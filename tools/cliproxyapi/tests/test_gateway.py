"""Wire-level tests; all listeners and upstreams are isolated loopback fakes."""

import gzip
import http.client
import json
import queue
import socket
import struct
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
OPENAI_CATALOG = [
    {"id": "chat-model", "object": "model", "owned_by": "openai"},
    {"id": "claude-opus-5-5", "object": "model", "owned_by": "anthropic"},
    {"id": "claude-opus-5-5-high", "object": "model", "owned_by": "antigravity"},
    {"id": "pool/vendor/new-model", "object": "model", "owned_by": "pool"},
    {"id": "claude-invalid-list", "owned_by": []},
    {"id": "claude-invalid-object", "owned_by": {}},
]
# CLIProxyAPI's Codex-shaped catalog carries per-model limits.
CODEX_CATALOG = [
    {
        "slug": "chat-model",
        "context_window": 272000,
        "input_modalities": ["text", "image"],
    },
    {
        "slug": "claude-opus-5-5",
        "context_window": 1000000,
        "input_modalities": ["text"],
    },
    {"slug": "claude-opus-5-5-high", "context_window": 200000},
]


@contextmanager
def upstream():
    requests = queue.Queue()
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def json_response(self, status, payload):
            body = json.dumps(payload).encode()
            compress = "gzip" in self.headers.get("Accept-Encoding", "")
            if compress:
                body = gzip.compress(body)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if compress:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
            elif self.path.startswith("/v1/models?client_version="):
                self.json_response(
                    int(self.headers.get("X-Test-Catalog-Status", "200")),
                    {"models": CODEX_CATALOG},
                )
            elif self.path.startswith("/v1/models"):
                self.json_response(
                    int(self.headers.get("X-Test-Listing-Status", "200")),
                    {"object": "list", "data": OPENAI_CATALOG},
                )
            elif self.path.startswith("/v1/chat/completions"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b"data: fir")
                self.wfile.flush()
                release.wait(5)
                self.wfile.write(b"st\n\ndata: [DONE]\n\n")
            elif self.path == "/v1/responses?delayed":
                release.wait(5)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ordinary")
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ordinary")

        do_POST = respond
        do_GET = respond
        do_PUT = respond
        do_OPTIONS = respond

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


@contextmanager
def gateway_process(config, *, fast_select=False):
    command = [sys.executable, str(SCRIPT), "--config", str(config)]
    if fast_select:
        # Accelerate only the socket wait clock, not the gateway implementation.
        command = [
            sys.executable,
            "-c",
            "import runpy,select,sys; original=select.select; "
            "select.select=lambda r,w,x,timeout=None: original(r,w,x,0.05); "
            "sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')",
            str(SCRIPT),
            "--config",
            str(config),
        ]
    with subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
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
            yield process, json.loads(line)["port"]
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


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
        with gateway_process(config) as (_, port):
            yield port, cpa_requests, router_requests, release


def request(port, method, path, body=None, headers=None):
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as client:
        client.request(method, path, body=body, headers=headers or {})
        response = client.getresponse()
        return response.status, dict(response.headers), response.read()


@pytest.fixture
def relay_config(tmp_path):
    with upstream() as (url, requests, release):
        config = tmp_path / "gateway.json"
        config.write_text(
            json.dumps(
                {
                    "listen": {"host": "127.0.0.1", "port": 0},
                    "upstream": url,
                    "systemOne": {
                        "baseUrl": url,
                        "apiKeyEntries": [{"apiKey": "test-key"}],
                        "models": [MODEL],
                    },
                }
            ),
            encoding="utf-8",
        )
        yield config, requests, release


def test_client_reset_before_headers_is_not_an_upstream_error(relay_config):
    config, requests, release = relay_config
    with gateway_process(config) as (process, port):
        with socket.create_connection(("127.0.0.1", port), timeout=3) as client:
            client.sendall(
                b"GET /v1/responses?delayed HTTP/1.0\r\nHost: localhost\r\n\r\n"
            )
            assert requests.get(timeout=1)[1] == "/v1/responses?delayed"
            client.setsockopt(
                socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
            )
        release.set()
        # A second response proves the facade still serves after the reset.
        assert request(port, "GET", "/v1/embeddings")[0] == 200
        process.terminate()
        process.wait(timeout=5)
        assert process.stderr.read() == ""


def test_upstream_disconnect_before_headers_still_returns_502(relay_config):
    config, _, _ = relay_config
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        data = json.loads(config.read_text())
        data["upstream"] = f"http://127.0.0.1:{unavailable.getsockname()[1]}"
        config.write_text(json.dumps(data), encoding="utf-8")
        with gateway_process(config) as (_, port):
            status, _, body = request(port, "GET", "/v1/embeddings")
            assert status == 502
            assert (
                json.loads(body)["error"]["message"]
                == "Inference upstream is unavailable"
            )


def test_sigterm_drains_inflight_stream(relay_config):
    config, _, release = relay_config
    with gateway_process(config) as (process, port):
        with closing(
            http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        ) as client:
            client.request("POST", "/v1/chat/completions", b"{}")
            response = client.getresponse()
            assert response.read(9) == b"data: fir"
            process.terminate()
            # Wait until shutdown closes the listener, without releasing the stream.
            for _ in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.05):
                        threading.Event().wait(0.01)
                except ConnectionRefusedError:
                    break
            else:
                pytest.fail("Gateway did not stop accepting connections")
            assert process.poll() is None
            release.set()
            assert response.read() == b"st\n\ndata: [DONE]\n\n"
        assert process.wait(timeout=5) == 0


def test_websocket_silence_does_not_close_tunnel(relay_config):
    config, _, _ = relay_config
    with gateway_process(config, fast_select=True) as (_, port):
        with socket.create_connection(("127.0.0.1", port), timeout=3) as client:
            client.sendall(
                b"GET /v1/responses HTTP/1.1\r\nHost: localhost\r\n"
                b"Connection: Upgrade\r\nUpgrade: websocket\r\n\r\n"
            )
            received = b""
            while b"\r\n\r\n" not in received:
                received += client.recv(4096)
            _, body = received.split(b"\r\n\r\n", 1)
            while len(body) < 4:
                body += client.recv(4096)
            assert body == b"\x81\x02hi"
            client.settimeout(0.2)
            with pytest.raises(TimeoutError):
                client.recv(1)
            frame = b"\x81\x82abcd\x09\x0b"
            client.sendall(frame)
            client.settimeout(3)
            echoed = b""
            while len(echoed) < len(frame):
                echoed += client.recv(4096)
            assert echoed == frame


def test_classifier_discovery_is_local_nonsecret_and_separate(gateway):
    port, cpa, router, _ = gateway
    status, headers, body = request(port, "GET", "/v1/systemone/models")
    assert status == 200
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body) == {"object": "list", "data": [{"id": MODEL}]}
    assert b"server-secret" not in body
    assert cpa.empty() and router.empty()
    status, _, body = request(port, "GET", "/v1/models")
    assert status == 200
    assert MODEL not in {entry["id"] for entry in json.loads(body)["data"]}


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


def test_model_list_reports_limits_and_endpoints(gateway):
    """Clients read context limits and Anthropic routing from the OpenAI model list."""
    port, cpa, _, _ = gateway
    status, _, body = request(port, "GET", "/v1/models")
    assert status == 200
    models = {model["id"]: model for model in json.loads(body)["data"]}
    assert models["chat-model"]["context_length"] == 272000
    assert models["chat-model"]["supported_endpoint_types"] == ["openai"]
    # Claude served by Anthropic credentials speaks Anthropic Messages natively.
    assert models["claude-opus-5-5"]["context_length"] == 1000000
    assert models["claude-opus-5-5"]["supported_endpoint_types"] == [
        "anthropic",
        "openai",
    ]
    # The same family through another pool may not serve /v1/messages.
    assert models["claude-opus-5-5-high"]["supported_endpoint_types"] == ["openai"]
    # Models the Codex catalog omits keep their entry without invented limits.
    assert "context_length" not in models["pool/vendor/new-model"]
    assert models["pool/vendor/new-model"]["owned_by"] == "pool"
    assert models["claude-invalid-list"]["supported_endpoint_types"] == ["openai"]
    assert models["claude-invalid-object"]["supported_endpoint_types"] == ["openai"]
    paths = {cpa.get(timeout=1)[1], cpa.get(timeout=1)[1]}
    assert paths == {"/v1/models", "/v1/models?client_version="}


def test_compressed_client_request_still_receives_enriched_catalog(gateway):
    port, cpa, _, _ = gateway
    status, headers, body = request(
        port, "GET", "/v1/models", headers={"Accept-Encoding": "gzip"}
    )
    assert status == 200 and "Content-Encoding" not in headers
    models = {model["id"]: model for model in json.loads(body)["data"]}
    assert models["chat-model"]["context_length"] == 272000
    assert all(cpa.get(timeout=1)[2]["Accept-Encoding"] == "identity" for _ in range(2))


def test_model_list_survives_metadata_catalog_failure(gateway):
    port, _, _, _ = gateway
    status, _, body = request(
        port, "GET", "/v1/models", headers={"X-Test-Catalog-Status": "503"}
    )
    assert status == 200
    models = {model["id"]: model for model in json.loads(body)["data"]}
    assert set(models) == {model["id"] for model in OPENAI_CATALOG}
    assert all("context_length" not in model for model in models.values())
    assert models["claude-opus-5-5"]["supported_endpoint_types"] == [
        "anthropic",
        "openai",
    ]


def test_model_list_preserves_upstream_failure_status(gateway):
    port, _, _, _ = gateway
    status, _, body = request(
        port, "GET", "/v1/models", headers={"X-Test-Listing-Status": "503"}
    )
    assert status == 503
    assert json.loads(body)["data"] == OPENAI_CATALOG


def test_catalog_and_sse_passthrough(gateway):
    port, cpa, _, release = gateway
    assert json.loads(request(port, "GET", "/v1/models?client_version=pi")[2]) == {
        "models": CODEX_CATALOG
    }
    assert cpa.get(timeout=1)[1] == "/v1/models?client_version=pi"
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
        ("GET", "/management.html"),
        ("GET", "/v0/management/config"),
        ("PUT", "/v0/management/config"),
        ("POST", "/v8/management/requests/api-call"),
        ("OPTIONS", "/v8/management/config"),
        ("GET", "/v0/resource/plugins/quota/card.js"),
    ],
)
def test_management_routes_reach_cliproxyapi_with_their_key(gateway, method, path):
    """The panel authenticates to CLIProxyAPI with its own key, so it passes through."""
    port, cpa, router, _ = gateway
    status, _, _ = request(
        port,
        method,
        path,
        b"{}" if method in {"POST", "PUT"} else None,
        {"Authorization": "Bearer panel-key", "X-Management-Key": "panel-key"},
    )
    assert status == 200
    seen_method, seen_path, headers, _ = cpa.get(timeout=1)
    assert (seen_method, seen_path) == (method, path)
    assert headers["Authorization"] == "Bearer panel-key"
    assert headers["X-Management-Key"] == "panel-key"
    assert router.empty()


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/v1/management/config"),
        ("GET", "/v0/managementx"),
        ("GET", "/management.html.bak"),
        ("GET", "/v1/../v0/management/config"),
        ("GET", "/v0/management/../../v1/models"),
        ("GET", "/v0/management/%2e%2e/config"),
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
        client.request("GET", "/v1/embeddings")
        response = client.getresponse()
        assert response.status == 200
        assert response.read() == b"ordinary"
    assert cpa.get(timeout=1)[1] == "/v1/embeddings"


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
