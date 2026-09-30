# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""HTTP GET with labelled RuntimeError failures for release downloads."""

from __future__ import annotations

import httpx

from sync.runtime.errors import panic_message

__all__ = ["get_ok"]

_HTTP_OK = 200
_MS_PER_SECOND = 1000.0


def get_ok(url: str, timeout_ms: int, label: str) -> httpx.Response:
    """GET `url` following redirects; raise RuntimeError prefixed by `label`.

    Transport errors and any status other than 200 are failures.
    """
    try:
        response = httpx.get(
            url, timeout=timeout_ms / _MS_PER_SECOND, follow_redirects=True
        )
    except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
        message = f"{label} ({panic_message(exc)})"
        raise RuntimeError(message) from exc
    if response.status_code != _HTTP_OK:
        message = f"{label} with HTTP {response.status_code}"
        raise RuntimeError(message)
    return response
