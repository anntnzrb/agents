# Copyright (c) 2026
from __future__ import annotations

from pathlib import Path

import pytest
from fakes.transport import QueueOpener, Response
from livebench.cache import CacheStore
from livebench.contracts import SourceTarget
from livebench.transport import FetchError, fetch_target


def test_200_then_304_reuses_exact_cache(tmp_path: Path) -> None:
    target = SourceTarget(
        "fixture-release",
        "score_table",
        "https://livebench.ai/table_fixture.csv",
        "https://livebench.ai/",
    )
    opener = QueueOpener(
        Response(
            b"model,task\nmodel-a,72.4\n",
            headers={"ETag": '"e1"', "Last-Modified": "Sun, 09 Aug 2026 00:00:00 GMT"},
            final_url=target.url,
        ),
        Response(b"", status=304, headers={"ETag": '"e1"'}, final_url=target.url),
    )
    first = fetch_target(target, CacheStore(tmp_path), opener=opener)
    second = fetch_target(target, CacheStore(tmp_path), opener=opener)
    assert first.body == second.body
    assert second.cache_reused
    assert opener.requests[1].headers["If-none-match"] == '"e1"'
    assert (
        opener.requests[1].headers["If-modified-since"]
        == "Sun, 09 Aug 2026 00:00:00 GMT"
    )


def test_404_does_not_fallback(tmp_path: Path) -> None:
    target = SourceTarget(
        "missing",
        "score_table",
        "https://livebench.ai/missing.csv",
        "https://livebench.ai/",
    )
    with pytest.raises(FetchError, match="HTTP 404"):
        fetch_target(
            target,
            CacheStore(tmp_path),
            opener=QueueOpener(Response(b"", status=404, final_url=target.url)),
        )
