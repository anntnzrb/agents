"""Bearer-token gate in front of the keyless CLIProxyAPI gateway.

Tailscale Funnel publishes this listener to the internet so hosted clients
(Amp) can reach the gateway. CLIProxyAPI itself accepts any client key, so the
token checked here is the only credential on the public path. Sync installs
this file and renders GATEWAY_SECRET and CLIPROXY_UPSTREAM into its env file.

The management panel stays on the private network: its routes are refused
here before authentication, so a leaked client token never reaches it.
"""

import hmac
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

SECRET_KEY = os.environ["GATEWAY_SECRET"].encode()
UPSTREAM = os.environ["CLIPROXY_UPSTREAM"]
# The Funnel mapping proxies to 127.0.0.1:8318; the override exists for tests.
LISTEN = ("127.0.0.1", int(os.environ.get("GATEWAY_PORT", "8318")))
# CLIProxyAPI's management surface (its server_middleware.go).
MANAGEMENT_PREFIXES = ("/v0/management", "/v8/management", "/v0/resource/plugins")


def management_route(raw_path):
    """Match on the decoded path so encoded or doubled slashes cannot hide a route."""
    path = "/" + "/".join(
        part for part in unquote(urlsplit(raw_path).path).split("/") if part
    )
    return path.startswith("/management") or any(
        path == prefix or path.startswith(prefix + "/") for prefix in MANAGEMENT_PREFIXES
    )


class ProxyHandler(BaseHTTPRequestHandler):
    def authorized(self):
        auth = self.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.startswith("Bearer ") else ""
        if hmac.compare_digest(token.encode(), SECRET_KEY):
            return True
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(
            b'{"error":{"message":"Unauthorized: invalid API key",'
            b'"type":"authentication_error","code":"unauthorized"}}'
        )
        return False

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def forward(self, method):
        if management_route(self.path):
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"Not found"}}')
            return
        if not self.authorized():
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else None
        headers = {
            k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection")
        }
        headers["Authorization"] = "Bearer keyless"
        request = urllib.request.Request(
            UPSTREAM + self.path, data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request) as response:
                self.relay(response.status, response.headers, response)
        except urllib.error.HTTPError as error:
            with error:
                self.relay(error.code, error.headers, error)
        except OSError as error:
            payload = f'{{"error":{{"message":"Gateway Bad Gateway: {error}"}}}}'.encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

    def relay(self, status, headers, body):
        # Stream the body as it arrives: SSE responses must reach the client
        # token by token, not after generation ends. HTTP/1.0 (the handler's
        # default) delimits the body by closing the connection.
        self.send_response(status)
        for key, value in headers.items():
            if key.lower() not in ("transfer-encoding", "content-length", "connection"):
                self.send_header(key, value)
        self.end_headers()
        try:
            while chunk := body.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
        except OSError:
            # client went away or upstream dropped mid-stream; headers are
            # already sent, so closing the connection is the only signal left
            return

    def do_GET(self):
        self.forward("GET")

    def do_POST(self):
        self.forward("POST")

    def do_PUT(self):
        self.forward("PUT")

    def do_DELETE(self):
        self.forward("DELETE")

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(LISTEN, ProxyHandler).serve_forever()
