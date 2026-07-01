from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest
from pathlib import Path

import _path  # noqa: F401
from artificial_analysis import cli


TMP_ARTIFACT_DIR = Path("/tmp/artifacts/artificial-analysis")
TMP_SNAPSHOT = TMP_ARTIFACT_DIR / "full-data.json"
TMP_ENDPOINTS = TMP_ARTIFACT_DIR / "endpoints.txt"
TMP_URL = TMP_ARTIFACT_DIR / "full-url.txt"
TMP_CODING = TMP_ARTIFACT_DIR / "coding-data.json"


class TestCliDefaultPaths(unittest.TestCase):
    def test_fetch_parser_uses_tmp_artifacts_defaults(self) -> None:
        args = cli.build_parser().parse_args(["fetch"])

        self.assertEqual(args.output_json, TMP_SNAPSHOT)
        self.assertEqual(args.output_endpoints, TMP_ENDPOINTS)
        self.assertEqual(args.output_url, TMP_URL)

    def test_reader_commands_default_to_tmp_snapshot(self) -> None:
        parser = cli.build_parser()
        for command in (["stats"], ["harness"], ["reasoning"], ["query"]):
            with self.subTest(command=command[0]):
                args = parser.parse_args(command)
                self.assertEqual(args.snapshot, TMP_SNAPSHOT)

        args = parser.parse_args(["qa", "best provider"])
        self.assertEqual(args.snapshot, TMP_SNAPSHOT)

    def test_coding_parser_uses_tmp_output_default(self) -> None:
        args = cli.build_parser().parse_args(["coding"])

        self.assertEqual(args.output_json, TMP_CODING)

    def test_rpc_namespace_defaults_use_tmp_artifacts(self) -> None:
        fetch_args = cli._fetch_namespace({})

        self.assertEqual(fetch_args.output_json, TMP_SNAPSHOT)
        self.assertEqual(fetch_args.output_endpoints, TMP_ENDPOINTS)
        self.assertEqual(fetch_args.output_url, TMP_URL)
        self.assertEqual(cli._stats_namespace({}).snapshot, TMP_SNAPSHOT)
        self.assertEqual(cli._coding_namespace({}).output_json, TMP_CODING)

    def test_capability_schema_reports_tmp_fetch_defaults(self) -> None:
        schema = cli._capability_schema()
        flags = schema["commands"]["fetch"]["flags"]

        self.assertEqual(
            flags["output_json"],
            "Path (default /tmp/artifacts/artificial-analysis/full-data.json)",
        )
        self.assertEqual(
            flags["output_endpoints"],
            "Path (default /tmp/artifacts/artificial-analysis/endpoints.txt)",
        )
        self.assertEqual(
            flags["output_url"],
            "Path (default /tmp/artifacts/artificial-analysis/full-url.txt)",
        )

    def test_default_snapshot_guard_rejects_stale_tmp_snapshot(self) -> None:
        stale_snapshot = {
            "meta": {
                "fetched_at": (datetime.now(UTC) - timedelta(days=2)).isoformat()
            }
        }

        with self.assertRaisesRegex(cli.ExtractionError, "Default snapshot is stale"):
            cli._ensure_default_snapshot_fresh(TMP_SNAPSHOT, stale_snapshot)

    def test_default_snapshot_guard_allows_explicit_stale_snapshot(self) -> None:
        stale_snapshot = {"meta": {"fetched_at": "2000-01-01T00:00:00+00:00"}}

        cli._ensure_default_snapshot_fresh(Path("fixtures/old-snapshot.json"), stale_snapshot)


if __name__ == "__main__":
    unittest.main()
