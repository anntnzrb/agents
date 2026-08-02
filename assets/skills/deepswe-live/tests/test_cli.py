"""CLI envelope tests use injected fixture payloads and never access the network."""
# ruff: noqa: CPY001, E501, INP001, S101

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    from pathlib import Path

import _path  # noqa: F401
import pytest
from deepswe import cli

EXPECTED_CHANGE_COUNT = 2
USAGE_EXIT_STATUS = 2
VALID_COST_PER_ATTEMPT = 0.5

LEADERBOARD = {
    "generated_at": "2026-07-25T03:13:49Z",
    "rows": [
        {
            "model": "fixture-model",
            "harness": "fixture-harness",
            "reasoning_effort": "high",
            "config": "fixture-config",
            "source": "deep-swe",
            "pass_at_1": 0.5,
            "n_attempted": 2,
            "n_tasks_attempted": 2,
            "ci_lo": 0.25,
            "ci_hi": 0.75,
            "ci_half": 0.25,
            "mean_output_tokens": 100,
            "mean_cost_usd": 1.0,
            "mean_agent_steps": 3,
        }
    ],
}
TRIALS = {
    "n_trials": 2,
    "rows": [
        {
            "id": "included",
            "source": "deep-swe",
            "eval_scope": "full",
            "included_in_score": True,
        },
        {
            "id": "excluded",
            "source": "other",
            "eval_scope": "smoke",
            "included_in_score": False,
        },
    ],
}


def source_fixture(
    *, leaderboard_stats: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build a deterministic fetch envelope for CLI command tests."""
    metadata = {
        "benchmark": "DeepSWE",
        "benchmark_version": "v1.1",
        "fetched_at": "2026-07-25T04:00:00Z",
        "url": "fixture://deepswe/v1.1",
        "etag": '"fixture"',
        "last_modified": "fixture-date",
    }
    leaderboard = dict(LEADERBOARD)
    if leaderboard_stats is not None:
        leaderboard["stats"] = leaderboard_stats
    return {
        "benchmark": "DeepSWE",
        "benchmark_version": "v1.1",
        "artifacts": {
            "leaderboard-live.json": {
                **metadata,
                "artifact": "leaderboard-live.json",
                "data": leaderboard,
            },
            "trials.json": {**metadata, "artifact": "trials.json", "data": TRIALS},
        },
        "payloads": {"leaderboard-live.json": leaderboard, "trials.json": TRIALS},
        "provenance": {
            "url": "fixture://deepswe/v1.1",
            "fetched_at": "2026-07-25T04:00:00Z",
        },
    }


def invoke(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], source: object = None
) -> tuple[int, dict[str, Any], str]:
    """Invoke the CLI with captured output and an optional source fixture."""
    if source is not None:
        monkeypatch.setattr(cli, "fetch_artifacts", lambda *_args, **_kwargs: source)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli.main(argv, stdout=stdout, stderr=stderr)
    lines = stdout.getvalue().splitlines()
    assert len(lines) == 1, stdout.getvalue()
    envelope = json.loads(lines[0])
    assert isinstance(envelope, dict)
    return code, envelope, stderr.getvalue()


def test_report_success_is_one_json_envelope_with_scope_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure report output is one scoped JSON envelope."""
    code, envelope, diagnostics = invoke(
        monkeypatch, ["report", "--version", "v1.1"], source_fixture()
    )
    assert code == 0
    assert diagnostics == ""
    assert envelope["ok"] is True
    assert envelope["schema_version"] == 1
    assert envelope["command"] == "report"
    scope = envelope["data"]["scope"]
    assert scope["benchmark"] == "DeepSWE"
    assert scope["benchmark_version"] == "v1.1"
    assert scope["value_status"] == "derived"
    assert scope["filters_applied"]["quality_exclusion"] == "none"
    provenance = envelope["data"]["provenance"]
    assert provenance["url"] == "fixture://deepswe/v1.1"
    assert provenance["fetched_at"] == "2026-07-25T04:00:00Z"


def test_report_supports_custom_pareto_axes_and_efficiency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure CLI reports honor custom Pareto axes and efficiency specs."""
    code, envelope, diagnostics = invoke(
        monkeypatch,
        [
            "report",
            "--version",
            "v1.1",
            "--pareto-axis",
            "pass_at_1:max",
            "--pareto-axis",
            "mean_cost_usd:min",
            "--efficiency",
            "cost_per_attempt=mean_cost_usd/n_attempted",
        ],
        source_fixture(),
    )
    assert code == 0
    assert diagnostics == ""
    data = envelope["data"]
    assert data["pareto_axes"] == [
        {"metric": "pass_at_1", "order": "desc"},
        {"metric": "mean_cost_usd", "order": "asc"},
    ]
    assert (
        data["efficiency"]["rows"][0]["derived"]["efficiency"]["cost_per_attempt"][
            "value"
        ]
        == VALID_COST_PER_ATTEMPT
    )


def test_stats_prefers_artifact_provenance_over_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure artifact-specific provenance overrides wrapper metadata."""
    source = source_fixture()
    wrapper_provenance = {
        "url": "fixture://wrapper/deepswe/v1.1",
        "fetched_at": "2026-07-25T05:00:00Z",
    }
    source.update(wrapper_provenance)
    source["provenance"] = dict(wrapper_provenance)
    source["artifacts"]["leaderboard-live.json"].update(
        {
            "url": "fixture://artifact/deepswe/v1.1/leaderboard-live.json",
            "fetched_at": "2026-07-25T06:00:00Z",
        }
    )

    code, envelope, diagnostics = invoke(
        monkeypatch, ["stats", "--version", "v1.1"], source
    )

    assert code == 0
    assert diagnostics == ""
    provenance = envelope["data"]["provenance"]
    assert provenance["url"] == "fixture://artifact/deepswe/v1.1/leaderboard-live.json"
    assert provenance["fetched_at"] == "2026-07-25T06:00:00Z"


def test_trials_success_exposes_default_filter_and_raw_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure trials output exposes its default raw-data filter."""
    code, envelope, diagnostics = invoke(
        monkeypatch, ["trials", "--version", "v1.1"], source_fixture()
    )
    assert code == 0
    assert diagnostics == ""
    assert envelope["ok"] is True
    assert envelope["data"]["scope"]["value_status"] == "published_raw"
    filters = envelope["data"]["scope"]["filters_applied"]
    assert filters["source"] == "deep-swe"
    assert filters["eval_scope"] == "full"
    assert filters["included_in_score"] is True
    assert envelope["data"]["rows"] == [TRIALS["rows"][0]]


def test_stats_over_published_leaderboard_rows_is_derived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure derived stats are marked separately from published rows."""
    code, envelope, diagnostics = invoke(
        monkeypatch, ["stats", "--version", "v1.1"], source_fixture()
    )
    assert code == 0
    assert diagnostics == ""
    assert envelope["ok"] is True
    assert envelope["data"]["scope"]["value_status"] == "derived"
    assert envelope["data"]["row_count"] == len(LEADERBOARD["rows"])


def test_stats_copies_published_leaderboard_stats_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure published stats mappings are returned without recomputation."""
    published_stats = {
        "row_count": 99,
        "fields": ["published_metric"],
        "missing": {"published_metric": 0},
        "numeric_ranges": {"published_metric": {"min": 1, "max": 1}},
    }
    code, envelope, diagnostics = invoke(
        monkeypatch,
        ["stats", "--version", "v1.1"],
        source_fixture(leaderboard_stats=published_stats),
    )
    assert code == 0
    assert diagnostics == ""
    assert envelope["ok"] is True
    assert envelope["data"]["scope"]["value_status"] == "published"
    assert envelope["data"]["row_count"] == published_stats["row_count"]
    assert envelope["data"]["fields"] == published_stats["fields"]


def test_rank_accepts_zero_limit_with_empty_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure a zero rank limit yields an empty successful result."""
    code, envelope, diagnostics = invoke(
        monkeypatch,
        ["rank", "--version", "v1.1", "--limit", "0"],
        source_fixture(),
    )
    assert code == 0
    assert diagnostics == ""
    assert envelope["ok"] is True
    assert envelope["schema_version"] == 1
    assert envelope["command"] == "rank"
    assert envelope["data"]["rows"] == []
    assert envelope["data"]["count"] == 0
    assert envelope["data"]["filters_applied"]["limit"] == 0


def test_unversioned_snapshot_is_rejected_without_version_proof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject snapshots lacking payload or path version evidence."""
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps({"benchmark": "DeepSWE", "rows": [{"model": "fixture-model"}]}),
        encoding="utf-8",
    )

    code, envelope, diagnostics = invoke(
        monkeypatch, ["report", "--snapshot", str(snapshot)]
    )

    assert code == 1
    assert envelope == {
        "ok": False,
        "schema_version": 1,
        "command": "report",
        "error": {
            "code": "version",
            "message": "snapshot must declare benchmark_version in payload metadata or include a concrete version component in its path",
        },
    }
    assert "benchmark_version" in diagnostics


def test_compare_keeps_delimiter_colliding_configuration_identities(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ensure structured identities do not collide on delimiters."""
    left_rows = [
        {
            "model": "model|high",
            "reasoning_effort": "runner",
            "harness": "config",
            "config": None,
            "pass_at_1": 1,
        },
        {
            "model": "model",
            "reasoning_effort": "high",
            "harness": "runner|config",
            "config": "",
            "pass_at_1": 2,
        },
    ]
    right_rows = [
        {**left_rows[0], "pass_at_1": 3},
        {**left_rows[1], "pass_at_1": 6},
    ]
    left_path = tmp_path / "left.json"
    right_path = tmp_path / "right.json"
    left_path.write_text(
        json.dumps(
            {"benchmark": "DeepSWE", "benchmark_version": "v1.1", "rows": left_rows}
        ),
        encoding="utf-8",
    )
    right_path.write_text(
        json.dumps(
            {"benchmark": "DeepSWE", "benchmark_version": "v1.1", "rows": right_rows}
        ),
        encoding="utf-8",
    )

    code, envelope, diagnostics = invoke(
        monkeypatch,
        ["compare", str(left_path), str(right_path), "--version", "v1.1"],
    )

    assert code == 0
    assert diagnostics == ""
    assert envelope["ok"] is True
    changes = envelope["data"]["changes"]
    assert len(changes) == EXPECTED_CHANGE_COUNT
    assert [change["config"] for change in changes] == [
        '["model","high","runner|config",""]',
        '["model|high","runner","config",null]',
    ]
    assert [
        (change["before"], change["after"], change["delta"]) for change in changes
    ] == [
        (2, 6, 4),
        (1, 3, 2),
    ]


def test_compare_uses_version_from_snapshot_path_when_payload_unversioned(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Use a concrete release component from snapshot paths."""
    versioned_path = tmp_path / "v1.1"
    versioned_path.mkdir()
    payload = {
        "benchmark": "DeepSWE",
        "rows": [{"model": "fixture-model", "pass_at_1": 1}],
    }
    left_path = versioned_path / "left.json"
    right_path = versioned_path / "right.json"
    left_path.write_text(json.dumps(payload), encoding="utf-8")
    right_path.write_text(
        json.dumps({**payload, "rows": [{"model": "fixture-model", "pass_at_1": 2}]}),
        encoding="utf-8",
    )

    code, envelope, diagnostics = invoke(
        monkeypatch, ["compare", str(left_path), str(right_path)]
    )

    assert code == 0
    assert diagnostics == ""
    assert envelope["ok"] is True
    assert envelope["data"]["scope"]["benchmark_version"] == "v1.1"
    assert envelope["data"]["changes"][0]["delta"] == 1


def test_error_is_json_only_on_stdout_and_diagnostics_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep machine-readable errors on stdout and diagnostics on stderr."""

    def fail_fetch(*_args: object, **_kwargs: object) -> NoReturn:
        code = "network"
        message = "network fixture offline"
        raise cli.CliError(code, message)

    monkeypatch.setattr(cli, "fetch_artifacts", fail_fetch)
    code, envelope, diagnostics = invoke(monkeypatch, ["fetch", "--version", "v1.1"])
    assert code == 1
    assert envelope == {
        "ok": False,
        "schema_version": 1,
        "command": "fetch",
        "error": {"code": "network", "message": "network fixture offline"},
    }
    assert "network fixture offline" in diagnostics


def test_usage_failure_still_uses_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Render missing commands as a usage error envelope."""
    code, envelope, diagnostics = invoke(monkeypatch, [])
    assert code == USAGE_EXIT_STATUS
    assert envelope["ok"] is False
    assert envelope["schema_version"] == 1
    assert envelope["command"] == "unknown"
    assert envelope["error"]["code"] == "usage"
    assert diagnostics


def test_schema_is_json_only_and_declares_future_additive_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose the additive command and envelope schema as JSON."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(cli, "_now", lambda: "2026-07-25T05:00:00+00:00")
    code = cli.main(["schema", "--version", "v1.1"], stdout=stdout, stderr=stderr)
    envelope = json.loads(stdout.getvalue())
    assert code == 0
    assert stderr.getvalue() == ""
    assert envelope["ok"] is True
    schema = envelope["data"]["schema"]
    assert schema["commands"] == [
        "fetch",
        "report",
        "rank",
        "trials",
        "stats",
        "schema",
        "compare",
    ]
    assert schema["scope"]["value_status"] == ["published", "published_raw", "derived"]
    assert envelope["data"]["scope"]["benchmark_version"] == "v1.1"


if __name__ == "__main__":
    pytest.main([__file__])
