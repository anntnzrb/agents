"""Comprehensive unit and integration test suite for AutoReview."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Add lib/ to sys.path for test execution
_LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from autoreview.cli import format_human_report
from autoreview.git_ops import safe_git_env
from autoreview.redaction import (
    filter_diff_paths,
    is_sensitive_path,
    redact_sensitive_text,
)
from autoreview.verification import (
    filter_findings_by_priority,
    validate_finding_structure,
    verify_physical_line_exists,
)

CLI_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "cli.py"


def test_cli_help_flag() -> None:
    """Verify that the CLI provides help output with valid zero exit code."""
    proc = subprocess.run(
        [sys.executable, str(CLI_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "usage:" in proc.stdout.lower()
    assert "--mode" in proc.stdout
    assert "--max-priority" in proc.stdout


def test_cli_dry_run_execution() -> None:
    """Verify that --dry-run captures bundle metadata without errors."""
    proc = subprocess.run(
        [sys.executable, str(CLI_SCRIPT), "--mode", "local", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "AutoReview [Dry Run]" in proc.stdout


def test_safe_git_env_sanitization() -> None:
    """Verify that safe_git_env blocks user configs and graft files."""
    env = safe_git_env(Path.cwd())
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert env["GIT_OPTIONAL_LOCKS"] == "0"
    assert "LANG" in env


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".env", True),
        ("config/.env.local", True),
        ("secrets/id_rsa", True),
        (".ssh/authorized_keys", True),
        ("server.pem", True),
        ("src/main.ts", False),
        ("lib/util.py", False),
        ("docs/README.md", False),
    ],
)
def test_sensitive_path_detection(path: str, expected: bool) -> None:
    """Verify sensitive credential and path detection logic."""
    assert is_sensitive_path(path) == expected


def test_filter_diff_paths() -> None:
    """Verify separation of safe vs sensitive paths."""
    paths = ["src/index.ts", ".env", "certs/server.key", "package.json"]
    kept, redacted = filter_diff_paths(paths)
    assert kept == ["src/index.ts", "package.json"]
    assert redacted == [".env", "certs/server.key"]


def test_redact_sensitive_text() -> None:
    """Verify regex redacting of private keys and tokens."""
    payload = (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----\n"
        "api_key = 'abcdef12345678901234567890'\n"
        "normal_code = true\n"
    )
    redacted = redact_sensitive_text(payload)
    assert "[REDACTED PRIVATE KEY BLOCK]" in redacted
    assert "api_key = [REDACTED]" in redacted
    assert "normal_code = true" in redacted


def test_validate_finding_structure_valid() -> None:
    """Verify validation passes for compliant findings."""
    valid_finding = {
        "title": "Unchecked error return",
        "body": "Function may throw without catch block.",
        "priority": "P1",
        "confidence": 0.9,
        "category": "bug",
        "code_location": {"file_path": "src/app.ts", "line": 15},
    }
    validate_finding_structure(valid_finding, 0)


def test_validate_finding_structure_invalid() -> None:
    """Verify validation rejects malformed findings."""
    invalid_finding = {
        "title": "Missing category",
        "priority": "P5",
        "confidence": 1.5,
    }
    with pytest.raises(ValueError, match="missing required fields"):
        validate_finding_structure(invalid_finding, 0)


def test_verify_physical_line_exists() -> None:
    """Verify that physical lines are verified against actual file content."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo = Path(tmp_dir)
        test_file = repo / "foo.py"
        test_file.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")

        assert verify_physical_line_exists(repo, "foo.py", 2) is True
        assert verify_physical_line_exists(repo, "foo.py", 10) is False
        assert verify_physical_line_exists(repo, "missing.py", 1) is False


def test_filter_findings_by_priority() -> None:
    """Verify severity threshold filtering logic."""
    findings = [
        {"title": "P0 Blocker", "priority": "P0"},
        {"title": "P1 High", "priority": "P1"},
        {"title": "P2 Med", "priority": "P2"},
        {"title": "P3 Low", "priority": "P3"},
    ]
    kept, filtered = filter_findings_by_priority(findings, "P1")
    assert len(kept) == 2
    assert [f["title"] for f in kept] == ["P0 Blocker", "P1 High"]
    assert len(filtered) == 2


def test_format_human_report() -> None:
    """Verify human report string formatting."""
    report = {
        "overall_correctness": "patch is correct",
        "overall_explanation": "All good",
        "findings": [
            {
                "title": "Test Finding",
                "priority": "P1",
                "category": "bug",
                "confidence": 0.95,
                "body": "Explain",
                "code_location": {"file_path": "a.ts", "line": 5},
            }
        ],
    }
    rendered = format_human_report(report)
    assert "=== AutoReview Summary ===" in rendered
    assert "[P1] Test Finding (bug)" in rendered
    assert "Location: a.ts:5" in rendered
