"""Pure redaction checks supplement the subprocess workflow suite."""

import pytest
from autoreview.redaction import (
    filter_diff_paths,
    is_sensitive_path,
    redact_sensitive_text,
)


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
    line1 = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
    line2 = "api_key = 'abcdef12345678901234567890'"
    line3 = "normal_code = true"
    payload = f"{line1}\n{line2}\n{line3}\n"
    redacted = redact_sensitive_text(payload)
    assert "[REDACTED PRIVATE KEY BLOCK]" in redacted
    assert "api_key = [REDACTED]" in redacted
    assert "normal_code = true" in redacted
