from __future__ import annotations

import http.server
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from odoo_rpc import (
    OdooRpcClient,
    OdooRpcConfig,
    json_rpc,
    load_env,
    main,
    parse_env_file,
)


def _stub(mock: MagicMock, dotted: str, value: object) -> None:
    """Wire one nested mock attribute; dotted keys need dynamic unpacking."""
    mock.configure_mock(**{dotted: value})


class TestOdooRpcConfig(unittest.TestCase):
    def test_missing_required_fields_raise_value_error(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(ValueError, match="Missing Odoo RPC URL"),
        ):
            _ = OdooRpcConfig.from_env()

    def test_loopback_plaintext_http_allowed(self) -> None:
        cfg = OdooRpcConfig.from_env(
            url="http://127.0.0.1:8069",
            database="testdb",
            user="testuser",
            token="secret",  # noqa: S106 - test fixture credential
        )
        assert cfg.url == "http://127.0.0.1:8069/jsonrpc"

    def test_remote_plaintext_http_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="Plaintext HTTP is only permitted for loopback"
        ):
            _ = OdooRpcConfig.from_env(
                url="http://remote.erp.com/jsonrpc",
                database="testdb",
                user="testuser",
                token="secret",  # noqa: S106 - test fixture credential
            )

    def test_remote_insecure_tls_rejected(self) -> None:
        with pytest.raises(ValueError, match="Disabling SSL verification"):
            _ = OdooRpcConfig.from_env(
                url="https://remote.erp.com/jsonrpc",
                database="testdb",
                user="testuser",
                token="secret",  # noqa: S106 - test fixture credential
                verify_ssl=False,
            )

    def test_userinfo_in_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="embedded user credentials"):
            _ = OdooRpcConfig.from_env(
                url="https://admin:pass@test.erp.com/jsonrpc",
                database="testdb",
                user="testuser",
                token="secret",  # noqa: S106 - test fixture credential
            )

    def test_query_and_fragment_in_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="query parameters"):
            _ = OdooRpcConfig.from_env(
                url="https://test.erp.com/jsonrpc?debug=1",
                database="testdb",
                user="testuser",
                token="secret",  # noqa: S106 - test fixture credential
            )
        with pytest.raises(ValueError, match="URL fragments"):
            _ = OdooRpcConfig.from_env(
                url="https://test.erp.com/jsonrpc#section",
                database="testdb",
                user="testuser",
                token="secret",  # noqa: S106 - test fixture credential
            )

    def test_invalid_url_schemes_rejected(self) -> None:
        for invalid_url in (
            "file:///etc/passwd",
            "gopher://127.0.0.1",
            "ftp://127.0.0.1",
        ):
            with (
                self.subTest(url=invalid_url),
                pytest.raises(ValueError, match="Invalid Odoo RPC URL"),
            ):
                _ = OdooRpcConfig.from_env(
                    url=invalid_url,
                    database="testdb",
                    user="testuser",
                    token="tok",  # noqa: S106 - test fixture credential
                )

    def test_missing_explicit_token_path_fails_closed(self) -> None:
        with pytest.raises(FileNotFoundError, match="Explicit token file not found"):
            _ = OdooRpcConfig.from_env(
                url="https://test.erp.com/jsonrpc",
                database="testdb",
                user="testuser",
                token_path=Path("/nonexistent/path/to/token"),
            )

    def test_parse_env_file(self) -> None:
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            _ = f.write("# Sample env\n")
            _ = f.write('export ODOO_RPC_URL="https://env.erp.com/jsonrpc"\n')
            _ = f.write("ODOO_RPC_DB=envdb\n")
            _ = f.write("ODOO_RPC_USER='envuser'\n")
            _ = f.write("INVALID KEY=bad\n")
            env_file = Path(f.name)

        try:
            with patch.dict(os.environ, {}, clear=True):
                assert parse_env_file(env_file)
                assert os.environ.get("ODOO_RPC_URL") == "https://env.erp.com/jsonrpc"
                assert os.environ.get("ODOO_RPC_DB") == "envdb"
                assert os.environ.get("ODOO_RPC_USER") == "envuser"
                assert os.environ.get("INVALID KEY") is None
        finally:
            env_file.unlink(missing_ok=True)

    def test_load_env_missing_explicit_file_fails_closed(self) -> None:
        with pytest.raises(FileNotFoundError, match=r"Explicit \.env file not found"):
            load_env("/nonexistent/file.env")


def _make_clients() -> tuple[OdooRpcClient, OdooRpcClient]:
    """Build read/write clients with explicit RPC authorization and stubbed authentication uid."""
    config = OdooRpcConfig(
        url="https://test.erp.com/jsonrpc",
        database="testdb",
        user="testuser",
        token="secret",  # noqa: S106 - test fixture credential
        verify_ssl=True,
    )
    readonly_client = OdooRpcClient(config, allow_rpc=True, allow_write=False)
    write_client = OdooRpcClient(config, allow_rpc=True, allow_write=True)
    with patch("odoo_rpc.json_rpc", return_value=1):
        _ = readonly_client.uid
        _ = write_client.uid
    return readonly_client, write_client


class TestOdooAllowlistsAndGuards(unittest.TestCase):
    def test_client_blocked_without_allow_rpc(self) -> None:
        config = OdooRpcConfig(
            url="https://test.erp.com/jsonrpc",
            database="testdb",
            user="testuser",
            token="secret",  # noqa: S106 - test fixture credential
            verify_ssl=True,
        )
        with pytest.raises(PermissionError, match="RPC BLOCKED"):
            _ = OdooRpcClient(config, allow_rpc=False)

    def test_json_rpc_blocked_without_allow_rpc(self) -> None:
        with pytest.raises(PermissionError, match="RPC BLOCKED"):
            _ = json_rpc(
                "https://test.erp.com/jsonrpc",
                "common",
                "authenticate",
                "testdb",
                "user",
                "token",  # noqa: S106 - test fixture credential
                {},
                allow_rpc=False,
            )

    def test_mutations_blocked_without_write(self) -> None:
        readonly_client, _ = _make_clients()
        for method in ("create", "write", "unlink", "copy", "action_archive"):
            with (
                self.subTest(method=method),
                pytest.raises(PermissionError, match="MUTATION BLOCKED"),
            ):
                _ = readonly_client.execute("crm.lead", method, [])

    def test_side_effectful_introspection_is_forbidden(self) -> None:
        _, write_client = _make_clients()
        for method in ("onchange", "export_data"):
            with pytest.raises(PermissionError, match="METHOD FORBIDDEN"):
                _ = write_client.execute("crm.lead", method, [])

    def test_unknown_arbitrary_method_forbidden_even_with_write(self) -> None:
        _, write_client = _make_clients()
        arbitrary_methods = ["_auto_init", "drop_table", "raw_sql", "arbitrary_custom"]
        for method in arbitrary_methods:
            with (
                self.subTest(method=method),
                pytest.raises(PermissionError, match="METHOD FORBIDDEN"),
            ):
                _ = write_client.execute("crm.lead", method, [])

    def test_invalid_model_names_rejected(self) -> None:
        _, write_client = _make_clients()
        for invalid_model in ("", "   ", "model with spaces", "model;injection"):
            with (
                self.subTest(model=invalid_model),
                pytest.raises(
                    ValueError,
                    match=r"(Model name must be a non-empty string|Invalid model name)",
                ),
            ):
                _ = write_client.execute(invalid_model, "search", [])

    def test_strict_positive_ids_enforced(self) -> None:
        readonly_client, write_client = _make_clients()
        for invalid_id in (0, -1, True, False, "1"):
            with (
                self.subTest(invalid_id=invalid_id),
                pytest.raises(
                    ValueError, match="ID must be a positive non-boolean integer"
                ),
            ):
                _ = readonly_client.read("res.partner", cast("list[int]", [invalid_id]))
            with (
                self.subTest(invalid_id=invalid_id),
                pytest.raises(
                    ValueError, match="ID must be a positive non-boolean integer"
                ),
            ):
                _ = write_client.unlink("res.partner", cast("list[int]", [invalid_id]))


class TestOdooJsonRpc(unittest.TestCase):
    def test_json_rpc_service_gate_denies_unauthorized_service(self) -> None:
        with pytest.raises(PermissionError, match="SERVICE FORBIDDEN"):
            _ = json_rpc(
                "http://127.0.0.1:8069/jsonrpc",
                "db",
                "drop",
                "testdb",
                allow_rpc=True,
            )

    def test_json_rpc_common_service_denies_non_authenticate(self) -> None:
        with pytest.raises(PermissionError, match="METHOD FORBIDDEN"):
            _ = json_rpc(
                "http://127.0.0.1:8069/jsonrpc",
                "common",
                "version",
                allow_rpc=True,
            )

    def test_json_rpc_object_service_denies_non_execute_kw(self) -> None:
        with pytest.raises(PermissionError, match="METHOD FORBIDDEN"):
            _ = json_rpc(
                "http://127.0.0.1:8069/jsonrpc",
                "object",
                "execute",
                "testdb",
                1,
                "token",  # noqa: S106 - test fixture credential
                "res.partner",
                "read",
                [],
                allow_rpc=True,
            )

    def test_json_rpc_transport_gate_blocks_mutation_without_allow_write(self) -> None:
        with pytest.raises(PermissionError, match="MUTATION BLOCKED"):
            _ = json_rpc(
                "http://127.0.0.1:8069/jsonrpc",
                "object",
                "execute_kw",
                "testdb",
                1,
                "token",  # noqa: S106 - test fixture credential
                "res.partner",
                "unlink",
                [[1]],
                {},
                allow_rpc=True,
                allow_write=False,
            )

    @patch("urllib.request.OpenerDirector.open")
    def test_json_rpc_error_sanitization(self, mock_open: MagicMock) -> None:
        payload = json.dumps(
            {
                "error": {
                    "code": 200,
                    "message": "Odoo Server Error",
                    "data": {"secret_stack_trace": "database_password=secret_pw"},
                }
            }
        ).encode("utf-8")
        mock_resp = MagicMock()
        _stub(mock_resp, "read.return_value", payload)
        _stub(mock_open, "return_value.__enter__.return_value", mock_resp)

        with pytest.raises(RuntimeError) as exc_info:
            _ = json_rpc(
                "http://127.0.0.1:8069/jsonrpc",
                "common",
                "authenticate",
                "testdb",
                "user",
                "token",  # noqa: S106 - test fixture credential
                {},
                allow_rpc=True,
            )
        # Verify secret traceback data and sensitive server message are omitted from error string
        assert "secret_stack_trace" not in str(exc_info.value)
        assert "secret_pw" not in str(exc_info.value)
        assert "Odoo RPC server error (code 200)" in str(exc_info.value)


class _MockHttpServer:
    """Ephemeral HTTP test server running on loopback."""

    def __init__(self, handler_cls: type[http.server.BaseHTTPRequestHandler]) -> None:
        self.server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class TestOdooRpcControlledLoopbackHttp(unittest.TestCase):
    def test_redirect_rejected_without_following(self) -> None:
        request_count = {"redirect_hit": 0, "target_hit": 0}

        class RedirectHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path == "/jsonrpc":
                    request_count["redirect_hit"] += 1
                    self.send_response(302)
                    self.send_header(
                        "Location",
                        f"http://127.0.0.1:{server.port}/target_endpoint",
                    )
                    self.end_headers()
                else:
                    request_count["target_hit"] += 1
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"result": "leaked"}')

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass

        server = _MockHttpServer(RedirectHandler)
        server.start()
        try:
            with pytest.raises(RuntimeError, match="HTTP 302"):
                _ = json_rpc(
                    f"http://127.0.0.1:{server.port}/jsonrpc",
                    "common",
                    "authenticate",
                    "testdb",
                    "user",
                    "secret_token",  # noqa: S106 - test fixture credential
                    {},
                    allow_rpc=True,
                )
            assert request_count["redirect_hit"] == 1
            assert request_count["target_hit"] == 0
        finally:
            server.stop()

    def test_zero_network_requests_when_rpc_or_write_denied(self) -> None:
        request_count = {"count": 0}

        class CountingHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                request_count["count"] += 1
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"result": 1}')

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass

        server = _MockHttpServer(CountingHandler)
        server.start()
        try:
            # 1. Denied without --allow-rpc
            argv_no_rpc = [
                "--url",
                f"http://127.0.0.1:{server.port}/jsonrpc",
                "--db",
                "testdb",
                "--user",
                "user@test.com",
                "--token",
                "secret",  # noqa: S106 - test fixture credential
                "search_read",
                "crm.lead",
            ]
            exit_code = main(argv_no_rpc)
            assert exit_code == 1
            assert request_count["count"] == 0

            # 2. Denied mutation without --write
            argv_no_write = [
                "--allow-rpc",
                "--url",
                f"http://127.0.0.1:{server.port}/jsonrpc",
                "--db",
                "testdb",
                "--user",
                "user@test.com",
                "--token",
                "secret",  # noqa: S106 - test fixture credential
                "unlink",
                "crm.lead",
                "[1]",
            ]
            exit_code = main(argv_no_write)
            assert exit_code == 1
            assert request_count["count"] == 0
        finally:
            server.stop()

    def test_e2e_client_read_and_write_on_loopback(self) -> None:
        received_calls: list[dict[str, object]] = []

        class E2eOdooHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                body = cast(
                    "dict[str, object]",
                    json.loads(self.rfile.read(length).decode("utf-8")),
                )
                params = cast("dict[str, object]", body.get("params", {}))
                service = params.get("service")
                method = params.get("method")
                args = cast("list[object]", params.get("args", []))

                received_calls.append(
                    {"service": service, "method": method, "args": args}
                )

                if service == "common" and method == "authenticate":
                    resp = {"jsonrpc": "2.0", "id": 1, "result": 2}
                elif service == "object" and method == "execute_kw":
                    inner_method = args[4]
                    if inner_method == "search_read":
                        resp = {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "result": [{"id": 1, "name": "Partner A"}],
                        }
                    elif inner_method == "create":
                        resp = {"jsonrpc": "2.0", "id": 1, "result": 42}
                    else:
                        resp = {"jsonrpc": "2.0", "id": 1, "result": True}
                else:
                    resp = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "error": {"code": 400, "message": "Bad request"},
                    }

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(resp).encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass

        server = _MockHttpServer(E2eOdooHandler)
        server.start()
        try:
            config = OdooRpcConfig.from_env(
                url=f"http://127.0.0.1:{server.port}/jsonrpc",
                database="testdb",
                user="user@test.com",
                token="secret_token",  # noqa: S106 - test fixture credential
            )

            # 1. Read client can authenticate and read
            read_client = OdooRpcClient(config, allow_rpc=True, allow_write=False)
            records = read_client.search_read("res.partner", domain=[])
            assert records == [{"id": 1, "name": "Partner A"}]

            # 2. Write client can create records
            write_client = OdooRpcClient(config, allow_rpc=True, allow_write=True)
            created_id = write_client.create("res.partner", {"name": "Partner B"})
            assert created_id == 42

            # 3. CLI dispatch end-to-end
            argv_cli = [
                "--allow-rpc",
                "--url",
                f"http://127.0.0.1:{server.port}/jsonrpc",
                "--db",
                "testdb",
                "--user",
                "user@test.com",
                "--token",
                "secret_token",  # noqa: S106 - test fixture credential
                "search_read",
                "res.partner",
            ]
            with patch("sys.stdout", new=io.StringIO()) as fake_stdout:
                exit_code = main(argv_cli)
                assert exit_code == 0
                parsed_out = json.loads(fake_stdout.getvalue())
                assert parsed_out == [{"id": 1, "name": "Partner A"}]
        finally:
            server.stop()


class TestOdooRpcCli(unittest.TestCase):
    def test_cli_blocked_without_allow_rpc(self) -> None:
        argv = [
            "--url",
            "http://127.0.0.1:8069/jsonrpc",
            "--db",
            "testdb",
            "--user",
            "user@test.com",
            "--token",
            "secret",  # noqa: S106 - test fixture credential
            "search_read",
            "crm.lead",
            '[["active", "=", true]]',
        ]
        with patch("sys.stderr", new=io.StringIO()) as fake_stderr:
            exit_code = main(argv)
            assert exit_code == 1
            assert "RPC BLOCKED" in fake_stderr.getvalue()

    def test_cli_mutation_blocked_before_config_without_write(self) -> None:
        argv = [
            "--allow-rpc",
            "--url",
            "http://127.0.0.1:8069/jsonrpc",
            "--db",
            "testdb",
            "--user",
            "user@test.com",
            "--token",
            "secret",  # noqa: S106 - test fixture credential
            "create",
            "crm.lead",
            '{"name": "Lead"}',
        ]
        with patch("sys.stderr", new=io.StringIO()) as fake_stderr:
            exit_code = main(argv)
            assert exit_code == 1
            assert "MUTATION BLOCKED" in fake_stderr.getvalue()


if __name__ == "__main__":
    _ = unittest.main()
