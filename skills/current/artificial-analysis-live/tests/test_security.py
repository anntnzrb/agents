"""Credential redaction and immutable artifact safety tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from artificial_analysis.diagnostics import REDACTED, redact
from artificial_analysis.provenance import ArtifactStore

FIXTURES = Path(__file__).parent / "fixtures"


def test_fixture_tree_contains_no_credential_material() -> None:
    serialized = b"\n".join(
        path.read_bytes()
        for path in sorted(FIXTURES.rglob("*"))
        if path.is_file() and path.name != ".env"
    )
    text = serialized.decode("utf-8")

    assert "super-secret" not in text
    assert "Bearer " not in text
    assert "api_key=" not in text.casefold()
    assert "authorization:" not in text.casefold()


def test_redaction_preserves_safe_metrics_and_public_url_shape() -> None:
    payload = {
        "score": 42.5,
        "output_tokens": 100,
        "source_url": "https://example.test/public?token=do-not-leak&tab=score",
        "headers": {"Authorization": "Bearer do-not-leak", "cookie": "sid=secret"},
        "api_key": "do-not-leak",
    }
    redacted = cast("dict[str, object]", redact(payload))
    encoded = json.dumps(redacted, sort_keys=True)

    assert redacted["score"] == 42.5
    assert redacted["output_tokens"] == 100
    assert "tab=score" in cast("str", redacted["source_url"])
    assert REDACTED in encoded
    assert "do-not-leak" not in encoded
    assert "sid=secret" not in encoded


def test_artifact_store_manifest_is_immutable_and_redacted(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "cache")
    _ = store.store(
        "fixture-source",
        b'{"score":42.5}',
        {
            "source_url": "https://example.test/public",
            "authorization": "Bearer do-not-leak",
            "safe_metric": 42.5,
        },
    )
    manifest = store.write_manifest()
    assert manifest["sha256"] == manifest["manifest_sha256"]

    serialized = b"\n".join(
        path.read_bytes()
        for path in sorted((tmp_path / "cache").rglob("*"))
        if path.is_file()
    )
    text = serialized.decode("utf-8")
    assert "do-not-leak" not in text
    assert "42.5" in text
