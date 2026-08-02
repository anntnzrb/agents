"""CLI default-path regression tests."""

# ruff: noqa: CPY001, D101, D102, E501, INP001, PLR2004, S101, SLF001
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import _path  # noqa: F401
import pytest
from artificial_analysis import cli

TMP_ARTIFACT_DIR = Path(tempfile.gettempdir()) / "artifacts" / "artificial-analysis"
TMP_SNAPSHOT = TMP_ARTIFACT_DIR / "full-data.json"
TMP_ENDPOINTS = TMP_ARTIFACT_DIR / "endpoints.txt"
TMP_URL = TMP_ARTIFACT_DIR / "full-url.txt"
TMP_CODING = TMP_ARTIFACT_DIR / "coding-data.json"


class TestCliDefaultPaths(unittest.TestCase):
    def test_fetch_parser_uses_tmp_artifacts_defaults(self) -> None:
        args = cli.build_parser().parse_args(["fetch"])

        assert args.output_json == TMP_SNAPSHOT
        assert args.output_endpoints == TMP_ENDPOINTS
        assert args.output_url == TMP_URL

    def test_reader_commands_default_to_tmp_snapshot(self) -> None:
        parser = cli.build_parser()
        for command in (["stats"], ["harness"], ["reasoning"], ["query"]):
            with self.subTest(command=command[0]):
                args = parser.parse_args(command)
                assert args.snapshot == TMP_SNAPSHOT

        args = parser.parse_args(["qa", "best provider"])
        assert args.snapshot == TMP_SNAPSHOT

    def test_coding_parser_uses_tmp_output_default(self) -> None:
        args = cli.build_parser().parse_args(["coding"])

        assert args.output_json == TMP_CODING

    def test_evaluation_parser_accepts_url_and_generic_controls(self) -> None:
        args = cli.build_parser().parse_args(
            [
                "evaluation",
                "https://example.test/evaluations/demo",
                "--sort-by",
                "score",
                "--order",
                "desc",
                "--limit",
                "3",
            ],
        )
        assert args.url == "https://example.test/evaluations/demo"
        assert args.sort_by == "score"
        assert args.order == "desc"
        assert args.limit == 3

    def test_rpc_namespace_defaults_use_tmp_artifacts(self) -> None:
        fetch_args = cli._fetch_namespace({})

        assert fetch_args.output_json == TMP_SNAPSHOT
        assert fetch_args.output_endpoints == TMP_ENDPOINTS
        assert fetch_args.output_url == TMP_URL
        assert cli._stats_namespace({}).snapshot == TMP_SNAPSHOT
        assert cli._coding_namespace({}).output_json == TMP_CODING

    def test_capability_schema_reports_tmp_fetch_defaults(self) -> None:
        schema = cli._capability_schema()
        flags = schema["commands"]["fetch"]["flags"]

        assert (
            flags["output_json"]
            == "Path (default <temp-dir>/artifacts/artificial-analysis/full-data.json)"
        )
        assert (
            flags["output_endpoints"]
            == "Path (default <temp-dir>/artifacts/artificial-analysis/endpoints.txt)"
        )
        assert (
            flags["output_url"]
            == "Path (default <temp-dir>/artifacts/artificial-analysis/full-url.txt)"
        )

    def test_default_snapshot_guard_rejects_stale_tmp_snapshot(self) -> None:
        stale_snapshot = {
            "meta": {"fetched_at": (datetime.now(UTC) - timedelta(days=2)).isoformat()},
        }

        with pytest.raises(cli.ExtractionError, match="Default snapshot is stale"):
            cli._ensure_default_snapshot_fresh(TMP_SNAPSHOT, stale_snapshot)

    def test_default_snapshot_guard_allows_explicit_stale_snapshot(self) -> None:
        stale_snapshot = {"meta": {"fetched_at": "2000-01-01T00:00:00+00:00"}}

        cli._ensure_default_snapshot_fresh(
            Path("fixtures/old-snapshot.json"),
            stale_snapshot,
        )

    def test_fetch_requires_exact_key_error_before_network(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(cli, "_dotenv_candidates", return_value=[]),
            pytest.raises(
                cli.CliUsageError,
                match=r"^ARTIFICIAL_ANALYSIS_API_KEY required; copy \.env\.example to \.env and set the key\.$",
            ),
        ):
            cli._required_api_key()

    def test_dotenv_preserves_existing_process_variables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "ARTIFICIAL_ANALYSIS_API_KEY=file-key\nUNRELATED=file-value\n",
                encoding="utf-8",
            )
            with (
                patch.dict(
                    os.environ,
                    {
                        "ARTIFICIAL_ANALYSIS_API_KEY": "process-key",
                        "UNRELATED": "process-value",
                    },
                    clear=True,
                ),
                patch.object(cli, "_dotenv_candidates", return_value=[env_file]),
            ):
                cli._load_dotenv()
                assert os.environ["ARTIFICIAL_ANALYSIS_API_KEY"] == "process-key"
                assert os.environ["UNRELATED"] == "process-value"

    def test_schema_v2_readers_join_slim_endpoints_to_canonical_models(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir) / "snapshot.json"
            snapshot_path.write_text(
                '{"meta":{"schema_version":2,"fetched_at":"2026-01-01T00:00:00+00:00"},"models":[{"slug":"model-a","name":"Model A","creator":{"name":"Lab"},"agentic_index":80,"coding_index":60,"intelligence_index":70}],"hosts_models":[{"slug":"host_model-a","model_slug":"model-a","host":{"slug":"host","name":"Host"},"timescaleData":{"median_output_speed":10},"price_1m_blended_7_to_2_to_1":4}]}',
                encoding="utf-8",
            )
            query = cli._query_payload(
                SimpleNamespace(
                    snapshot=snapshot_path,
                    model=None,
                    provider=None,
                    endpoint=None,
                    sort_by="intelligence",
                    order="auto",
                    limit=10,
                ),
            )
            harness = cli._harness_payload(
                SimpleNamespace(
                    snapshot=snapshot_path,
                    model=None,
                    creator=None,
                    open_weights_only=False,
                    limit=10,
                ),
            )
        assert query["rows"][0]["model_name"] == "Model A"
        assert query["rows"][0]["price_blended"] == 4
        assert harness["rows"][0]["creator"] == "Lab"

    def test_fetch_uses_last_good_snapshot_when_required_source_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "cache"
            cache_dir.mkdir()
            (cache_dir / "last-good.json").write_text(
                '{"meta":{"fetched_at":"2026-01-01T00:00:00+00:00"},"models":[],"hosts":[],"hosts_models":[{"slug":"host_model-1"}]}',
                encoding="utf-8",
            )
            args = SimpleNamespace(
                cache_dir=cache_dir,
                timeout_seconds=1.0,
                min_endpoints=0,
                min_providers=0,
                strict=False,
                output_json=Path(temp_dir) / "snapshot.json",
                output_endpoints=Path(temp_dir) / "endpoints.txt",
                output_url=Path(temp_dir) / "url.txt",
            )
            with (
                patch.object(cli, "_required_api_key", return_value="secret"),
                patch.object(cli, "fetch_rsc", side_effect=OSError("HTTP 503")),
            ):
                payload = cli._fetch_payload(args)
        assert payload["fallback"]["used"]
        assert payload["sources"]["rsc"]["status_code"] is None

    def test_fetch_falls_back_when_official_api_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "cache"
            cache_dir.mkdir()
            (cache_dir / "last-good.json").write_text(
                '{"meta":{"fetched_at":"2026-01-01T00:00:00+00:00"},"models":[],"hosts":[],"hosts_models":[{"slug":"host_model-1"}]}',
                encoding="utf-8",
            )
            args = SimpleNamespace(
                cache_dir=cache_dir,
                timeout_seconds=1.0,
                min_endpoints=0,
                min_providers=0,
                strict=False,
                output_json=Path(temp_dir) / "snapshot.json",
                output_endpoints=Path(temp_dir) / "endpoints.txt",
                output_url=Path(temp_dir) / "url.txt",
            )
            with (
                patch.object(cli, "_required_api_key", return_value="secret"),
                patch.object(
                    cli,
                    "fetch_rsc",
                    return_value=SimpleNamespace(status_code=200, headers={}, body=""),
                ),
                patch.object(cli, "fetch_models", side_effect=OSError("HTTP 503")),
            ):
                payload = cli._fetch_payload(args)
        assert payload["fallback"]["used"]
        assert payload["sources"]["official_api"]["status_code"] is None

    def test_evaluation_payload_reads_saved_next_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "evaluation.html"
            input_path.write_text(
                "<script>self.__next_f.push([1,"
                '"0:{\\"rows\\":[{\\"name\\":\\"A\\",\\"score\\":70},'
                '{\\"name\\":\\"B\\",\\"score\\":80}]}'
                '"])</script>',
                encoding="utf-8",
            )
            args = cli._evaluation_namespace(
                {"input": str(input_path), "sort_by": "score", "order": "desc"},
            )
            payload = cli._evaluation_payload(args)

        assert payload["counts"]["matched_rows"] == 2
        assert [row["name"] for row in payload["rows"]] == ["B", "A"]


if __name__ == "__main__":
    unittest.main()
