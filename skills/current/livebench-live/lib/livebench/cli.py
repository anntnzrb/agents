# Copyright (c) 2026
"""One-shot LiveBench CLI with a compact JSON success/failure envelope."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, TextIO, cast, override

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

from .cache import CacheStore
from .catalog_diff import diff_catalog, load_snapshot_catalog
from .commands import (
    ReleaseContext,
    build_releases_data,
    catalog_data,
    load_context,
    project_data,
    snapshot_manifest,
)
from .contracts import (
    SCHEMA_VERSION,
    SkillError,
    compact_json,
    failure,
    raise_expected,
    success,
)
from .diagnostics import redact
from .discovery import discover_releases
from .identity import canonical_token
from .semantics import OVERALL_DEFINITION, OVERALL_FORMULA

COMMANDS = (
    "releases",
    "catalog",
    "leaderboard",
    "model",
    "compare",
    "category",
    "subtasks",
    "catalog-diff",
    "diagnose",
    "schema",
    "refresh",
    "snapshot",
)


class _Parser(argparse.ArgumentParser):
    @override
    def error(self, message: str) -> NoReturn:
        """Error for the LiveBench adapter."""
        raise_expected("USAGE", message, {}, exit_code=2)


def build_parser() -> argparse.ArgumentParser:
    """Build parser for the LiveBench adapter."""
    parser = _Parser(
        prog="livebench-live",
        add_help=True,
        description="Official LiveBench release and leaderboard data",
    )
    sub = parser.add_subparsers(dest="command")
    add_parser = sub.add_parser
    _add_releases(add_parser)
    _add_release_command(add_parser, "catalog")
    _add_release_command(add_parser, "leaderboard")
    _add_release_command(add_parser, "model", features=("model",))
    _add_release_command(add_parser, "compare", features=("models",))
    _add_release_command(add_parser, "category", features=("category",))
    _add_release_command(add_parser, "subtasks", features=("model", "category"))
    diff_parser = add_parser(
        "catalog-diff", help="diff two explicit catalog/release snapshots"
    )
    _ = diff_parser.add_argument("--left", required=True, type=Path)
    _ = diff_parser.add_argument("--right", required=True, type=Path)
    _add_release_command(add_parser, "diagnose")
    schema_parser = add_parser("schema", help="describe the stable output contract")
    _ = schema_parser.add_argument(
        "--json", action="store_true", help=argparse.SUPPRESS
    )
    _add_release_command(add_parser, "refresh", features=("output",))
    _add_release_command(add_parser, "snapshot", features=("output",))
    return parser


def _add_releases(add_parser: Callable[..., argparse.ArgumentParser]) -> None:
    parser = add_parser(
        "releases", help="discover releases from the current official app/bundle"
    )
    _ = parser.add_argument(
        "--snapshot", type=Path, help="explicit local release snapshot"
    )
    _ = parser.add_argument("--cache-dir", type=Path, default=None)
    _ = parser.add_argument("--timeout", type=float, default=30.0)
    _ = parser.add_argument("--allow-stale", action="store_true")


def _add_release_command(
    add_parser: Callable[..., argparse.ArgumentParser],
    name: str,
    *,
    features: tuple[str, ...] = (),
) -> None:
    parser = add_parser(name, help=f"{name} LiveBench release data")
    _ = parser.add_argument(
        "--release",
        default="latest",
        help="latest or an exact source-advertised release ID",
    )
    _ = parser.add_argument(
        "--snapshot", type=Path, help="read only this explicit local snapshot"
    )
    _ = parser.add_argument("--cache-dir", type=Path, default=None)
    _ = parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="permit a failed refresh to serve matching stale cache",
    )
    _ = parser.add_argument("--timeout", type=float, default=30.0)
    _ = parser.add_argument("--table-url", default=None, help=argparse.SUPPRESS)
    _ = parser.add_argument("--categories-url", default=None, help=argparse.SUPPRESS)
    _ = parser.add_argument("--cost-url", default=None, help=argparse.SUPPRESS)
    if "model" in features:
        _ = parser.add_argument("--model", required=True)
    if "models" in features:
        _ = parser.add_argument(
            "--models",
            required=True,
            help="comma-separated exact model/model-variant selectors",
        )
    if "category" in features:
        _ = parser.add_argument("--category", required=True)
    if "output" in features:
        _ = parser.add_argument("--output", type=Path, default=None)
    if name == "diagnose":
        _ = parser.add_argument("--asset", default=None, help=argparse.SUPPRESS)


def _str_arg(args: argparse.Namespace, name: str, default: str = "") -> str:
    val: object = getattr(args, name, default)
    return str(val) if val is not None else default


def _opt_str_arg(args: argparse.Namespace, name: str) -> str | None:
    val: object = getattr(args, name, None)
    return str(val) if val is not None else None


def _path_arg(args: argparse.Namespace, name: str) -> Path | None:
    val: object = getattr(args, name, None)
    if isinstance(val, Path):
        return val
    if isinstance(val, str) and val:
        return Path(val)
    return None


def _float_arg(args: argparse.Namespace, name: str, default: float = 30.0) -> float:
    val: object = getattr(args, name, default)
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            return default
    return default


def _bool_arg(args: argparse.Namespace, name: str) -> bool:
    val: object = getattr(args, name, False)
    return bool(val)


def _redact_details(data: Mapping[str, object]) -> dict[str, object]:
    redacted = redact(data)
    if isinstance(redacted, dict):
        return cast("dict[str, object]", redacted)
    return {}


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the LiveBench adapter."""
    _ = stderr
    out = stdout or sys.stdout
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    command = next((item for item in raw_argv if not item.startswith("-")), "unknown")
    parser = build_parser()
    if any(item in {"-h", "--help"} for item in raw_argv):
        _ = out.write(
            compact_json(
                success(
                    "help",
                    {
                        "usage": parser.format_usage().strip(),
                        "commands": list(COMMANDS),
                    },
                )
            )
            + "\n"
        )
        return 0
    try:
        args = parser.parse_args(raw_argv)
        cmd = _opt_str_arg(args, "command")
        if not cmd:
            raise_expected(
                "USAGE",
                "A command is required.",
                {"commands": list(COMMANDS)},
                exit_code=2,
            )
        command = cmd
        payload = _dispatch(args)
        _ = out.write(compact_json(payload) + "\n")
        return 0  # noqa: TRY300
    except SkillError as exc:
        safe_details = _redact_details(exc.details)
        safe = SkillError(exc.code, exc.message, safe_details, exit_code=exc.exit_code)
        _ = out.write(compact_json(failure(command, safe)) + "\n")
        return exc.exit_code
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        err_details: dict[str, object] = {"error": str(exc)}
        safe_details = _redact_details(err_details)
        error = SkillError(
            "SOURCE_UNAVAILABLE",
            "LiveBench command failed before producing a usable result.",
            safe_details,
        )
        _ = out.write(compact_json(failure(command, error)) + "\n")
        return 1
    except Exception as exc:  # noqa: BLE001
        # Keep stdout contractual even for unexpected adapter drift.
        drift_details: dict[str, object] = {"error": str(exc)}
        safe_details = _redact_details(drift_details)
        error = SkillError(
            "MALFORMED_PAYLOAD",
            "LiveBench adapter encountered an unexpected source shape.",
            safe_details,
        )
        _ = out.write(compact_json(failure(command, error)) + "\n")
        return 1


def _dispatch(args: argparse.Namespace) -> dict[str, object]:
    command = _str_arg(args, "command")
    if command == "schema":
        return success(command, _schema_data())
    if command == "catalog-diff":
        return _catalog_diff(command, args)
    if command == "releases":
        return _releases(command, args)
    context = _load_context(args)
    return _dispatch_context(command, args, context)


def _catalog_diff(command: str, args: argparse.Namespace) -> dict[str, object]:
    left_path = _path_arg(args, "left")
    right_path = _path_arg(args, "right")
    left_str = str(left_path) if left_path is not None else ""
    right_str = str(right_path) if right_path is not None else ""
    left, left_provenance = load_snapshot_catalog(left_str)
    right, right_provenance = load_snapshot_catalog(right_str)
    data: dict[str, object] = {
        "scope": {
            "source": "livebench",
            "release": None,
            "filters_applied": {"left": left_str, "right": right_str},
        },
        "value_status": "published",
        "rows": [],
        "catalog_diff": diff_catalog(left, right),
        "warnings": [],
        "diagnostics": [],
        "provenance": {"left": left_provenance, "right": right_provenance},
    }
    return success(command, data)


def _releases(command: str, args: argparse.Namespace) -> dict[str, object]:
    snapshot = _path_arg(args, "snapshot")
    cache_dir = _path_arg(args, "cache_dir")
    timeout = _float_arg(args, "timeout", 30.0)
    discovery = discover_releases(
        snapshot=snapshot,
        cache=CacheStore(cache_dir),
        timeout=timeout,
    )
    return success(command, build_releases_data(discovery))


def _load_context(args: argparse.Namespace) -> ReleaseContext:
    return load_context(
        release_selector=_opt_str_arg(args, "release") or "latest",
        snapshot=_path_arg(args, "snapshot"),
        cache_dir=_path_arg(args, "cache_dir"),
        allow_stale=_bool_arg(args, "allow_stale"),
        timeout=_float_arg(args, "timeout", 30.0),
        table_url=_opt_str_arg(args, "table_url"),
        categories_url=_opt_str_arg(args, "categories_url"),
        cost_url=_opt_str_arg(args, "cost_url"),
    )


def _dispatch_context(
    command: str, args: argparse.Namespace, context: ReleaseContext
) -> dict[str, object]:
    if command == "catalog":
        return success(command, catalog_data(context))
    if command in {"leaderboard", "diagnose", "refresh", "snapshot"}:
        return _dispatch_projection(command, args, context)
    return _dispatch_filtered(command, args, context)


def _dispatch_filtered(
    command: str, args: argparse.Namespace, context: ReleaseContext
) -> dict[str, object]:
    if command == "model":
        model_str = _str_arg(args, "model")
        return success(
            command,
            project_data(context, model=model_str, include_rank=False),
        )
    if command == "compare":
        models_str = _str_arg(args, "models")
        selectors = [item.strip() for item in models_str.split(",") if item.strip()]
        data = project_data(context, models=selectors, include_rank=True)
        data["comparison"] = _comparison(data.get("rows"))
        return success(command, data)
    if command == "category":
        category_str = _str_arg(args, "category")
        return success(
            command,
            project_data(context, category=category_str, include_rank=True),
        )
    if command == "subtasks":
        return _subtasks(command, args, context)
    return raise_expected(
        "USAGE",
        f"Unsupported command {command!r}.",
        {"commands": list(COMMANDS)},
        exit_code=2,
    )


def _dispatch_projection(
    command: str, args: argparse.Namespace, context: ReleaseContext
) -> dict[str, object]:
    if command == "diagnose":
        return success(command, project_data(context, include_rank=True))
    if command == "refresh":
        return _refresh(command, args, context)
    if command == "snapshot":
        return _snapshot(command, args, context)
    return success(command, project_data(context, include_rank=True))


def _refresh(
    command: str, args: argparse.Namespace, context: ReleaseContext
) -> dict[str, object]:
    data = project_data(context)
    data["refresh"] = {
        "release": context.release.as_dict(),
        "artifacts": [
            artifact.provenance(parser="livebench.refresh")
            for artifact in context.parsed.artifacts.values()
        ],
    }
    output = _path_arg(args, "output")
    if output is not None:
        _ = output.write_text(compact_json(data), encoding="utf-8")
    return success(command, data)


def _snapshot(
    command: str, args: argparse.Namespace, context: ReleaseContext
) -> dict[str, object]:
    output = _path_arg(args, "output")
    manifest = snapshot_manifest(context, output)
    data = project_data(context)
    data["snapshot"] = manifest
    return success(command, data)


def _filter_subtasks(
    subtasks_raw: object, category_key: str
) -> list[dict[str, object]]:
    subtasks_list: list[dict[str, object]] = []
    if isinstance(subtasks_raw, list):
        for item in cast("list[object]", subtasks_raw):
            if isinstance(item, dict):
                item_dict = cast("dict[str, object]", item)
                if item_dict.get("category_id") == f"livebench:category:{category_key}":
                    subtasks_list.append(item_dict)
    return subtasks_list


def _subtasks(
    command: str, args: argparse.Namespace, context: ReleaseContext
) -> dict[str, object]:
    model_str = _str_arg(args, "model")
    category_str = _str_arg(args, "category")
    data = project_data(
        context,
        model=model_str,
        category=category_str,
        include_rank=False,
    )
    category_key = canonical_category(category_str)
    rows = data.get("rows")
    if isinstance(rows, list):
        for row in cast("list[object]", rows):
            if isinstance(row, dict):
                row_dict = cast("dict[str, object]", row)
                row_dict["subtasks"] = _filter_subtasks(
                    row_dict.get("subtasks"), category_key
                )
                row_dict["selected_category"] = category_key
    return success(command, data)


def canonical_category(value: str) -> str:
    """Canonical category for the LiveBench adapter."""
    return canonical_token(value)


def _extract_release_ids(rows: list[object]) -> set[str]:
    release_ids: set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            rel = cast("dict[str, object]", row).get("release")
            if isinstance(rel, dict):
                rel_id = cast("dict[str, object]", rel).get("id")
                if rel_id is not None:
                    release_ids.add(str(rel_id))
    return release_ids


def _check_row_blocked(row_dict: dict[str, object], blocked: list[str]) -> None:
    overall = row_dict.get("overall")
    if (
        not isinstance(overall, dict)
        or cast("dict[str, object]", overall).get("normalized_value") is None
    ):
        blocked.append("missing_overall")
    if row_dict.get("_duplicate_conflict"):
        blocked.append("duplicate_identity")


def _comparison(rows: object) -> dict[str, object]:
    if not isinstance(rows, list):
        return {"status": "blocked", "blocked_reasons": ["rows_unavailable"]}
    rows_list = cast("list[object]", rows)
    release_ids = _extract_release_ids(rows_list)
    blocked: list[str] = []
    if len(release_ids) != 1:
        blocked.append("release_identity_mismatch")
    for row in rows_list:
        if isinstance(row, dict):
            _check_row_blocked(cast("dict[str, object]", row), blocked)
    return {
        "status": "eligible" if not blocked else "blocked",
        "comparison_key": {
            "source": "livebench",
            "release_id": next(iter(release_ids), None),
            "metric": "overall",
            "definition": OVERALL_FORMULA,
            "scope": "release",
        },
        "blocked_reasons": sorted(set(blocked)),
    }


def _schema_data() -> dict[str, object]:
    return {
        "scope": {"source": "livebench", "release": None, "filters_applied": {}},
        "value_status": "published",
        "rows": [],
        "warnings": [],
        "provenance": {
            "parser": "livebench.cli",
            "parser_version": "1",
            "freshness": {"mode": "fresh", "historical": False, "stale": False},
        },
        "schema_version": SCHEMA_VERSION,
        "commands": list(COMMANDS),
        "value_statuses": ["published", "derived", "missing", "unparsed"],
        "diagnostic_codes": [
            "SOURCE_UNAVAILABLE",
            "SOURCE_AUTH_REQUIRED",
            "REQUIRES_RENDERED_SOURCE",
            "RELEASE_NOT_FOUND",
            "MIXED_RELEASE",
            "STALE_DATA",
            "HISTORICAL_SNAPSHOT",
            "RELEASE_DISCOVERY_LIMITED",
            "CACHE_MISSING",
            "CACHE_VALIDATOR_INVALID",
            "MALFORMED_PAYLOAD",
            "SCHEMA_DRIFT",
            "UNKNOWN_SCORE_SEMANTICS",
            "UNKNOWN_CATEGORY",
            "PLACEHOLDER_VALUE",
            "NUMERIC_AMBIGUITY",
            "OUT_OF_RANGE",
            "DUPLICATE_MODEL_VARIANT",
            "MISSING_REQUIRED_IDENTITY",
            "PARTIAL_EXTRACTION",
            "SNAPSHOT_INVALID",
            "MODEL_NOT_FOUND",
            "COMPARISON_INCOMPARABLE",
            "OVERLAP_DOUBLE_COUNTING_RISK",
        ],
        "dynamic_rules": {
            "releases": (
                "discover from the current official application/bundle authority; "
                "never enumerate an origin directory"
            ),
            "categories": "keys from the release category JSON map",
            "subtasks": "category-array task keys plus unmapped score headers",
            "models": "all score-table rows, including unknown metadata rows",
            "unknown_fields": "retained under raw_fields/raw_metadata",
            "overall": {
                "value_status": "derived",
                "formula": OVERALL_FORMULA,
                "definition": OVERALL_DEFINITION,
                "never_alias": "pass_at_1",
            },
            "cost": {
                "published_fields": ["cost_per_question", "cost_per_successful_task"],
                "derived_formula": "(sum cost / sum questions / selected score) * 100",
            },
            "cache": (
                "immutable sha256 bytes with ETag and Last-Modified; "
                "stale requires --allow-stale; snapshots are explicit"
            ),
        },
    }
