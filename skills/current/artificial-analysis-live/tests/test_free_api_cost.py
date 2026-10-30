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


def test_cost_prices_cache_and_marks_assumptions() -> None:
    from artificial_analysis.eval_cost import derive_eval_cost

    rows: list[dict[str, object]] = [
        {
            "slug": "model",
            "name": "Model (high)",
            "frontierCode20": 0.5,
            "canonicalEvalTokenCounts": {
                "frontierCode20": {
                    "input": 1000000,
                    "answer": 100000,
                    "reasoning": 100000,
                    "cacheableInput": 800000,
                }
            },
            "price1mInputTokens": 2,
            "price1mOutputTokens": 10,
        }
    ]
    priced = derive_eval_cost(
        rows,
        "frontierCode20",
        396,
        {"model": {"price_1m_cache_hit_tokens": 0.5}},
        source_url="https://example.test/evaluation",
        manifest_hash="abc",
    )
    assert priced[0]["total_cost_usd"] == 2.8
    assert priced[0]["cost_per_task_usd"] == pytest.approx(2.8 / 396)
    assert priced[0]["value_status"] == "derived"
    assert priced[0]["manifest_hash"] == "abc"
    assert priced[0]["cache_pricing"] == "cache_hit_assumed"
    rows[0]["cacheHitPrice"] = 0.25
    manifest_priced = derive_eval_cost(
        rows,
        "frontierCode20",
        396,
        {"model": {"price_1m_cache_hit_tokens": 0.5}},
        source_url="https://example.test/evaluation",
        manifest_hash="abc",
    )
    assert manifest_priced[0]["total_cost_usd"] == 2.6
    assert (
        as_dict(manifest_priced[0]["pricing_source"])["cache_hit"]
        == "evaluation_manifest"
    )


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


def test_eval_cost_cli_replays_page_and_joins_snapshot(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    _ = snapshot.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "model-high",
                        "pricing": {"price_1m_cache_hit_tokens": 0.5},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    fixture = Path(__file__).parent / "fixtures" / "eval-cost" / "frontier.rsc"
    cli = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"
    env = {name: os.environ[name] for name in ("PATH", "HOME") if name in os.environ}
    completed = subprocess.run(
        [
            sys.executable,
            str(cli),
            "eval-cost",
            "--input",
            str(fixture),
            "--metric",
            "frontierCode20",
            "--attempts",
            "396",
            "--snapshot",
            str(snapshot),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=True,
    )
    data = as_dict(as_dict(parse_json(completed.stdout))["data"])
    rows = [as_dict(row) for row in as_list(data["rows"])]
    assert [row["slug"] for row in rows] == ["model-high", "model-low"]
    assert rows[0]["total_cost_usd"] == 2.8
    assert rows[1]["total_cost_usd"] is None
    assert rows[0]["pricing_snapshot_hash"]
    assert rows[0]["source_url"] == fixture.resolve().as_uri()
    assert rows[1]["cache_pricing"] == "input_rate_fallback"


def test_free_api_rejects_inconsistent_pagination() -> None:
    bad = json.dumps(
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
