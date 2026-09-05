"""CLI envelope tests use injected fixture payloads and never access the network."""
# ruff: noqa: E501

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, NoReturn, cast

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

import pytest

from deepswe import cli

EXPECTED_CHANGE_COUNT = 2
USAGE_EXIT_STATUS = 2
VALID_COST_PER_ATTEMPT = 0.5
PUBLIC_COMMANDS = (
    "fetch",
    "report",
    "rank",
    "trials",
    "stats",
    "schema",
    "compare",
    "diagnose",
)
IDENTITY_FIELDS = ("model", "reasoning_effort", "harness", "config")

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
    *, leaderboard_stats: Mapping[str, object] | None = None
) -> dict[str, object]:
    """Build a deterministic fetch envelope for CLI command tests."""
    metadata = {
        "benchmark": "DeepSWE",
        "benchmark_version": "v1.1",
        "fetched_at": "2026-07-25T04:00:00Z",
        "url": "fixture://deepswe/v1.1",
        "etag": '"fixture"',
        "last_modified": "fixture-date",
    }
    leaderboard: dict[str, object] = dict(LEADERBOARD)
    if leaderboard_stats is not None:
        leaderboard["stats"] = dict(leaderboard_stats)
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
) -> tuple[int, dict[str, object], str]:
    """Invoke the CLI with captured output and an optional source fixture."""
    if source is not None:

        def _fetch(*_args: object, **_kwargs: object) -> object:
            return source

        monkeypatch.setattr(cli, "fetch_artifacts", _fetch)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli.main(argv, stdout=stdout, stderr=stderr)
    lines = stdout.getvalue().splitlines()
    assert len(lines) == 1, stdout.getvalue()
    envelope = cast("dict[str, object]", json.loads(lines[0]))
    assert isinstance(envelope, dict)
    return code, envelope, stderr.getvalue()


def test_public_commands_keep_v1_compact_success_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Freeze one compact integer-v1 success object for every public command."""
    snapshot_dir = tmp_path / "v1.1"
    snapshot_dir.mkdir()
    left_path = snapshot_dir / "left.json"
    right_path = snapshot_dir / "right.json"
    _ = left_path.write_text(
        json.dumps(
            {
                "benchmark": "DeepSWE",
                "benchmark_version": "v1.1",
                "rows": [{"model": "fixture-model", "pass_at_1": 1}],
            }
        ),
        encoding="utf-8",
    )
    _ = right_path.write_text(
        json.dumps(
            {
                "benchmark": "DeepSWE",
                "benchmark_version": "v1.1",
                "rows": [{"model": "fixture-model", "pass_at_1": 2}],
            }
        ),
        encoding="utf-8",
    )
    invocations: list[tuple[str, list[str], object]] = [
        ("fetch", ["fetch", "--version", "v1.1"], source_fixture()),
        ("report", ["report", "--version", "v1.1"], source_fixture()),
        ("rank", ["rank", "--version", "v1.1"], source_fixture()),
        ("trials", ["trials", "--version", "v1.1"], source_fixture()),
        ("stats", ["stats", "--version", "v1.1"], source_fixture()),
        ("schema", ["schema", "--version", "v1.1"], None),
        (
            "compare",
            [
                "compare",
                str(left_path),
                str(right_path),
                "--version",
                "v1.1",
            ],
            None,
        ),
    ]

    for command, argv, source in invocations:
        code, envelope, diagnostics = invoke(monkeypatch, argv, source)
        assert code == 0
        assert diagnostics == ""
        assert envelope["ok"] is True
        assert type(envelope["schema_version"]) is int
        assert envelope["schema_version"] == 1
        assert envelope["command"] == command
        assert set(envelope) == {"ok", "schema_version", "command", "data"}


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
    data = cast("dict[str, object]", envelope["data"])
    scope = cast("dict[str, object]", data["scope"])
    assert scope["benchmark"] == "DeepSWE"
    assert scope["benchmark_version"] == "v1.1"
    assert scope["value_status"] == "derived"
    scope_filters = cast("dict[str, object]", scope["filters_applied"])
    assert scope_filters["quality_exclusion"] == "none"
    provenance = cast("dict[str, object]", data["provenance"])
    assert provenance["url"] == "fixture://deepswe/v1.1"
    assert provenance["fetched_at"] == "2026-07-25T04:00:00Z"


def test_report_preserves_identity_tuple_and_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the published identity tuple and established report sections."""
    code, envelope, diagnostics = invoke(
        monkeypatch, ["report", "--version", "v1.1"], source_fixture()
    )
    assert code == 0
    assert diagnostics == ""
    data = cast("dict[str, object]", envelope["data"])
    assert {"recommendations", "raw_extrema", "pareto"} <= data.keys()
    recs = cast("dict[str, list[dict[str, object]]]", data["recommendations"])
    row = recs["rows"][0]
    assert tuple(row[field] for field in IDENTITY_FIELDS) == (
        "fixture-model",
        "high",
        "fixture-harness",
        "fixture-config",
    )
    row_derived = cast("dict[str, object]", row["derived"])
    assert row_derived["value_status"] == "derived"


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
    data = cast("dict[str, object]", envelope["data"])
    assert data["pareto_axes"] == [
        {"metric": "pass_at_1", "order": "desc"},
        {"metric": "mean_cost_usd", "order": "asc"},
    ]
    eff = cast("dict[str, list[dict[str, object]]]", data["efficiency"])
    eff_row0 = eff["rows"][0]
    eff_derived = cast("dict[str, dict[str, dict[str, object]]]", eff_row0["derived"])
    assert (
        eff_derived["efficiency"]["cost_per_attempt"]["value"] == VALID_COST_PER_ATTEMPT
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
    artifacts = cast("dict[str, dict[str, object]]", source["artifacts"])
    artifacts["leaderboard-live.json"].update(
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
    data = cast("dict[str, object]", envelope["data"])
    provenance = cast("dict[str, object]", data["provenance"])
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
    data = cast("dict[str, object]", envelope["data"])
    scope = cast("dict[str, object]", data["scope"])
    assert scope["value_status"] == "published_raw"
    filters = cast("dict[str, object]", scope["filters_applied"])
    assert filters["source"] == "deep-swe"
    assert filters["eval_scope"] == "full"
    assert filters["included_in_score"] is True
    trials_rows = cast("list[dict[str, object]]", TRIALS["rows"])
    assert data["rows"] == [trials_rows[0]]


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
    data = cast("dict[str, object]", envelope["data"])
    scope = cast("dict[str, object]", data["scope"])
    assert scope["value_status"] == "derived"
    assert data["row_count"] == len(LEADERBOARD["rows"])


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
    data = cast("dict[str, object]", envelope["data"])
    scope = cast("dict[str, object]", data["scope"])
    assert scope["value_status"] == "published"
    assert data["row_count"] == published_stats["row_count"]
    assert data["fields"] == published_stats["fields"]


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
    data = cast("dict[str, object]", envelope["data"])
    assert data["rows"] == []
    assert data["count"] == 0
    filters = cast("dict[str, object]", data["filters_applied"])
    assert filters["limit"] == 0


def test_allow_stale_is_forwarded_only_when_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep stale refresh opt-in at the public CLI boundary."""
    calls: list[dict[str, object]] = []

    def capture_fetch(*_args: object, **kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return source_fixture()

    monkeypatch.setattr(cli, "fetch_artifacts", capture_fetch)
    for flag, expected in (("--allow-stale", True), (None, False)):
        argv = ["fetch", "--version", "v1.1"]
        if flag is not None:
            argv.append(flag)
        code, envelope, diagnostics = invoke(monkeypatch, argv)
        assert code == 0
        assert diagnostics == ""
        assert envelope["ok"] is True
        assert calls[-1]["allow_stale"] is expected


def test_snapshot_is_explicit_and_historical_without_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Use a versioned snapshot only when explicitly selected."""
    snapshot_dir = tmp_path / "v1.1"
    snapshot_dir.mkdir()
    snapshot = snapshot_dir / "leaderboard.json"
    _ = snapshot.write_text(
        json.dumps(
            {
                "benchmark": "DeepSWE",
                "benchmark_version": "v1.1",
                "rows": [
                    {
                        "model": "fixture-model",
                        "reasoning_effort": "high",
                        "harness": "fixture-harness",
                        "config": "fixture-config",
                        "pass_at_1": 0.5,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def fail_fetch(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "snapshot mode must not fetch"
        raise AssertionError(msg)

    monkeypatch.setattr(cli, "fetch_artifacts", fail_fetch)
    code, envelope, diagnostics = invoke(
        monkeypatch, ["report", "--snapshot", str(snapshot)]
    )
    assert code == 0
    assert diagnostics == ""
    assert envelope["ok"] is True
    data = cast("dict[str, object]", envelope["data"])
    scope = cast("dict[str, object]", data["scope"])
    assert scope["benchmark_version"] == "v1.1"
    provenance = cast("dict[str, object]", data["provenance"])
    assert provenance["freshness"] == "snapshot"
    assert provenance["snapshot"] is True


def test_unversioned_snapshot_is_rejected_without_version_proof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject snapshots lacking payload or path version evidence."""
    snapshot = tmp_path / "snapshot.json"
    _ = snapshot.write_text(
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
    _ = left_path.write_text(
        json.dumps(
            {"benchmark": "DeepSWE", "benchmark_version": "v1.1", "rows": left_rows}
        ),
        encoding="utf-8",
    )
    _ = right_path.write_text(
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
    data = cast("dict[str, object]", envelope["data"])
    changes = cast("list[dict[str, object]]", data["changes"])
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
    _ = left_path.write_text(json.dumps(payload), encoding="utf-8")
    _ = right_path.write_text(
        json.dumps({**payload, "rows": [{"model": "fixture-model", "pass_at_1": 2}]}),
        encoding="utf-8",
    )

    code, envelope, diagnostics = invoke(
        monkeypatch, ["compare", str(left_path), str(right_path)]
    )

    assert code == 0
    assert diagnostics == ""
    assert envelope["ok"] is True
    data = cast("dict[str, object]", envelope["data"])
    scope = cast("dict[str, object]", data["scope"])
    assert scope["benchmark_version"] == "v1.1"
    changes = cast("list[dict[str, object]]", data["changes"])
    assert changes[0]["delta"] == 1


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
    envelope_error = cast("dict[str, object]", envelope["error"])
    assert envelope_error["code"] == "usage"
    assert diagnostics


def test_schema_is_json_only_and_declares_future_additive_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose the additive command and envelope schema as JSON."""
    stdout = io.StringIO()
    stderr = io.StringIO()

    def _now() -> str:
        return "2026-07-25T05:00:00+00:00"

    monkeypatch.setattr(cli, "_now", _now)
    code = cli.main(["schema", "--version", "v1.1"], stdout=stdout, stderr=stderr)
    envelope = cast("dict[str, object]", json.loads(stdout.getvalue()))
    assert code == 0
    assert stderr.getvalue() == ""
    assert envelope["ok"] is True
    data = cast("dict[str, object]", envelope["data"])
    schema = cast("dict[str, object]", data["schema"])
    assert schema["commands"] == list(PUBLIC_COMMANDS)
    scope_schema = cast("dict[str, object]", schema["scope"])
    assert scope_schema["value_status"] == ["published", "published_raw", "derived"]
    comp_schema = cast("dict[str, object]", schema["comparison"])
    assert comp_schema["strict_compare"] == "--strict-compare"
    assert comp_schema["strict_semantics"] == "--strict-semantics"
    diag_schema = cast("dict[str, object]", schema["diagnostics"])
    assert diag_schema["field"] == "diagnostics"
    ev_schema = cast("dict[str, object]", schema["evidence"])
    assert "comparison_eligibility" in cast("list[object]", ev_schema["fields"])
    overlap_schema = cast("dict[str, object]", schema["overlap"])
    assert overlap_schema["dependencies"] == []
    scope = cast("dict[str, object]", data["scope"])
    assert scope["benchmark_version"] == "v1.1"


def _write_compare_payload(path: Path, payload: Mapping[str, object]) -> None:
    _ = path.write_text(json.dumps(payload), encoding="utf-8")


def test_compare_duplicate_conflict_warns_legacy_and_blocks_strict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Legacy compare keeps first duplicate; strict compare exposes a blocker."""
    left = {
        "benchmark": "DeepSWE",
        "benchmark_version": "v1.1",
        "rows": [
            {
                "model": "m",
                "reasoning_effort": "high",
                "harness": "h",
                "config": "c",
                "pass_at_1": 0.2,
            },
            {
                "model": "m",
                "reasoning_effort": "high",
                "harness": "h",
                "config": "c",
                "pass_at_1": 0.3,
            },
        ],
    }
    right = {
        **left,
        "rows": [
            {
                "model": "m",
                "reasoning_effort": "high",
                "harness": "h",
                "config": "c",
                "pass_at_1": 0.4,
            }
        ],
    }
    snapshot_dir = tmp_path / "v1.1"
    snapshot_dir.mkdir()
    left_path = snapshot_dir / "left.json"
    right_path = snapshot_dir / "right.json"
    _write_compare_payload(left_path, left)
    _write_compare_payload(right_path, right)

    code, envelope, diagnostics = invoke(
        monkeypatch,
        ["compare", str(left_path), str(right_path), "--version", "v1.1"],
    )
    assert code == 0
    assert diagnostics == ""
    data = cast("dict[str, object]", envelope["data"])
    changes = cast("list[dict[str, object]]", data["changes"])
    assert changes[0]["before"] == 0.2
    assert changes[0]["after"] == 0.4
    warnings = cast("list[dict[str, object]]", data["warnings"])
    assert any(item["code"] == "DUPLICATE_CONFLICT" for item in warnings)

    code, envelope, diagnostics = invoke(
        monkeypatch,
        ["compare", str(left_path), str(right_path), "--strict-compare"],
    )
    assert code == 0
    assert diagnostics == ""
    data = cast("dict[str, object]", envelope["data"])
    assert data["changes"] == []
    blocked = cast("list[dict[str, object]]", data["blocked"])
    assert blocked[0]["reason"] == "duplicate_conflict"
    diags = cast("list[dict[str, object]]", data["diagnostics"])
    assert any(item["code"] == "DUPLICATE_CONFLICT" for item in diags)


def test_strict_compare_blocks_schema_and_denominator_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Strict diff checks artifact schema and metric denominator declarations."""
    base = {
        "benchmark": "DeepSWE",
        "benchmark_version": "v1.1",
        "rows": [
            {
                "model": "m",
                "reasoning_effort": "high",
                "harness": "h",
                "config": "c",
                "pass_at_1": 0.2,
            }
        ],
    }
    left = {
        **base,
        "artifact_schema_version": 1,
        "metric_semantics": {
            "pass_at_1": {
                "unit": "ratio",
                "scope": "tasks",
                "denominator": "tasks",
            }
        },
    }
    right = {
        **base,
        "artifact_schema_version": 2,
        "metric_semantics": {
            "pass_at_1": {
                "unit": "ratio",
                "scope": "tasks",
                "denominator": "attempts",
            }
        },
    }
    left_path = tmp_path / "left.json"
    right_path = tmp_path / "right.json"
    _write_compare_payload(left_path, left)
    _write_compare_payload(right_path, right)

    def load_art_1(path: object) -> object:
        return left if str(path) == str(left_path) else right

    monkeypatch.setattr(cli, "load_artifact", load_art_1)
    code, envelope, diagnostics = invoke(
        monkeypatch,
        [
            "compare",
            str(left_path),
            str(right_path),
            "--version",
            "v1.1",
            "--strict-compare",
        ],
    )
    assert code == 0
    assert diagnostics == ""
    data = cast("dict[str, object]", envelope["data"])
    assert data["changes"] == []
    blocked = cast("list[dict[str, object]]", data["blocked"])
    assert blocked[0]["reason"] == "schema_mismatch"
    diags = cast("list[dict[str, object]]", data["diagnostics"])
    assert diags[0]["code"] == "SCHEMA_DRIFT"
    right_semantic = {**right, "artifact_schema_version": 1}

    def load_art_2(path: object) -> object:
        return left if str(path) == str(left_path) else right_semantic

    monkeypatch.setattr(cli, "load_artifact", load_art_2)
    code, envelope, diagnostics = invoke(
        monkeypatch,
        [
            "compare",
            str(left_path),
            str(right_path),
            "--version",
            "v1.1",
            "--strict-compare",
        ],
    )
    assert code == 0
    assert diagnostics == ""
    data = cast("dict[str, object]", envelope["data"])
    blocked = cast("list[dict[str, object]]", data["blocked"])
    assert blocked[0]["reason"] == "denominator_mismatch"


def test_diagnose_snapshot_is_offline_and_metrics_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Diagnose snapshots without fetching or exposing row/task bodies."""
    path = tmp_path / "v1.1" / "leaderboard-live.json"
    path.parent.mkdir()
    _ = path.write_text(
        json.dumps(
            {
                "benchmark": "DeepSWE",
                "benchmark_version": "v1.1",
                "artifact": "leaderboard-live.json",
                "rows": [
                    {
                        "model": "secret-model",
                        "pass_at_1": 0.5,
                        "task_id": "task-body",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def unexpected_fetch(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "snapshot diagnose must remain offline"
        raise AssertionError(msg)

    monkeypatch.setattr(cli, "fetch_artifacts", unexpected_fetch)
    code, envelope, diagnostics = invoke(
        monkeypatch, ["diagnose", "--snapshot", str(path)]
    )
    assert code == 0
    assert diagnostics == ""
    data = cast("dict[str, object]", envelope["data"])
    assert "rows" not in data
    summary = cast("dict[str, object]", data["summary"])
    assert summary["row_count"] == 1
    summary_metrics = cast("dict[str, dict[str, object]]", summary["metrics"])
    assert summary_metrics["pass_at_1"]["max"] == 0.5
    assert "task-body" not in json.dumps(envelope)


def test_diagnose_trials_is_explicit_and_body_free(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Only --trials selects the raw trial artifact, still returning summaries."""
    path = tmp_path / "v1.1" / "trials.json"
    path.parent.mkdir()
    _ = path.write_text(
        json.dumps(
            {
                "benchmark": "DeepSWE",
                "benchmark_version": "v1.1",
                "artifact": "trials.json",
                "rows": [
                    {
                        "trial_id": "trial-body",
                        "passed": True,
                        "mean_output_tokens": 12,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    code, envelope, diagnostics = invoke(
        monkeypatch,
        ["diagnose", "--snapshot", str(path), "--trials"],
    )
    assert code == 0
    assert diagnostics == ""
    data = cast("dict[str, object]", envelope["data"])
    summary = cast("dict[str, object]", data["summary"])
    assert summary["artifact"] == "trials.json"
    assert "rows" not in data
    assert "trial-body" not in json.dumps(envelope)


if __name__ == "__main__":
    _ = pytest.main([__file__])
