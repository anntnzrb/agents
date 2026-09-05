"""Security and metrics-only fixture checks for DeepSWE release artifacts."""

from __future__ import annotations

import io
import json
import re
import socket
import urllib.request
from pathlib import Path
from typing import cast

import pytest

from deepswe import cli
from deepswe.diagnostics import redact
from deepswe.provenance import artifact_evidence

FIXTURES = Path(__file__).parent / "fixtures"
_SECRET_TEXT = re.compile(
    r"""(?ix)
    (?:bearer\s+[A-Za-z0-9._~+/=-]+
    |(?:api[_-]?key|access[_-]?token|password|secret|authorization)\s*[:=]\s*(?!<redacted>)[^\s,}\"]+
    |-----BEGIN [^-\r\n]*PRIVATE KEY-----)
    """
)
_FORBIDDEN_CONTENT = re.compile(
    r"(?i)(?:task[-_ ]?body|exercise[-_ ]?body|trajectory[-_ ]?body)"
)


def _fixture_texts() -> list[tuple[Path, str]]:
    return [
        (path, path.read_text(encoding="utf-8"))
        for path in sorted(FIXTURES.rglob("*"))
        if path.is_file() and path.suffix in {".json", ".txt"}
    ]


def test_fixture_tree_has_no_credential_like_values() -> None:
    """Keep deterministic fixtures safe to ship and inspect."""
    for path, text in _fixture_texts():
        assert not _SECRET_TEXT.search(text), path
        assert not _FORBIDDEN_CONTENT.search(text), path
        parsed = json.loads(text) if path.suffix == ".json" else None
        if parsed is not None:
            assert "task-body" not in json.dumps(parsed)


def test_redaction_removes_credentials_but_preserves_metrics_and_safe_urls() -> None:
    """Redact headers/query secrets without hiding harmless metrics."""
    payload = {
        "Authorization": "Bearer fixture-secret-token",
        "Cookie": "session=fixture-cookie",
        "api_key": "fixture-api-key",
        "query": "https://example.test/data.json?token=query-secret&keep=value",
        "metric": "token_count",
        "value": "tokens",
        "url": "https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json",
    }
    safe = cast("dict[str, object]", redact(payload))
    encoded = json.dumps(safe, sort_keys=True)
    for secret in (
        "fixture-secret-token",
        "fixture-cookie",
        "fixture-api-key",
        "query-secret",
    ):
        assert secret not in encoded
    assert safe["metric"] == "token_count"
    assert safe["value"] == "tokens"
    assert isinstance(safe["url"], str)
    assert safe["url"].endswith("leaderboard-live.json")
    assert "keep=value" in str(safe["query"])


def test_provenance_redacts_nested_transport_metadata() -> None:
    """Persisted provenance must not expose header or query credentials."""
    evidence = artifact_evidence(
        metadata={
            "url": "https://example.test/data.json?access_token=source-secret",
            "headers": {
                "Authorization": "Bearer header-secret",
                "Cookie": "session=cookie-secret",
            },
        },
        body=b'{"metric": 0.5}',
        benchmark_version="v1.1",
    )
    encoded = json.dumps(evidence)
    for secret in ("source-secret", "header-secret", "cookie-secret"):
        assert secret not in encoded
    assert evidence["artifact_sha256"]
    assert evidence["benchmark_version"] == "v1.1"


def test_offline_guard_blocks_url_and_socket_calls() -> None:
    """The autouse policy rejects accidental transport in deterministic tests."""
    with pytest.raises(AssertionError, match="network access is disabled"):
        _ = cast("object", urllib.request.urlopen("https://example.test"))
    with pytest.raises(AssertionError, match="network access is disabled"):
        _ = socket.create_connection(("example.test", 443))


def test_phase6_fixtures_cover_evidence_and_schema_diff() -> None:
    """Exercise the small fixture set used by release-evaluation prompts."""
    evidence = FIXTURES / "phase6" / "evidence.json"
    left = FIXTURES / "phase6" / "schema-left.json"
    right = FIXTURES / "phase6" / "schema-right.json"

    diagnose_out = io.StringIO()
    diagnose_err = io.StringIO()
    assert (
        cli.main(
            ["diagnose", "--snapshot", str(evidence)],
            stdout=diagnose_out,
            stderr=diagnose_err,
        )
        == 0
    )
    diagnose = cast("dict[str, object]", json.loads(diagnose_out.getvalue()))
    assert diagnose["ok"] is True
    diagnose_data = cast("dict[str, object]", diagnose["data"])
    diagnose_scope = cast("dict[str, object]", diagnose_data["scope"])
    assert diagnose_scope["benchmark"] == "DeepSWE"
    assert "task-body" not in diagnose_out.getvalue()

    compare_out = io.StringIO()
    compare_err = io.StringIO()
    assert (
        cli.main(
            [
                "compare",
                str(left),
                str(right),
                "--version",
                "v1.1",
                "--strict-compare",
            ],
            stdout=compare_out,
            stderr=compare_err,
        )
        == 0
    )
    comparison = cast("dict[str, object]", json.loads(compare_out.getvalue()))
    comparison_data = cast("dict[str, object]", comparison["data"])
    comparison_blocked = cast("list[dict[str, object]]", comparison_data["blocked"])
    assert comparison_blocked[0]["reason"] == "schema_mismatch"
    assert comparison_data["changes"] == []
