# Copyright 2026 Vals-live contributors.
"""Exercise fixture and diagnostic credential redaction."""

import json
import re
import unittest

from _path import ROOT
from vals_live.diagnostics import redact

_SECRET = re.compile(
    r"(?i)(authorization\s*[:=]|cookie\s*[:=]|bearer\s+"
    + r"[A-Za-z0-9._-]{8,}|-----BEGIN .*PRIVATE KEY-----)"
)


class SecurityTests(unittest.TestCase):
    """Verify fixture credential scanning and redaction."""

    def test_fixture_tree_has_no_credentials(self) -> None:
        for path in (ROOT / "tests" / "fixtures").rglob("*"):
            if not path.is_file():
                continue
            assert (
                _SECRET.search(path.read_text(encoding="utf-8", errors="replace"))
                is None
            ), str(path)

    def test_redaction_never_emits_auth_or_cookie(self) -> None:
        value = redact(
            {
                "Authorization": "Bearer super-secret",
                "Cookie": "session=secret",
                "source_url": "https://www.vals.ai/benchmarks",
            }
        )
        encoded = json.dumps(value)
        assert "super-secret" not in encoded
        assert "session=secret" not in encoded
        assert "<redacted>" in encoded


if __name__ == "__main__":
    _ = unittest.main()
