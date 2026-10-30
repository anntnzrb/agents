"""Contracts for free API pagination and evaluation cost."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from artificial_analysis import rsc
from artificial_analysis.contracts import as_dict, as_list, parse_json


def test_free_api_collects_pages_and_preserves_nulls() -> None:
    def page(
        _key: str, *, timeout_seconds: float, url: str | None = None, **_kwargs: object
    ) -> rsc.FetchResult:
        _ = timeout_seconds
        number = 2 if url and "page=2" in url else 1
        body = json.dumps(
            {
                "tier": "free",
                "intelligence_index_version": 5,
                "pagination": {
                    "page": number,
                    "page_size": 200,
                    "total_pages": 2,
                    "has_more": number == 1,
                },
                "data": [
                    {
                        "slug": f"m{number}",
                        "name": f"M{number}",
                        "model_creator": {},
                        "pricing": {"price_1m_input_tokens": 1},
                        "performance": {"median_output_tokens_per_second": 2},
                        "evaluations": {"artificial_analysis_intelligence_index": None},
                    }
                ],
            }
        )
        return rsc.FetchResult(body, 200, {}, "2026-01-01T00:00:00+00:00")

    with patch.object(rsc, "fetch_models", side_effect=page):
        result = rsc.fetch_all_models("key")
    payload = as_dict(parse_json(result.body))
    assert payload["intelligence_index_version"] == 5
    models = rsc.normalize_official_models(result.body)
    assert [model["slug"] for model in models] == ["m1", "m2"]
    assert as_dict(models[0]["evaluations"])["intelligence_index"] is None
    assert models[0]["median_output_tokens_per_second"] == 2


def test_provider_manifest_decodes_complete_endpoint_population() -> None:
    import gzip
    import hashlib

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = bytes(range(32))
    rows = [{"host": {"slug": "host"}, "model": {"slug": "model"}}]
    raw = AESGCM(key).encrypt(
        hashlib.sha256(key).digest()[:12],
        gzip.compress(json.dumps(rows).encode()),
        None,
    )
    assert rsc.decode_provider_manifest(raw, key.hex()) == rows


        {
            "tier": "free",
            "intelligence_index_version": 5,
            "pagination": {"page": 1, "total_pages": 1, "has_more": True},
            "data": [],
        }
    )
    with (
        patch.object(
            rsc,
            "fetch_models",
            return_value=rsc.FetchResult(bad, 200, {}, "2026-01-01"),
        ),
        pytest.raises(rsc.ExtractionError, match="pagination"),
    ):
        _ = rsc.fetch_all_models("key")
