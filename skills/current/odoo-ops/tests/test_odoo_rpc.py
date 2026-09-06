from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from odoo_rpc import (
    MUTATION_ALLOWLIST,
    READONLY_ALLOWLIST,
    OdooRpcClient,
    OdooRpcConfig,
    json_rpc,
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

    def test_valid_config_from_explicit_args(self) -> None:
        cfg = OdooRpcConfig.from_env(
            url="https://test.erp.com/jsonrpc",
            database="testdb",
            user="testuser",
            token="secret123",  # noqa: S106 - test fixture credential
            verify_ssl=True,
        )
        assert cfg.url == "https://test.erp.com/jsonrpc"
        assert cfg.database == "testdb"
        assert cfg.user == "testuser"
        assert cfg.token == "secret123"  # noqa: S105 - test fixture credential comparison
        assert cfg.verify_ssl

    def test_url_auto_normalizes_to_jsonrpc(self) -> None:
        cfg = OdooRpcConfig.from_env(
            url="https://erptech.espol.edu.ec/",
            database="espoltecherp",
            user="erpespoltech@espol.edu.ec",
            token="secret",  # noqa: S106 - test fixture credential
        )
        assert cfg.url == "https://erptech.espol.edu.ec/jsonrpc"

    def test_token_loaded_from_token_path(self) -> None:
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            _ = f.write("token_from_file\n")
            token_file = Path(f.name)

        try:
            cfg = OdooRpcConfig.from_env(
                url="https://test.erp.com/jsonrpc",
                database="testdb",
                user="testuser",
                token_path=token_file,
            )
            assert cfg.token == "token_from_file"  # noqa: S105 - test fixture credential comparison
        finally:
            token_file.unlink(missing_ok=True)

    def test_ssl_verification_flags(self) -> None:
        with patch.dict(os.environ, {"ODOO_RPC_VERIFY_SSL": "false"}):
            cfg = OdooRpcConfig.from_env(
                url="https://test.erp.com/jsonrpc",
                database="testdb",
                user="testuser",
                token="tok",  # noqa: S106 - test fixture credential
            )
            assert not cfg.verify_ssl

    def test_parse_env_file(self) -> None:
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            _ = f.write("# Sample env\n")
            _ = f.write('export ODOO_RPC_URL="https://env.erp.com/jsonrpc"\n')
            _ = f.write("ODOO_RPC_DB=envdb\n")
            _ = f.write("ODOO_RPC_USER='envuser'\n")
            env_file = Path(f.name)

        try:
            with patch.dict(os.environ, {}, clear=True):
                assert parse_env_file(env_file)
                assert os.environ.get("ODOO_RPC_URL") == "https://env.erp.com/jsonrpc"
                assert os.environ.get("ODOO_RPC_DB") == "envdb"
                assert os.environ.get("ODOO_RPC_USER") == "envuser"
        finally:
            env_file.unlink(missing_ok=True)


def _make_clients() -> tuple[OdooRpcClient, OdooRpcClient]:
    """Build read/write clients with a stubbed authentication uid."""
    config = OdooRpcConfig(
        url="https://test.erp.com/jsonrpc",
        database="testdb",
        user="testuser",
        token="secret",  # noqa: S106 - test fixture credential
        verify_ssl=True,
    )
    readonly_client = OdooRpcClient(config, allow_write=False)
    write_client = OdooRpcClient(config, allow_write=True)
    with patch("odoo_rpc.json_rpc", return_value=1):
        _ = readonly_client.uid
        _ = write_client.uid
    return readonly_client, write_client


class TestOdooAllowlistsAndGuards(unittest.TestCase):
    def test_safe_introspections_pass_without_write(self) -> None:
        readonly_client, _ = _make_clients()
        with patch("odoo_rpc.json_rpc", return_value={"status": "ok"}) as mock_rpc:
            for method in sorted(READONLY_ALLOWLIST):
                with self.subTest(method=method):
                    res = readonly_client.execute("crm.lead", method, [])
                    assert res == {"status": "ok"}
                    mock_rpc.assert_called()

    def test_mutations_blocked_without_write(self) -> None:
        readonly_client, _ = _make_clients()
        for method in sorted(MUTATION_ALLOWLIST):
            with self.subTest(method=method):
                with pytest.raises(PermissionError) as exc_info:
                    _ = readonly_client.execute("crm.lead", method, [])
                assert "MUTATION BLOCKED" in str(exc_info.value)
                assert "--write was not specified" in str(exc_info.value)

    def test_mutations_allowed_with_write_flag(self) -> None:
        _, write_client = _make_clients()
        with patch("odoo_rpc.json_rpc", return_value={"result": "mutated"}) as mock_rpc:
            for method in sorted(MUTATION_ALLOWLIST):
                with self.subTest(method=method):
                    res = write_client.execute("crm.lead", method, [])
                    assert res == {"result": "mutated"}
                    mock_rpc.assert_called()

    def test_unknown_arbitrary_method_forbidden_even_with_write(self) -> None:
        _, write_client = _make_clients()
        arbitrary_methods = ["_auto_init", "drop_table", "raw_sql", "arbitrary_custom"]
        for method in arbitrary_methods:
            with self.subTest(method=method):
                with pytest.raises(PermissionError) as exc_info:
                    _ = write_client.execute("crm.lead", method, [])
                assert "METHOD FORBIDDEN" in str(exc_info.value)


class TestOdooJsonRpc(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_json_rpc_success(self, mock_urlopen: MagicMock) -> None:
        payload = json.dumps({"result": 42}).encode("utf-8")
        mock_resp = MagicMock()
        _stub(mock_resp, "read.return_value", payload)
        _stub(mock_urlopen, "return_value.__enter__.return_value", mock_resp)

        res = json_rpc("https://test.erp.com/jsonrpc", "common", "version")
        assert res == 42

    @patch("urllib.request.urlopen")
    def test_json_rpc_error_raises_runtime_error(self, mock_urlopen: MagicMock) -> None:
        payload = json.dumps(
            {"error": {"code": 200, "message": "Odoo Server Error"}}
        ).encode("utf-8")
        mock_resp = MagicMock()
        _stub(mock_resp, "read.return_value", payload)
        _stub(mock_urlopen, "return_value.__enter__.return_value", mock_resp)
        with pytest.raises(RuntimeError) as exc_info:
            _ = json_rpc("https://test.erp.com/jsonrpc", "common", "version")
        assert "Odoo Server Error" in str(exc_info.value)


class TestOdooRpcCli(unittest.TestCase):
    @patch("odoo_rpc.OdooRpcClient")
    def test_cli_search_read(self, mock_client_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        _stub(mock_instance, "search_read.return_value", [{"id": 1, "name": "Lead A"}])
        _stub(mock_client_cls, "return_value", mock_instance)

        argv = [
            "--url",
            "https://test.erp.com/jsonrpc",
            "--db",
            "testdb",
            "--user",
            "user@test.com",
            "--token",
            "secret",
            "search_read",
            "crm.lead",
            '[["active", "=", true]]',
            "--limit",
            "5",
        ]

        with patch("sys.stdout", new=io.StringIO()) as fake_stdout:
            exit_code = main(argv)
            assert exit_code == 0
            output = cast("object", json.loads(fake_stdout.getvalue()))
            assert output == [{"id": 1, "name": "Lead A"}]

    @patch("odoo_rpc.OdooRpcClient")
    def test_cli_metadata(self, mock_client_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        _stub(
            mock_instance,
            "get_metadata.return_value",
            [{"id": 1, "xmlid": "base.main_partner"}],
        )
        _stub(mock_client_cls, "return_value", mock_instance)

        argv = [
            "--url",
            "https://test.erp.com/jsonrpc",
            "--db",
            "testdb",
            "--user",
            "user@test.com",
            "--token",
            "secret",
            "metadata",
            "res.partner",
            "[1]",
        ]

        with patch("sys.stdout", new=io.StringIO()) as fake_stdout:
            exit_code = main(argv)
            assert exit_code == 0
            output = cast("object", json.loads(fake_stdout.getvalue()))
            assert output == [{"id": 1, "xmlid": "base.main_partner"}]

    @patch("odoo_rpc.OdooRpcClient")
    def test_cli_mutation_without_write_fails(self, mock_client_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        _stub(
            mock_instance,
            "create.side_effect",
            PermissionError("MUTATION BLOCKED: --write was not specified"),
        )
        _stub(mock_client_cls, "return_value", mock_instance)

        argv = [
            "--url",
            "https://test.erp.com/jsonrpc",
            "--db",
            "testdb",
            "--user",
            "user@test.com",
            "--token",
            "secret",
            "create",
            "crm.lead",
            '{"name": "New Lead"}',
        ]

        with patch("sys.stderr", new=io.StringIO()) as fake_stderr:
            exit_code = main(argv)
            assert exit_code == 1
            assert "MUTATION BLOCKED" in fake_stderr.getvalue()

    @patch("odoo_rpc.OdooRpcClient")
    def test_cli_mutation_with_write_succeeds(self, mock_client_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        _stub(mock_instance, "create.return_value", 101)
        _stub(mock_client_cls, "return_value", mock_instance)

        argv = [
            "--url",
            "https://test.erp.com/jsonrpc",
            "--db",
            "testdb",
            "--user",
            "user@test.com",
            "--token",
            "secret",
            "--write",
            "create",
            "crm.lead",
            '{"name": "New Lead"}',
        ]

        with patch("sys.stdout", new=io.StringIO()) as fake_stdout:
            exit_code = main(argv)
            assert exit_code == 0
            output = cast("object", json.loads(fake_stdout.getvalue()))
            assert output == {"created_id": 101}


if __name__ == "__main__":
    _ = unittest.main()
