# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Boundary tests for static release manifest fetching and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
import pytest

from sync.core.release_manifest import (
    StaticReleaseManifest,
    fetch_static_release_manifest,
)

VALID_SHA256 = "a" * 64


@dataclass(frozen=True, slots=True)
class _FakeResponse:
    """Minimal stand-in for the httpx response surface the fetcher reads."""

    status_code: int
    text: str


def _valid_payload() -> dict[str, object]:
    """Return a minimal well-formed manifest payload."""
    return {
        "version": "1.2.3",
        "platforms": {
            "darwin-arm64": {
                "url": "https://cdn.example.test/devin.tar.gz",
                "sha256": VALID_SHA256,
            }
        },
    }


def _install_get(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: _FakeResponse | None = None,
    error: BaseException | None = None,
    calls: list[tuple[str, float, bool]] | None = None,
) -> None:
    """Replace httpx.get with a fake that records its call and replays one outcome."""

    def _fake_get(
        url: str,
        *,
        timeout: float,
        follow_redirects: bool,
    ) -> _FakeResponse:
        if calls is not None:
            calls.append((url, timeout, follow_redirects))
        if error is not None:
            raise error
        assert response is not None
        return response

    monkeypatch.setattr("sync.core.release_manifest.httpx.get", _fake_get)


def test_fetch_manifest_parses_valid_payload_and_converts_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A well-formed payload parses and the timeout is converted to seconds."""
    calls: list[tuple[str, float, bool]] = []
    _install_get(
        monkeypatch,
        response=_FakeResponse(200, json.dumps(_valid_payload())),
        calls=calls,
    )

    manifest = fetch_static_release_manifest(
        "https://cdn.example.test/manifest.json", 2500
    )

    assert isinstance(manifest, StaticReleaseManifest)
    assert manifest.version == "1.2.3"
    assert manifest.platforms["darwin-arm64"].sha256 == VALID_SHA256
    assert calls == [("https://cdn.example.test/manifest.json", 2.5, True)]


def test_fetch_manifest_ignores_unknown_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown manifest fields stay forward compatible instead of failing closed."""
    payload: dict[str, object] = {
        "version": "1.2.3",
        "generatedAt": "2026-01-01T00:00:00Z",
        "platforms": {
            "darwin-arm64": {
                "url": "https://cdn.example.test/devin.tar.gz",
                "sha256": VALID_SHA256,
                "notes": "added upstream after this client shipped",
            }
        },
    }
    _install_get(monkeypatch, response=_FakeResponse(200, json.dumps(payload)))

    manifest = fetch_static_release_manifest(
        "https://cdn.example.test/manifest.json", 1000
    )

    assert manifest.version == "1.2.3"


@pytest.mark.parametrize("status_code", [301, 404, 500, 503])
def test_fetch_manifest_rejects_non_200_status(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    """A non-200 response must fail with the observed status, never parse the body."""
    _install_get(monkeypatch, response=_FakeResponse(status_code, "not found"))

    with pytest.raises(RuntimeError, match=f"HTTP {status_code}"):
        _ = fetch_static_release_manifest(
            "https://cdn.example.test/manifest.json", 1000
        )


def test_fetch_manifest_rejects_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-JSON body must fail as a parse error, not a validation error."""
    _install_get(monkeypatch, response=_FakeResponse(200, "{not json"))

    with pytest.raises(RuntimeError, match="parse failed"):
        _ = fetch_static_release_manifest(
            "https://cdn.example.test/manifest.json", 1000
        )


def test_fetch_manifest_rejects_short_checksum(monkeypatch: pytest.MonkeyPatch) -> None:
    """A checksum that is not 64 lowercase hex characters must be rejected."""
    payload: dict[str, object] = {
        "version": "1.2.3",
        "platforms": {
            "darwin-arm64": {
                "url": "https://cdn.example.test/devin.tar.gz",
                "sha256": "deadbeef",
            }
        },
    }
    _install_get(monkeypatch, response=_FakeResponse(200, json.dumps(payload)))

    with pytest.raises(RuntimeError, match="invalid release manifest"):
        _ = fetch_static_release_manifest(
            "https://cdn.example.test/manifest.json", 1000
        )


def test_fetch_manifest_rejects_unsafe_version_component(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A version with path separators must be rejected before it reaches a path."""
    payload: dict[str, object] = {
        "version": "1.2.3/../../escape",
        "platforms": {},
    }
    _install_get(monkeypatch, response=_FakeResponse(200, json.dumps(payload)))

    with pytest.raises(RuntimeError, match="invalid release manifest"):
        _ = fetch_static_release_manifest(
            "https://cdn.example.test/manifest.json", 1000
        )


def test_fetch_manifest_wraps_transport_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport failure surfaces as a RuntimeError with fetch context."""
    _install_get(monkeypatch, error=httpx.ConnectError("connection refused"))

    with pytest.raises(RuntimeError, match="release manifest fetch failed"):
        _ = fetch_static_release_manifest(
            "https://cdn.example.test/manifest.json", 1000
        )


def test_fetch_manifest_wraps_os_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """An OS-level failure (for example DNS) is wrapped the same way."""
    _install_get(monkeypatch, error=OSError("temporary failure in name resolution"))

    with pytest.raises(RuntimeError, match="release manifest fetch failed"):
        _ = fetch_static_release_manifest(
            "https://cdn.example.test/manifest.json", 1000
        )
