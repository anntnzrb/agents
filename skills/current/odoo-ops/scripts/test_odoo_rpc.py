from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestOdooRpcConfig(unittest.TestCase):
    def test_missing_required_fields_raise_value_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as ctx:
                OdooRpcConfig.from_env()
            self.assertIn("Missing Odoo RPC URL", str(ctx.exception))

    def test_valid_config_from_explicit_args(self) -> None:
        cfg = OdooRpcConfig.from_env(
            url="https://test.erp.com/jsonrpc",
            database="testdb",
            user="testuser",
            token="secret123",
            verify_ssl=True,
        )
        self.assertEqual(cfg.url, "https://test.erp.com/jsonrpc")
        self.assertEqual(cfg.database, "testdb")
        self.assertEqual(cfg.user, "testuser")
        self.assertEqual(cfg.token, "secret123")
        self.assertTrue(cfg.verify_ssl)
    def test_url_auto_normalizes_to_jsonrpc(self) -> None:
        cfg = OdooRpcConfig.from_env(
            url="https://erptech.espol.edu.ec/",
            database="espoltecherp",
            user="erpespoltech@espol.edu.ec",
            token="secret",
        )
        self.assertEqual(cfg.url, "https://erptech.espol.edu.ec/jsonrpc")


    def test_token_loaded_from_token_path(self) -> None:
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("token_from_file\n")
            token_file = Path(f.name)

        try:
            cfg = OdooRpcConfig.from_env(
                url="https://test.erp.com/jsonrpc",
                database="testdb",
                user="testuser",
                token_path=token_file,
            )
            self.assertEqual(cfg.token, "token_from_file")
        finally:
            token_file.unlink(missing_ok=True)

    def test_ssl_verification_flags(self) -> None:
        with patch.dict(os.environ, {"ODOO_RPC_VERIFY_SSL": "false"}):
            cfg = OdooRpcConfig.from_env(
                url="https://test.erp.com/jsonrpc",
                database="testdb",
                user="testuser",
                token="tok",
            )
            self.assertFalse(cfg.verify_ssl)

    def test_parse_env_file(self) -> None:
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("# Sample env\n")
            f.write('export ODOO_RPC_URL="https://env.erp.com/jsonrpc"\n')
            f.write("ODOO_RPC_DB=envdb\n")
            f.write("ODOO_RPC_USER='envuser'\n")
            env_file = Path(f.name)

        try:
            with patch.dict(os.environ, {}, clear=True):
                self.assertTrue(parse_env_file(env_file))
                self.assertEqual(
                    os.environ.get("ODOO_RPC_URL"), "https://env.erp.com/jsonrpc"
                )
                self.assertEqual(os.environ.get("ODOO_RPC_DB"), "envdb")
                self.assertEqual(os.environ.get("ODOO_RPC_USER"), "envuser")
        finally:
            env_file.unlink(missing_ok=True)


class TestOdooAllowlistsAndGuards(unittest.TestCase):
    def setUp(self) -> None:
        self.config = OdooRpcConfig(
            url="https://test.erp.com/jsonrpc",
            database="testdb",
            user="testuser",
            token="secret",
            verify_ssl=True,
        )
        self.readonly_client = OdooRpcClient(self.config, allow_write=False)
        self.readonly_client._uid = 1

        self.write_client = OdooRpcClient(self.config, allow_write=True)
        self.write_client._uid = 1

    def test_safe_introspections_pass_without_write(self) -> None:
        with patch("odoo_rpc.json_rpc", return_value={"status": "ok"}) as mock_rpc:
            for method in sorted(READONLY_ALLOWLIST):
                with self.subTest(method=method):
                    res = self.readonly_client.execute("crm.lead", method, [])
                    self.assertEqual(res, {"status": "ok"})
                    mock_rpc.assert_called()

    def test_mutations_blocked_without_write(self) -> None:
        for method in sorted(MUTATION_ALLOWLIST):
            with self.subTest(method=method):
                with self.assertRaises(PermissionError) as ctx:
                    self.readonly_client.execute("crm.lead", method, [])
                self.assertIn("MUTATION BLOCKED", str(ctx.exception))
                self.assertIn("--write was not specified", str(ctx.exception))

    def test_mutations_allowed_with_write_flag(self) -> None:
        with patch("odoo_rpc.json_rpc", return_value={"result": "mutated"}) as mock_rpc:
            for method in sorted(MUTATION_ALLOWLIST):
                with self.subTest(method=method):
                    res = self.write_client.execute("crm.lead", method, [])
                    self.assertEqual(res, {"result": "mutated"})
                    mock_rpc.assert_called()

    def test_unknown_arbitrary_method_forbidden_even_with_write(self) -> None:
        arbitrary_methods = ["_auto_init", "drop_table", "raw_sql", "arbitrary_custom"]
        for method in arbitrary_methods:
            with self.subTest(method=method):
                with self.assertRaises(PermissionError) as ctx:
                    self.write_client.execute("crm.lead", method, [])
                self.assertIn("METHOD FORBIDDEN", str(ctx.exception))


class TestOdooJsonRpc(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_json_rpc_success(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"result": 42}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        res = json_rpc("https://test.erp.com/jsonrpc", "common", "version")
        self.assertEqual(res, 42)

    @patch("urllib.request.urlopen")
    def test_json_rpc_error_raises_runtime_error(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"error": {"code": 200, "message": "Odoo Server Error"}}
        ).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        with self.assertRaises(RuntimeError) as ctx:
            json_rpc("https://test.erp.com/jsonrpc", "common", "version")
        self.assertIn("Odoo Server Error", str(ctx.exception))


class TestOdooRpcCli(unittest.TestCase):
    @patch("odoo_rpc.OdooRpcClient")
    def test_cli_search_read(self, mock_client_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_instance.search_read.return_value = [{"id": 1, "name": "Lead A"}]
        mock_client_cls.return_value = mock_instance

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
            self.assertEqual(exit_code, 0)
            output = json.loads(fake_stdout.getvalue())
            self.assertEqual(output, [{"id": 1, "name": "Lead A"}])

    @patch("odoo_rpc.OdooRpcClient")
    def test_cli_metadata(self, mock_client_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_instance.get_metadata.return_value = [
            {"id": 1, "xmlid": "base.main_partner"}
        ]
        mock_client_cls.return_value = mock_instance

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
            self.assertEqual(exit_code, 0)
            output = json.loads(fake_stdout.getvalue())
            self.assertEqual(output, [{"id": 1, "xmlid": "base.main_partner"}])

    @patch("odoo_rpc.OdooRpcClient")
    def test_cli_mutation_without_write_fails(self, mock_client_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_instance.create.side_effect = PermissionError(
            "MUTATION BLOCKED: --write was not specified"
        )
        mock_client_cls.return_value = mock_instance

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
            self.assertEqual(exit_code, 1)
            self.assertIn("MUTATION BLOCKED", fake_stderr.getvalue())

    @patch("odoo_rpc.OdooRpcClient")
    def test_cli_mutation_with_write_succeeds(self, mock_client_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_instance.create.return_value = 101
        mock_client_cls.return_value = mock_instance

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
            self.assertEqual(exit_code, 0)
            output = json.loads(fake_stdout.getvalue())
            self.assertEqual(output, {"created_id": 101})


if __name__ == "__main__":
    unittest.main()
