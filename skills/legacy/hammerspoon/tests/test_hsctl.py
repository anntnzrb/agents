"""Tests for hsctl.py — Hammerspoon skill CLI engine."""

import argparse
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Add skill scripts to path
_skill_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_skill_dir / "scripts"))

import hsctl

TEMP_DIR = tempfile.gettempdir()
TEMP_HS_DIR = str(Path(TEMP_DIR) / "hs")


class TestArgParsing(unittest.TestCase):
    def test_help_flag_on_parser(self) -> None:
        parser = hsctl.build_parser()
        with mock.patch.object(sys, "argv", ["hsctl", "--help"]):
            with self.assertRaises(SystemExit) as cm:
                parser.parse_args(["--help"])
            self.assertEqual(cm.exception.code, 0)


class TestStatus(unittest.TestCase):
    def test_status_missing_hs_binary_json(self) -> None:
        ns = argparse.Namespace(json=True)
        with mock.patch.object(hsctl, "_hs_binary", return_value=None):
            rc = hsctl.cmd_status(ns)
            self.assertNotEqual(rc, 0)

    def test_status_missing_hs_binary_text(self) -> None:
        ns = argparse.Namespace(json=False)
        with mock.patch.object(hsctl, "_hs_binary", return_value=None):
            rc = hsctl.cmd_status(ns)
            self.assertNotEqual(rc, 0)

    def test_status_hs_works_json(self) -> None:
        ns = argparse.Namespace(json=True)
        with (
            mock.patch.object(hsctl, "_hs_binary", return_value="/usr/local/bin/hs"),
            mock.patch.object(
                hsctl,
                "_run_hs_json",
                return_value=(True, {"version": "1.1.1", "configDir": TEMP_HS_DIR}, ""),
            ),
        ):
            rc = hsctl.cmd_status(ns)
            self.assertEqual(rc, 0)

    def test_status_hs_works_text(self) -> None:
        ns = argparse.Namespace(json=False)
        with (
            mock.patch.object(hsctl, "_hs_binary", return_value="/usr/local/bin/hs"),
            mock.patch.object(
                hsctl,
                "_run_hs_json",
                return_value=(True, {"version": "1.1.0", "configDir": TEMP_HS_DIR}, ""),
            ),
        ):
            rc = hsctl.cmd_status(ns)
            self.assertEqual(rc, 0)

    def test_status_hs_fails_json(self) -> None:
        ns = argparse.Namespace(json=True)
        with (
            mock.patch.object(hsctl, "_hs_binary", return_value="/usr/local/bin/hs"),
            mock.patch.object(
                hsctl,
                "_run_hs_json",
                return_value=(False, None, "connection refused"),
            ),
        ):
            rc = hsctl.cmd_status(ns)
            self.assertNotEqual(rc, 0)


class TestDoctor(unittest.TestCase):
    def test_doctor_json(self) -> None:
        ns = argparse.Namespace(json=True)
        with (
            mock.patch.object(hsctl, "_hs_binary", return_value="/usr/local/bin/hs"),
            mock.patch.object(
                hsctl,
                "_run_hs_json",
                return_value=(True, {"version": "1.1.1", "configDir": TEMP_DIR}, ""),
            ),
        ):
            rc = hsctl.cmd_doctor(ns)
            self.assertEqual(rc, 0)

    def test_doctor_missing_hs(self) -> None:
        ns = argparse.Namespace(json=False)
        with mock.patch.object(hsctl, "_hs_binary", return_value=None):
            rc = hsctl.cmd_doctor(ns)
            self.assertNotEqual(rc, 0)


class TestEval(unittest.TestCase):
    def test_eval_text(self) -> None:
        ns = argparse.Namespace(lua="return 42", json=False)
        with mock.patch.object(
            hsctl,
            "_run_hs",
            return_value=(0, "42\n", ""),
        ):
            rc = hsctl.cmd_eval(ns)
            self.assertEqual(rc, 0)

    def test_eval_json(self) -> None:
        ns = argparse.Namespace(lua="return 42", json=True)
        with mock.patch.object(
            hsctl,
            "_run_hs_json",
            return_value=(True, 42, ""),
        ):
            rc = hsctl.cmd_eval(ns)
            self.assertEqual(rc, 0)

    def test_eval_fail(self) -> None:
        ns = argparse.Namespace(lua="bad code", json=False)
        with mock.patch.object(
            hsctl,
            "_run_hs",
            return_value=(1, "", "syntax error"),
        ):
            rc = hsctl.cmd_eval(ns)
            self.assertNotEqual(rc, 0)

    def test_eval_stdin(self) -> None:
        ns = argparse.Namespace(lua="-", json=False)
        with (
            mock.patch.object(sys, "stdin", data="return 1 + 1"),  # type: ignore[attr-defined]
            mock.patch.object(
                hsctl,
                "_run_hs",
                return_value=(0, "2\n", ""),
            ),
        ):
            rc = hsctl.cmd_eval(ns)
            self.assertEqual(rc, 0)


class TestEvalFile(unittest.TestCase):
    def test_eval_file_json(self) -> None:
        ns = argparse.Namespace(json=True)
        with (
            tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as f,
        ):
            f.write("return 42\n")
            f.flush()
            ns.path = f.name  # type: ignore[attr-defined]
        try:
            with mock.patch.object(
                hsctl,
                "_run_hs_json",
                return_value=(True, 42, ""),
            ):
                rc = hsctl.cmd_eval_file(ns)
                self.assertEqual(rc, 0)
        finally:
            Path(f.name).unlink(missing_ok=True)


class TestInspectCommands(unittest.TestCase):
    def _mock_hs_json(self, data):
        return mock.patch.object(hsctl, "_run_hs_json", return_value=(True, data, ""))

    def test_windows_json(self) -> None:
        ns = argparse.Namespace(json=True)
        with self._mock_hs_json([{"id": 1, "title": "w1", "app": "App"}]):
            rc = hsctl.cmd_windows(ns)
            self.assertEqual(rc, 0)

    def test_apps_json(self) -> None:
        ns = argparse.Namespace(json=True)
        with self._mock_hs_json([{"name": "Finder", "pid": 100}]):
            rc = hsctl.cmd_apps(ns)
            self.assertEqual(rc, 0)

    def test_screens_json(self) -> None:
        ns = argparse.Namespace(json=True)
        with self._mock_hs_json([{"name": "Color LCD", "id": 1}]):
            rc = hsctl.cmd_screens(ns)
            self.assertEqual(rc, 0)

    def test_hotkeys_json(self) -> None:
        ns = argparse.Namespace(json=True)
        with self._mock_hs_json([{"mods": ["cmd", "alt"], "key": "h"}]):
            rc = hsctl.cmd_hotkeys(ns)
            self.assertEqual(rc, 0)

    def test_spoons_json(self) -> None:
        ns = argparse.Namespace(json=True)
        with self._mock_hs_json(["AClock", "ClipboardTool"]):
            rc = hsctl.cmd_spoons_loaded(ns)
            self.assertEqual(rc, 0)

    def test_config_json(self) -> None:
        ns = argparse.Namespace(json=True)
        with self._mock_hs_json("/Users/test/.hammerspoon"):
            rc = hsctl.cmd_config(ns)
            self.assertEqual(rc, 0)

    def test_config_fail(self) -> None:
        ns = argparse.Namespace(json=False)
        with mock.patch.object(
            hsctl,
            "_run_hs_json",
            return_value=(False, None, "error"),
        ):
            rc = hsctl.cmd_config(ns)
            self.assertNotEqual(rc, 0)


class TestDocsCommands(unittest.TestCase):
    _sample_index = "<html><body><a href='hs.window.html'>hs.window</a><a href='hs.ipc.html'>hs.ipc</a></body></html>"

    def test_fetch_docs_index(self) -> None:
        with mock.patch.object(
            hsctl,
            "fetch_url",
            return_value=(self._sample_index, False),
        ):
            html = hsctl._fetch_docs_index()
            self.assertIn("hs.window", html)

    def test_parse_docs_index(self) -> None:
        modules = hsctl._parse_docs_index(self._sample_index)
        names = [m["name"] for m in modules]
        self.assertIn("hs.window", names)
        self.assertIn("hs.ipc", names)

    def test_docs_search_module_match_json(self) -> None:
        ns = argparse.Namespace(query="hs.window", json=True)
        with (
            mock.patch.object(
                hsctl,
                "_fetch_docs_index",
                return_value=self._sample_index,
            ),
            mock.patch.object(
                hsctl,
                "_fetch_module_doc",
                return_value="",
            ),
        ):
            rc = hsctl.cmd_docs_search(ns)
            self.assertEqual(rc, 0)

    def test_docs_module_json(self) -> None:
        ns = argparse.Namespace(module="hs.window", json=True)
        with mock.patch.object(
            hsctl,
            "_fetch_module_doc",
            return_value='<h4>hs.window.moveToUnit</h4><div class="signature"><code>hs.window:moveToUnit(unit)</code></div>',
        ):
            rc = hsctl.cmd_docs_module(ns)
            self.assertEqual(rc, 0)

    def test_docs_refresh_json(self) -> None:
        ns = argparse.Namespace(if_needed=False, json=True)
        with mock.patch.object(
            hsctl,
            "fetch_url",
            return_value=("ok", False),
        ):
            rc = hsctl.cmd_docs_refresh(ns)
            self.assertEqual(rc, 0)


class TestSourceCommands(unittest.TestCase):
    def test_source_search_json(self) -> None:
        ns = argparse.Namespace(pattern="cliInstall", json=True)
        with mock.patch.object(
            hsctl,
            "_fetch_github_raw",
            return_value="function cliInstall(p, s)\n  local path = p or '/usr/local'\nend\n",
        ):
            rc = hsctl.cmd_source_search(ns)
            self.assertEqual(rc, 0)

    def test_source_search_no_match(self) -> None:
        ns = argparse.Namespace(pattern="nonexistent_xyz", json=True)
        with mock.patch.object(
            hsctl,
            "_fetch_github_raw",
            return_value="-- empty\n",
        ):
            rc = hsctl.cmd_source_search(ns)
            self.assertEqual(rc, 0)

    def test_source_fetch_json(self) -> None:
        ns = argparse.Namespace(if_needed=False, json=True)
        with mock.patch.object(
            hsctl,
            "_gh_ls_remote_sha",
            return_value="abc123def456",
        ):
            rc = hsctl.cmd_source_fetch(ns)
            self.assertEqual(rc, 0)


class TestSpoonsCommands(unittest.TestCase):
    def test_spoons_search_json(self) -> None:
        ns = argparse.Namespace(query="Clip", json=True)
        listing = json.dumps(
            [
                {
                    "name": "ClipboardTool.spoon",
                    "path": "Source/ClipboardTool.spoon",
                    "html_url": "https://github.com/Hammerspoon/Spoons/tree/master/Source/ClipboardTool.spoon",
                },
            ],
        )
        with mock.patch.object(hsctl, "_fetch_github_raw", return_value=listing):
            rc = hsctl.cmd_spoons_search(ns)
            self.assertEqual(rc, 0)

    def test_spoons_source_json(self) -> None:
        ns = argparse.Namespace(name="AClock", json=True)
        with mock.patch.object(
            hsctl,
            "_fetch_github_raw",
            return_value="-- AClock.lua\nlocal obj = {}\nreturn obj\n",
        ):
            rc = hsctl.cmd_spoons_source(ns)
            self.assertEqual(rc, 0)

    def test_spoons_source_error(self) -> None:
        ns = argparse.Namespace(name="NoSpoon", json=False)
        with mock.patch.object(
            hsctl,
            "_fetch_github_raw",
            side_effect=RuntimeError("404"),
        ):
            rc = hsctl.cmd_spoons_source(ns)
            self.assertNotEqual(rc, 0)


class TestLintFmt(unittest.TestCase):
    def test_lint_missing_tool(self) -> None:
        ns = argparse.Namespace(path=TEMP_DIR, json=False)
        with mock.patch.object(hsctl, "_discover_tool", return_value=None):
            rc = hsctl.cmd_lint(ns)
            self.assertNotEqual(rc, 0)

    def test_lint_json(self) -> None:
        ns = argparse.Namespace(path=TEMP_DIR, json=True)
        with (
            mock.patch.object(
                hsctl,
                "_discover_tool",
                return_value="/usr/local/bin/luacheck",
            ),
            mock.patch.object(
                subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout="",
                    stderr="",
                ),
            ),
        ):
            rc = hsctl.cmd_lint(ns)
            self.assertEqual(rc, 0)

    def test_lint_failure_json_sets_ok_false_and_returns_nonzero(self) -> None:
        ns = argparse.Namespace(path=TEMP_DIR, json=True)
        with (
            mock.patch.object(
                hsctl,
                "_discover_tool",
                return_value="/usr/local/bin/luacheck",
            ),
            mock.patch.object(
                subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    args=[],
                    returncode=1,
                    stdout="file.lua:1:1: warning",
                    stderr="",
                ),
            ),
            mock.patch.object(sys, "stdout", new_callable=io.StringIO) as stdout,
        ):
            rc = hsctl.cmd_lint(ns)

        self.assertNotEqual(rc, 0)
        self.assertFalse(json.loads(stdout.getvalue())["ok"])

    def test_fmt_missing_tool(self) -> None:
        ns = argparse.Namespace(path=TEMP_DIR, check=True, write=False, json=False)
        with mock.patch.object(hsctl, "_discover_tool", return_value=None):
            rc = hsctl.cmd_fmt(ns)
            self.assertNotEqual(rc, 0)

    def test_fmt_check_json(self) -> None:
        ns = argparse.Namespace(path=TEMP_DIR, check=True, write=False, json=True)
        with (
            mock.patch.object(
                hsctl,
                "_discover_tool",
                return_value="/usr/local/bin/stylua",
            ),
            mock.patch.object(
                subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout="",
                    stderr="",
                ),
            ),
        ):
            rc = hsctl.cmd_fmt(ns)
            self.assertEqual(rc, 0)

    def test_fmt_check_failure_json_sets_ok_false_and_returns_nonzero(self) -> None:
        ns = argparse.Namespace(path=TEMP_DIR, check=True, write=False, json=True)
        with (
            mock.patch.object(
                hsctl,
                "_discover_tool",
                return_value="/usr/local/bin/stylua",
            ),
            mock.patch.object(
                subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    args=[],
                    returncode=1,
                    stdout="formatting differs",
                    stderr="",
                ),
            ),
            mock.patch.object(sys, "stdout", new_callable=io.StringIO) as stdout,
        ):
            rc = hsctl.cmd_fmt(ns)

        self.assertNotEqual(rc, 0)
        self.assertFalse(json.loads(stdout.getvalue())["ok"])

    def test_fmt_write_failure_json_sets_ok_false_and_returns_nonzero(self) -> None:
        ns = argparse.Namespace(path=TEMP_DIR, check=False, write=True, json=True)
        with (
            mock.patch.object(
                hsctl,
                "_discover_tool",
                return_value="/usr/local/bin/stylua",
            ),
            mock.patch.object(
                subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    args=[],
                    returncode=2,
                    stdout="",
                    stderr="formatter failed",
                ),
            ),
            mock.patch.object(sys, "stdout", new_callable=io.StringIO) as stdout,
        ):
            rc = hsctl.cmd_fmt(ns)

        self.assertNotEqual(rc, 0)
        self.assertFalse(json.loads(stdout.getvalue())["ok"])


class TestTestAnnotations(unittest.TestCase):
    def test_test_missing_tool(self) -> None:
        ns = argparse.Namespace(path=TEMP_DIR, json=False)
        with mock.patch.object(hsctl, "_discover_tool", return_value=None):
            rc = hsctl.cmd_test(ns)
            self.assertNotEqual(rc, 0)

    def test_test_failure_json_sets_ok_false_and_returns_nonzero(self) -> None:
        ns = argparse.Namespace(path=TEMP_DIR, json=True)
        with (
            mock.patch.object(
                hsctl,
                "_discover_tool",
                return_value="/usr/local/bin/busted",
            ),
            mock.patch.object(
                subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    args=[],
                    returncode=1,
                    stdout="1 failure",
                    stderr="",
                ),
            ),
            mock.patch.object(sys, "stdout", new_callable=io.StringIO) as stdout,
        ):
            rc = hsctl.cmd_test(ns)

        self.assertNotEqual(rc, 0)
        self.assertFalse(json.loads(stdout.getvalue())["ok"])

    def test_annotations_status_json(self) -> None:
        ns = argparse.Namespace(json=True)
        with mock.patch.object(
            hsctl,
            "_run_hs_json",
            return_value=(True, "/Users/test/.hammerspoon", ""),
        ):
            rc = hsctl.cmd_annotations_status(ns)
            self.assertEqual(rc, 0)

    def test_lsp_config_print_json(self) -> None:
        ns = argparse.Namespace(json=True)
        with mock.patch.object(
            hsctl,
            "_run_hs_json",
            return_value=(True, "/Users/test/.hammerspoon", ""),
        ):
            rc = hsctl.cmd_lsp_config(ns)
            self.assertEqual(rc, 0)


class TestCache(unittest.TestCase):
    def test_cache_root(self) -> None:
        root = hsctl._cache_root()
        self.assertIn("hammerspoon", str(root))

    def test_cache_path_for_url(self) -> None:
        p = hsctl._cache_path_for_url("https://example.com/doc")
        self.assertTrue(str(p).endswith(".html"))

    def test_cache_write_read_meta(self) -> None:
        url = "https://example.com/test_meta"
        hsctl._write_cache_meta(url, "etag123", "Mon, 01 Jan 2024 00:00:00 GMT")
        meta = hsctl._read_cache_meta(url)
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta["etag"], "etag123")

    def test_is_stale_fresh(self) -> None:
        url = "https://example.com/fresh"
        hsctl._write_cache_meta(url, None, None)
        stale = hsctl._is_cache_stale(url)
        self.assertFalse(stale)

    def test_is_stale_missing(self) -> None:
        url = "https://example.com/nonexistent_meta_42"
        stale = hsctl._is_cache_stale(url)
        self.assertTrue(stale)

    def test_cache_miss_returns_empty_meta(self) -> None:
        meta = hsctl._read_cache_meta("https://example.com/no_such_meta")
        self.assertIsNone(meta)


class TestDiscover(unittest.TestCase):
    def test_discover_tool_found(self) -> None:
        with mock.patch.object(hsctl, "shutil", create=True) as sh:
            sh.which.return_value = "/usr/local/bin/stylua"
            path = hsctl._discover_tool("stylua")
            self.assertEqual(path, "/usr/local/bin/stylua")

    def test_discover_tool_missing(self) -> None:
        with mock.patch.object(hsctl, "shutil", create=True) as sh:
            sh.which.return_value = None
            path = hsctl._discover_tool("nonexistent_tool")
            self.assertIsNone(path)


if __name__ == "__main__":
    unittest.main()
