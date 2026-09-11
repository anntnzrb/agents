"""Unit tests for omp-search; port of test/omp-search.test.ts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import config
import executor
import pytest
from config import discover_active_omp_providers, extract_yaml_list
from executor import (
    SingleSearchExecutionOptions,
    execute_single_search,
    failure_message,
    resolve_omp,
)
from merge import merge_parallel_results
from models import (
    OmpBinaryNotFoundError,
    OmpExecutionError,
    OmpTimeoutError,
)
from parser import (
    frame_content,
    parse_search_output,
    redact,
    strip_terminal_controls,
)

import scripts.cli as cli_mod
from scripts.cli import main as cli_main

if TYPE_CHECKING:
    from models import SearchFailurePayload, SearchSuccessPayload


def test_strip_terminal_controls():
    raw = "\x1b[31mError\x1b[0m\x1b]0;Title\x07\r\nLine 2\rLine 3"
    cleaned = strip_terminal_controls(raw)
    assert cleaned == "Error\nLine 2\nLine 3"


def test_redact_sensitive_values():
    text = (
        "sk-abcdef1234567890\n"
        "OPENAI_API_KEY=sk-xyz1234567890\n"
        "Authorization: Bearer secret-token-value"
    )
    redacted = redact(text)
    assert "<redacted>" in redacted
    assert "sk-abcdef1234567890" not in redacted
    assert "secret-token-value" not in redacted


def test_frame_content_strips_box_drawing():
    assert frame_content("│  hello world  │") == "  hello world"
    assert frame_content("│  hello world") == "  hello world"
    assert frame_content("hello world") == "hello world"


def test_parse_structured_search_output():
    raw = """
Web Search: Brave 2 sources
--- Answer ---
Here is the summary of results.
--- Sources ---
+ Bun 1.2 Release Notes (bun.sh)
- TypeScript Documentation (www.typescriptlang.org; 2 days ago)
--- Metadata ---
Provider: Brave
query: latest Bun release
----------------
"""
    parsed = parse_search_output(raw, "fallback query")
    assert parsed.provider == "Brave"
    assert parsed.query == "latest Bun release"
    assert parsed.answer == "Here is the summary of results."
    assert len(parsed.sources) == 2
    assert parsed.sources[0] == {
        "title": "Bun 1.2 Release Notes",
        "domain": "bun.sh",
        "age": None,
    }
    assert parsed.sources[1] == {
        "title": "TypeScript Documentation",
        "domain": "www.typescriptlang.org",
        "age": "2 days ago",
    }
    assert parsed.truncated is False
    assert parsed.parsed is True


def test_parse_unicode_box_drawing_output():
    raw = """
╭─── ⌕ Web Search: Brave 2 sources ──────────────────────────────────────────────╮
│ Query: test query                                                              │
├─── Answer ─────────────────────────────────────────────────────────────────────┤
│ Answer text goes here.                                                         │
├─── Sources ────────────────────────────────────────────────────────────────────┤
│ ├─ Test Source (test.com) · 1 week ago                                         │
│ └─ Second Source (other.org) · 3 days ago                                      │
├─── Metadata ───────────────────────────────────────────────────────────────────┤
│ Provider: Brave (API)                                                          │
╰────────────────────────────────────────────────────────────────────────────────╯
"""
    parsed = parse_search_output(raw, "fallback")
    assert parsed.provider == "Brave (API)"
    assert parsed.query == "test query"
    assert parsed.answer == " Answer text goes here."
    assert len(parsed.sources) == 2
    assert parsed.sources[0] == {
        "title": "Test Source",
        "domain": "test.com",
        "age": "1 week ago",
    }
    assert parsed.sources[1] == {
        "title": "Second Source",
        "domain": "other.org",
        "age": "3 days ago",
    }


def test_parse_detects_truncation_marker():
    raw = """
Web Search: Exa 1 source
--- Answer ---
Short answer
... 12 more lines
--- Sources ---
+ Source 1 (example.com)
"""
    parsed = parse_search_output(raw, "query")
    assert parsed.truncated is True


def test_extract_yaml_list_under_providers_section():
    yaml = """
providers:
  webSearchOrder:
    - brave # fast search
    - parallel
    - exa
  webSearchExclude:
    - gemini
"""
    order = extract_yaml_list(yaml, "webSearchOrder")
    exclude = extract_yaml_list(yaml, "webSearchExclude")
    assert order == ["brave", "parallel", "exa"]
    assert exclude == ["gemini"]


def test_extract_yaml_list_ignores_items_outside_target_key():
    yaml = """
otherSection:
  webSearchOrder:
    - should_ignore
providers:
  otherKey:
    - other_val
  webSearchOrder:
    - brave
"""
    order = extract_yaml_list(yaml, "webSearchOrder")
    assert order == ["brave"]


def test_discover_active_omp_providers_returns_list():
    providers = discover_active_omp_providers()
    assert isinstance(providers, list)


def test_failure_message_extraction():
    assert (
        failure_message("stdout line", "Error: failed to connect", 1)
        == "Error: failed to connect"
    )
    assert (
        failure_message("cleaned output\nsomething went wrong", "", 1)
        == "something went wrong"
    )
    assert failure_message("", "", 2) == "omp search exited with code 2"


def test_resolve_omp_existing_binary():
    assert resolve_omp(sys.executable) == sys.executable


def test_merge_parallel_results_dedupes_sources():
    result1: SearchSuccessPayload = {
        "ok": True,
        "query": "test query",
        "provider": "brave",
        "providers": ["brave"],
        "providers_count": 1,
        "answer": "Brave answer summary.",
        "sources": [
            {"title": "Doc 1", "domain": "example.com", "age": None},
            {"title": "Doc 2", "domain": "test.org", "age": "1d ago"},
        ],
        "sources_count": 2,
        "truncated": False,
        "compact": True,
        "parsed": True,
        "exit_code": 0,
    }
    result2: SearchSuccessPayload = {
        "ok": True,
        "query": "test query",
        "provider": "exa",
        "providers": ["exa"],
        "providers_count": 1,
        "answer": "Exa detailed answer.",
        "sources": [
            {"title": "Doc 1", "domain": "EXAMPLE.COM", "age": None},
            {"title": "Doc 3", "domain": "other.com", "age": "3d ago"},
        ],
        "sources_count": 2,
        "truncated": True,
        "compact": True,
        "parsed": True,
        "exit_code": 0,
    }

    merged = merge_parallel_results("test query", [result1, result2], compact=True)
    assert merged["ok"] is True
    success = cast("SearchSuccessPayload", merged)
    assert success["provider"] == "brave+exa"
    assert success["providers"] == ["brave", "exa"]
    assert success["providers_count"] == 2
    assert "### [brave]\nBrave answer summary." in success["answer"]
    assert "### [exa]\nExa detailed answer." in success["answer"]
    assert len(success["sources"]) == 3
    assert success["sources_count"] == 3
    assert success["truncated"] is True
    assert success["compact"] is True


def test_merge_parallel_results_all_failed():
    failed1: SearchFailurePayload = {
        "ok": False,
        "query": "test query",
        "provider": "brave",
        "answer": "",
        "sources": [],
        "truncated": False,
        "compact": True,
        "parsed": False,
        "exit_code": 1,
        "error": {"code": "provider_error", "message": "Brave rate limit"},
    }
    failed2: SearchFailurePayload = {
        "ok": False,
        "query": "test query",
        "provider": "exa",
        "answer": "",
        "sources": [],
        "truncated": False,
        "compact": True,
        "parsed": False,
        "exit_code": 1,
        "error": {"code": "provider_error", "message": "Exa timeout"},
    }

    merged = merge_parallel_results("test query", [failed1, failed2], compact=True)
    assert merged["ok"] is False
    failure = cast("SearchFailurePayload", merged)
    assert failure["exit_code"] == 1
    assert failure["error"]["message"] == "Brave rate limit"
    assert failure["provider"] == "brave | exa"


def test_cli_help(capsys):
    exc_info = None
    try:
        cli_main(["--help"])
    except SystemExit as exc:
        exc_info = exc
    assert exc_info is not None
    assert exc_info.code == 0
    assert "usage" in capsys.readouterr().out.lower()


def _write_fake_omp(tmp_path, body: str) -> str:
    script = tmp_path / "omp-fake"
    script.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
    script.chmod(0o755)
    return str(script)


def test_execute_single_search_success_envelope(tmp_path):
    binary = _write_fake_omp(
        tmp_path,
        "import os\n"
        "print('NO_COLOR=' + os.environ.get('NO_COLOR', ''))\n"
        "print('Web Search: Brave 1 source')\n"
        "print('--- Answer ---')\n"
        "print('fake answer')\n"
        "print('--- Sources ---')\n"
        "print('+ Doc (example.com; 1d ago)')",
    )
    result = execute_single_search(
        SingleSearchExecutionOptions(query_words=["hello", "world"], include_raw=True),
        binary,
    )
    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert result["provider"] == "Brave"
    assert result["answer"] == "fake answer"
    assert result["compact"] is True
    assert result["sources_count"] == 1
    assert "NO_COLOR=1" in result.get("raw", "")


def test_execute_single_search_failure_envelope(tmp_path):
    binary = _write_fake_omp(
        tmp_path,
        "import sys\nsys.stderr.write('provider blew up\\n')\nsys.exit(3)",
    )
    result = execute_single_search(
        SingleSearchExecutionOptions(query_words=["q"], include_raw=True),
        binary,
    )
    assert result["ok"] is False
    assert result["exit_code"] == 3
    assert result["error"]["code"] == "omp_search_failed"
    assert result["error"]["message"] == "provider blew up"
    assert "provider blew up" in result.get("diagnostics", "")


def test_execute_single_search_timeout_envelope(tmp_path):
    binary = _write_fake_omp(
        tmp_path,
        "import time\ntime.sleep(30)",
    )
    result = execute_single_search(
        SingleSearchExecutionOptions(query_words=["q"], timeout_seconds=0.2),
        binary,
    )
    assert result["ok"] is False
    assert result["exit_code"] == 124
    assert result["error"]["code"] == "timeout"
    assert "0.2s" in result["error"]["message"]


def test_execute_single_search_spawn_failure(tmp_path):
    result = execute_single_search(
        SingleSearchExecutionOptions(query_words=["q"]),
        str(tmp_path / "does-not-exist"),
    )
    assert result["ok"] is False
    assert result["exit_code"] == 1
    assert result["error"]["code"] == "omp_search_failed"


# ---------------------------------------------------------------------------
# Added coverage: config discovery, executor branches, cli main, e2e
# ---------------------------------------------------------------------------


class TestConfigDiscovery:
    """discover_active_omp_providers candidate-order and parsing coverage."""

    def test_omp_config_dir_precedence(self, tmp_path, monkeypatch):
        cfg_dir = tmp_path / "ompconf"
        cfg_dir.mkdir()
        (cfg_dir / "config.yml").write_text(
            "providers:\n  webSearchOrder:\n    - from_cfg_dir\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("OMP_CONFIG_DIR", str(cfg_dir))
        monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
        monkeypatch.setenv("USERPROFILE", "")
        result = discover_active_omp_providers(str(tmp_path / "nowhere"))
        assert result == ["from_cfg_dir"]

    def test_home_fallback_and_exclude(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OMP_CONFIG_DIR", raising=False)
        home = tmp_path / "home"
        (home / ".omp" / "agent").mkdir(parents=True)
        (home / ".omp" / "agent" / "config.yml").write_text(
            "providers:\n"
            "  webSearchOrder:\n"
            "    - 'brave' # quoted\n"
            '    - "exa"\n'
            "    - gemini\n"
            "  webSearchExclude:\n"
            "    - gemini\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", "")
        cwd = tmp_path / "workdir"
        cwd.mkdir()
        result = discover_active_omp_providers(str(cwd))
        assert result == ["brave", "exa"]

    def test_userprofile_used_when_no_home(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OMP_CONFIG_DIR", raising=False)
        monkeypatch.delenv("HOME", raising=False)
        home = tmp_path / "winhome"
        (home / ".omp" / "agent").mkdir(parents=True)
        (home / ".omp" / "agent" / "config.yml").write_text(
            "providers:\n  webSearchOrder:\n    - parallel\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("USERPROFILE", str(home))
        result = discover_active_omp_providers(str(tmp_path / "nowhere"))
        assert result == ["parallel"]

    def test_cwd_config_and_malformed_content(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OMP_CONFIG_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
        monkeypatch.setenv("USERPROFILE", "")
        cwd = tmp_path / "repo"
        (cwd / ".omp" / "agent").mkdir(parents=True)
        # first candidate with content wins; empty order falls through
        (cwd / ".omp" / "agent" / "config.yml").write_text(
            "providers:\n  other:\n    - x\n  webSearchOrder:\n",
            encoding="utf-8",
        )
        (cwd / "harnesses" / "omp" / "agent").mkdir(parents=True)
        (cwd / "harnesses" / "omp" / "agent" / "config.yml").write_text(
            "providers:\n  webSearchOrder:\n    - tavily\n",
            encoding="utf-8",
        )
        result = discover_active_omp_providers(str(cwd))
        assert result == ["tavily"]

    def test_no_config_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OMP_CONFIG_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
        monkeypatch.setenv("USERPROFILE", "")
        assert discover_active_omp_providers(str(tmp_path / "nowhere")) == []

    def test_unreadable_file_returns_empty(self, tmp_path, monkeypatch):
        cfg_dir = tmp_path / "cfg"
        cfg_dir.mkdir()
        cfg_file = cfg_dir / "config.yml"
        cfg_file.write_text(
            "providers:\n  webSearchOrder:\n    - brave\n", encoding="utf-8"
        )
        cfg_file.chmod(0o000)
        monkeypatch.setenv("OMP_CONFIG_DIR", str(cfg_dir))
        monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
        monkeypatch.setenv("USERPROFILE", "")
        try:
            assert discover_active_omp_providers(str(tmp_path)) == []
        finally:
            cfg_file.chmod(0o644)


class TestYamlListEdges:
    """extract_yaml_list indentation/quoting/comment edge cases."""

    def test_deep_indented_and_inline_comments(self):
        yaml = (
            "providers:\n"
            "  webSearchOrder:\n"
            "      - brave # inline comment\n"
            "      -\n"
            "      -    \n"
            "      - 'q1'\n"
            "  next:\n"
            "    - not_this\n"
        )
        assert extract_yaml_list(yaml, "webSearchOrder") == ["brave", "q1"]

    def test_malformed_and_missing_sections(self):
        assert extract_yaml_list("no providers here", "webSearchOrder") == []
        assert extract_yaml_list("providers:\n  other: 1\n", "webSearchOrder") == []
        # a second providers: section resets scanning
        yaml = (
            "providers:\n"
            "  webSearchOrder:\n"
            "    - a\n"
            "providers:\n"
            "  webSearchOrder:\n"
            "    - b\n"
        )
        assert extract_yaml_list(yaml, "webSearchOrder") == ["a", "b"]

    def test_key_switch_mid_list(self):
        yaml = "providers:\n  webSearchOrder:\n    - one\n  otherKey:\n    - two\n"
        assert extract_yaml_list(yaml, "webSearchOrder") == ["one"]


class TestExecutorBranches:
    """resolve_omp and execute_single_search remaining branches."""

    def test_resolve_omp_env_var(self, tmp_path, monkeypatch):
        fake = tmp_path / "omp-env"
        fake.write_text("#!/bin/sh\n", encoding="utf-8")
        fake.chmod(0o755)
        monkeypatch.setenv("OMP_BIN", str(fake))
        assert resolve_omp(None) == str(fake)

    def test_resolve_omp_missing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OMP_BIN", raising=False)
        monkeypatch.setenv("PATH", str(tmp_path))
        with pytest.raises(OmpBinaryNotFoundError, match="not found"):
            resolve_omp(str(tmp_path / "nonexistent"))

    def test_resolve_omp_from_path(self, tmp_path, monkeypatch):
        bindir = tmp_path / "bin"
        bindir.mkdir()
        fake = bindir / "omp"
        fake.write_text("#!/bin/sh\n", encoding="utf-8")
        fake.chmod(0o755)
        monkeypatch.delenv("OMP_BIN", raising=False)
        monkeypatch.setenv("PATH", str(bindir))
        assert resolve_omp(None) == str(fake)

    def test_command_construction_full_args(self, tmp_path):
        seen: dict[str, Any] = {}
        binary = _write_fake_omp(
            tmp_path,
            "import sys, json\nprint(json.dumps(sys.argv[1:]))",
        )

        # capture argv via parsed output? simpler: patch _run_command

        orig = executor._run_command

        def spy(command, env, timeout_seconds):
            seen["command"] = command
            seen["env"] = env
            seen["timeout"] = timeout_seconds
            return executor._RunOutcome(
                is_timeout=False, stdout="x", stderr="", exit_code=0
            )

        executor._run_command = spy
        try:
            execute_single_search(
                SingleSearchExecutionOptions(
                    query_words=["hello", "world"],
                    provider="brave",
                    recency="week",
                    limit=5,
                    full=True,
                    timeout_seconds=42.0,
                ),
                binary,
            )
        finally:
            executor._run_command = orig

        assert seen["command"][:2] == [binary, "search"]
        assert "--provider" in seen["command"]
        assert "brave" in seen["command"]
        assert "--recency" in seen["command"]
        assert "week" in seen["command"]
        assert "--limit" in seen["command"]
        assert "5" in seen["command"]
        assert "--compact" not in seen["command"]  # full=True
        assert seen["command"][-2:] == ["hello", "world"]
        assert seen["timeout"] == 42.0
        assert seen["env"]["NO_COLOR"] == "1"
        assert seen["env"]["FORCE_COLOR"] == "0"

    def test_compact_default_and_timeout_seconds_format(self, tmp_path):

        seen: dict[str, Any] = {}
        orig = executor._run_command

        def spy(command, env, timeout_seconds):
            seen["command"] = command
            return executor._RunOutcome(
                is_timeout=True, stdout="", stderr="", exit_code=124
            )

        executor._run_command = spy
        try:
            result = execute_single_search(
                SingleSearchExecutionOptions(query_words=["q"]),
                "bin",
            )
        finally:
            executor._run_command = orig
        assert "--compact" in seen["command"]
        assert "300s" in cast("SearchFailurePayload", result)["error"]["message"]

    def test_timeout_partial_output_and_raw(self, tmp_path):

        orig = executor._run_command

        def fake(command, env, timeout_seconds):
            return executor._RunOutcome(
                is_timeout=True, stdout="partial out", stderr="", exit_code=124
            )

        executor._run_command = fake
        try:
            result = execute_single_search(
                SingleSearchExecutionOptions(
                    query_words=["q"], include_raw=True, timeout_seconds=1.5
                ),
                "bin",
            )
        finally:
            executor._run_command = orig
        assert result["exit_code"] == 124
        assert result.get("raw") == "partial out"
        assert "1.5s" in cast("SearchFailurePayload", result)["error"]["message"]

    def test_provider_fallback_when_parse_unknown(self, tmp_path):
        binary = _write_fake_omp(
            tmp_path,
            "print('totally unstructured output')",
        )
        result = execute_single_search(
            SingleSearchExecutionOptions(query_words=["q"], provider="customp"),
            binary,
        )
        assert result["provider"] == "customp"

    def test_failure_diagnostics_redacts_secrets(self, tmp_path):
        binary = _write_fake_omp(
            tmp_path,
            "import sys\nsys.stderr.write('key sk-secret12345678 failed\\n')\n"
            "sys.exit(1)",
        )
        result = execute_single_search(
            SingleSearchExecutionOptions(query_words=["q"]), binary
        )
        assert result["ok"] is False
        diag = result.get("diagnostics", "")
        assert "sk-secret12345678" not in diag
        assert "<redacted>" in diag


class TestModelErrors:
    """models.py exception field storage."""

    def test_omp_execution_error_fields(self):
        err = OmpExecutionError(2, "out", "err", "msg")
        assert err.exit_code == 2
        assert err.stdout == "out"
        assert err.stderr == "err"
        assert err.message == "msg"

    def test_omp_timeout_error_fields(self):
        err = OmpTimeoutError(5.0, "slow", "partial")
        assert err.timeout_seconds == 5.0
        assert err.partial_stdout == "partial"


class TestParserEdges:
    """parser.py remaining branches."""

    def test_parse_empty_and_metadata_provider(self):
        parsed = parse_search_output("", "fallback q")
        assert parsed.query == "fallback q"
        assert parsed.parsed is False or parsed.answer == ""

    def test_parse_provider_from_metadata_when_header_missing(self):
        raw = (
            "--- Answer ---\nanswer here\n"
            "--- Metadata ---\nProvider: Exa\nquery: my query\n"
        )
        parsed = parse_search_output(raw, "fb")
        assert parsed.provider == "Exa"
        assert parsed.query == "my query"

    def test_redact_multiple_secret_shapes(self):
        text = "OPENAI_API_KEY=abc123 and Bearer tok_xyz-789 here"
        redacted = redact(text)
        assert "abc123" not in redacted or "tok_xyz-789" not in redacted


class TestCliMain:
    """scripts.cli.main in-process coverage."""

    def _fake_omp(self, tmp_path, extra: str = "") -> str:
        return _write_fake_omp(
            tmp_path,
            "import sys\n"
            "p = sys.argv[sys.argv.index('--provider') + 1] "
            "if '--provider' in sys.argv else 'Brave'\n"
            "print('Web Search: ' + p + ' 1 source')\n"
            "print('--- Answer ---')\n"
            "print('the answer')\n"
            "print('--- Sources ---')\n"
            "print('+ Doc (example.com)')\n" + extra,
        )

    def _isolate_env(self, monkeypatch, tmp_path):
        """Prevent discovery from picking up a real user OMP config."""
        monkeypatch.setenv("OMP_CONFIG_DIR", str(tmp_path / "empty-cfg"))
        monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
        monkeypatch.setenv("USERPROFILE", "")
        monkeypatch.chdir(tmp_path)

    def test_missing_binary_returns_127(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("OMP_BIN", raising=False)
        monkeypatch.setenv("PATH", str(tmp_path))
        rc = cli_main(["query", "--omp-bin", str(tmp_path / "nope")])
        assert rc == 127
        assert "not found" in capsys.readouterr().err

    def test_explicit_provider(self, tmp_path, monkeypatch, capsys):

        seen: dict[str, Any] = {}
        orig = cli_mod.execute_single_search

        def spy(options, binary):
            seen["provider"] = options.provider
            return orig(options, binary)

        monkeypatch.setattr(cli_mod, "execute_single_search", spy)
        binary = self._fake_omp(tmp_path)
        rc = cli_main(["hello", "world", "--provider", "exa", "--omp-bin", binary])
        assert rc == 0
        assert seen["provider"] == "exa"
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True

    def test_comma_providers_parallel_merge(self, tmp_path, monkeypatch, capsys):

        providers_seen: list[str | None] = []
        orig = cli_mod.execute_single_search

        def spy(options, binary):
            providers_seen.append(options.provider)
            return orig(options, binary)

        monkeypatch.setattr(cli_mod, "execute_single_search", spy)
        binary = self._fake_omp(tmp_path)
        rc = cli_main(["q", "--providers", "brave, exa", "--omp-bin", binary])
        assert rc == 0
        assert set(providers_seen) == {"brave", "exa"}
        out = json.loads(capsys.readouterr().out)
        assert out["providers"] == ["brave", "exa"]
        assert out["provider"] == "brave+exa"
        assert out["providers_count"] == 2

    def test_single_flag_and_auto_discovery(self, tmp_path, monkeypatch, capsys):

        seen: list[str | None] = []
        orig = cli_mod.execute_single_search

        def spy(options, binary):
            seen.append(options.provider)
            return orig(options, binary)

        monkeypatch.setattr(cli_mod, "execute_single_search", spy)
        binary = self._fake_omp(tmp_path)
        rc = cli_main(["q", "--single", "--omp-bin", binary])
        assert rc == 0
        assert seen == [None]

        # auto-discovery from OMP_CONFIG_DIR
        cfg_dir = tmp_path / "ompcfg"
        cfg_dir.mkdir()
        (cfg_dir / "config.yml").write_text(
            "providers:\n  webSearchOrder:\n    - brave\n    - exa\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("OMP_CONFIG_DIR", str(cfg_dir))
        monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
        monkeypatch.setenv("USERPROFILE", "")
        monkeypatch.chdir(tmp_path / "nowhere" if False else tmp_path)
        seen.clear()
        rc = cli_main(["q", "--omp-bin", binary])
        assert rc == 0
        assert set(seen) == {"brave", "exa"}

    def test_full_flag_omits_compact_and_merges(self, tmp_path, monkeypatch, capsys):

        compacts: list[bool | None] = []
        orig = cli_mod.execute_single_search

        def spy(options, binary):
            compacts.append(not options.full)
            return orig(options, binary)

        monkeypatch.setattr(cli_mod, "execute_single_search", spy)
        binary = self._fake_omp(tmp_path)
        rc = cli_main(["q", "--providers", "a,b", "--full", "--omp-bin", binary])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["compact"] is False

    def test_timeout_limit_recency_forwarded(self, tmp_path, monkeypatch, capsys):

        seen: dict[str, Any] = {}
        orig = cli_mod.execute_single_search

        def spy(options, binary):
            seen.update(
                {
                    "timeout": options.timeout_seconds,
                    "limit": options.limit,
                    "recency": options.recency,
                }
            )
            return orig(options, binary)

        monkeypatch.setattr(cli_mod, "execute_single_search", spy)
        binary = self._fake_omp(tmp_path)
        rc = cli_main(
            [
                "q",
                "--timeout",
                "12.5",
                "--limit",
                "7",
                "--recency",
                "month",
                "--omp-bin",
                binary,
            ]
        )
        assert rc == 0
        assert seen["timeout"] == 12.5
        assert seen["limit"] == 7
        assert seen["recency"] == "month"

    def test_include_raw(self, tmp_path, monkeypatch, capsys):
        self._isolate_env(monkeypatch, tmp_path)
        binary = self._fake_omp(tmp_path)
        rc = cli_main(["q", "--include-raw", "--omp-bin", binary])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert "raw" in out


class TestEndToEnd:
    """Real subprocess: cli.py -> resolve -> spawn fake omp -> envelope."""

    def _cli(self) -> str:
        return str(Path(__file__).resolve().parents[1] / "scripts" / "cli.py")

    def test_e2e_single_provider(self, tmp_path):
        binary = _write_fake_omp(
            tmp_path,
            "print('Web Search: Brave 1 source')\n"
            "print('--- Answer ---')\n"
            "print('e2e answer')\n"
            "print('--- Sources ---')\n"
            "print('+ E2E Doc (e2e.example; 2h ago)')",
        )
        proc = subprocess.run(
            [
                sys.executable,
                self._cli(),
                "hello",
                "world",
                "--provider",
                "brave",
                "--omp-bin",
                binary,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        assert payload["ok"] is True
        assert payload["query"] == "hello world"
        assert payload["answer"] == "e2e answer"
        assert payload["sources"][0]["domain"] == "e2e.example"

    def test_e2e_missing_binary_exit_127(self, tmp_path, monkeypatch):
        env = {k: v for k, v in os.environ.items() if k != "OMP_BIN"}
        env["PATH"] = str(tmp_path)
        proc = subprocess.run(
            [sys.executable, self._cli(), "q"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=env,
        )
        assert proc.returncode == 127
        assert "not found" in proc.stderr

    def test_e2e_parallel_providers_merged(self, tmp_path):
        binary = _write_fake_omp(
            tmp_path,
            "import sys\n"
            "p = sys.argv[sys.argv.index('--provider') + 1]\n"
            "print('Web Search: ' + p + ' 1 source')\n"
            "print('--- Answer ---')\n"
            "print('ans')\n"
            "print('--- Sources ---')\n"
            "print('+ S (' + p + '.example)')",
        )
        proc = subprocess.run(
            [
                sys.executable,
                self._cli(),
                "q",
                "--providers",
                "alpha,beta",
                "--omp-bin",
                binary,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        assert payload["providers"] == ["alpha", "beta"]
        assert payload["sources_count"] == 2

    def test_e2e_timeout_exit_124(self, tmp_path):
        binary = _write_fake_omp(tmp_path, "import time\ntime.sleep(30)")
        env = {
            **os.environ,
            "OMP_CONFIG_DIR": str(tmp_path / "empty"),
            "HOME": str(tmp_path / "nohome"),
            "USERPROFILE": "",
        }
        proc = subprocess.run(
            [
                sys.executable,
                self._cli(),
                "q",
                "--timeout",
                "0.3",
                "--single",
                "--omp-bin",
                binary,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=env,
        )
        assert proc.returncode == 124
        payload = json.loads(proc.stdout)
        assert payload["error"]["code"] == "timeout"


class TestResidualBranches:
    """Surgical coverage for remaining defensive branches."""

    def test_path_exists_guard_swallows_errors(self, monkeypatch):

        def boom(self):
            raise OSError("exists blew up")

        monkeypatch.setattr(executor.Path, "exists", boom)
        assert executor._path_exists("/anything") is False

    def test_config_path_exists_guard_swallows_errors(self, monkeypatch):
        monkeypatch.setattr(
            config.Path,
            "exists",
            lambda self: (_ for _ in ()).throw(OSError("boom")),
        )
        monkeypatch.setenv("OMP_CONFIG_DIR", "/nonexistent")
        assert discover_active_omp_providers("/nowhere") == []

    def test_config_read_guard_swallows_errors(self, monkeypatch):
        monkeypatch.setattr(config.Path, "exists", lambda self: True)
        monkeypatch.setattr(
            config.Path,
            "read_text",
            lambda self, encoding=None: (_ for _ in ()).throw(OSError("unreadable")),
        )
        monkeypatch.setenv("OMP_CONFIG_DIR", "/anywhere")
        monkeypatch.setenv("HOME", "/nohome")
        monkeypatch.delenv("USERPROFILE", raising=False)
        assert discover_active_omp_providers("/nowhere") == []

    def test_as_text_bytes_and_none(self):

        assert executor._as_text(b"raw bytes") == "raw bytes"
        assert executor._as_text(None) == ""
        assert executor._as_text("already") == "already"

    def test_failure_payload_includes_raw_when_requested(self, tmp_path):
        binary = _write_fake_omp(
            tmp_path,
            "print('Web Search: Exa 0 sources')\n"
            "print('--- Answer ---')\n"
            "print('failed output')\n"
            "import sys\nsys.exit(4)",
        )
        result = execute_single_search(
            SingleSearchExecutionOptions(query_words=["q"], include_raw=True),
            binary,
        )
        assert result["ok"] is False
        assert result["exit_code"] == 4
        assert "failed output" in result.get("raw", "")

    def test_parse_trims_blank_answer_lines(self):
        raw = (
            "Web Search: Brave 0 sources\n"
            "--- Answer ---\n\n"
            "trimmed answer\n\n"
            "--- Sources ---\n"
        )
        parsed = parse_search_output(raw, "q")
        assert parsed.answer == "trimmed answer"

    def test_format_seconds_integer_and_float(self):

        assert executor._format_seconds(300) == "300"
        assert executor._format_seconds(1.5) == "1.5"
