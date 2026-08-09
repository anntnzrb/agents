# Copyright (c) 2026
"""One-shot LiveBench CLI with a compact JSON success/failure envelope."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from collections.abc import Sequence

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
    def error(self, message: str) -> None:
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
    _add_releases(sub)
    _add_release_command(sub, "catalog")
    _add_release_command(sub, "leaderboard")
    _add_release_command(sub, "model", features=("model",))
    _add_release_command(sub, "compare", features=("models",))
    _add_release_command(sub, "category", features=("category",))
    _add_release_command(sub, "subtasks", features=("model", "category"))
    diff_parser = sub.add_parser(
        "catalog-diff", help="diff two explicit catalog/release snapshots"
    )
    diff_parser.add_argument("--left", required=True, type=Path)
    diff_parser.add_argument("--right", required=True, type=Path)
    _add_release_command(sub, "diagnose")
    schema_parser = sub.add_parser("schema", help="describe the stable output contract")
    schema_parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    _add_release_command(sub, "refresh", features=("output",))
    _add_release_command(sub, "snapshot", features=("output",))
    return parser


def _add_releases(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "releases", help="discover releases from the current official app/bundle"
    )
    parser.add_argument("--snapshot", type=Path, help="explicit local release snapshot")
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--allow-stale", action="store_true")


def _add_release_command(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    *,
    features: tuple[str, ...] = (),
) -> None:
    parser = sub.add_parser(name, help=f"{name} LiveBench release data")
    parser.add_argument(
        "--release",
        default="latest",
        help="latest or an exact source-advertised release ID",
    )
    parser.add_argument(
        "--snapshot", type=Path, help="read only this explicit local snapshot"
    )
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="permit a failed refresh to serve matching stale cache",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--table-url", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--categories-url", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--cost-url", default=None, help=argparse.SUPPRESS)
    if "model" in features:
        parser.add_argument("--model", required=True)
    if "models" in features:
        parser.add_argument(
            "--models",
            required=True,
            help="comma-separated exact model/model-variant selectors",
        )
    if "category" in features:
        parser.add_argument("--category", required=True)
    if "output" in features:
        parser.add_argument("--output", type=Path, default=None)
    if name == "diagnose":
        parser.add_argument("--asset", default=None, help=argparse.SUPPRESS)


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,  # noqa: ARG001
) -> int:
    """Run the LiveBench adapter."""
    out = stdout or sys.stdout
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    command = next((item for item in raw_argv if not item.startswith("-")), "unknown")
    parser = build_parser()
    if any(item in {"-h", "--help"} for item in raw_argv):
        out.write(
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
        if not args.command:
            raise_expected(
                "USAGE",
                "A command is required.",
                {"commands": list(COMMANDS)},
                exit_code=2,
            )
        command = str(args.command)
        payload = _dispatch(args)
        out.write(compact_json(payload) + "\n")
        return 0  # noqa: TRY300
    except SkillError as exc:
        safe = SkillError(
            exc.code, exc.message, redact(exc.details), exit_code=exc.exit_code
        )
        out.write(compact_json(failure(command, safe)) + "\n")
        return exc.exit_code
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        error = SkillError(
            "SOURCE_UNAVAILABLE",
            "LiveBench command failed before producing a usable result.",
            {"error": str(exc)},
        )
        safe = SkillError(error.code, error.message, redact(error.details))
        out.write(compact_json(failure(command, safe)) + "\n")
        return 1
    except Exception as exc:  # noqa: BLE001
        # Keep stdout contractual even for unexpected adapter drift.
        error = SkillError(
            "MALFORMED_PAYLOAD",
            "LiveBench adapter encountered an unexpected source shape.",
            {"error": str(exc)},
        )
        safe = SkillError(error.code, error.message, redact(error.details))
        out.write(compact_json(failure(command, safe)) + "\n")
        return 1


def _dispatch(args: argparse.Namespace) -> dict[str, object]:
    command = str(args.command)
    if command == "schema":
        return success(command, _schema_data())
    if command == "catalog-diff":
        return _catalog_diff(command, args)
    if command == "releases":
        return _releases(command, args)
    context = _load_context(args)
    return _dispatch_context(command, args, context)


def _catalog_diff(command: str, args: argparse.Namespace) -> dict[str, object]:
    left, left_provenance = load_snapshot_catalog(str(args.left))
    right, right_provenance = load_snapshot_catalog(str(args.right))
    data = {
        "scope": {
            "source": "livebench",
            "release": None,
            "filters_applied": {"left": str(args.left), "right": str(args.right)},
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
    discovery = discover_releases(
        snapshot=args.snapshot,
        cache=CacheStore(args.cache_dir),
        timeout=float(args.timeout),
    )
    return success(command, build_releases_data(discovery))


def _load_context(args: argparse.Namespace) -> ReleaseContext:
    return load_context(
        release_selector=getattr(args, "release", "latest"),
        snapshot=getattr(args, "snapshot", None),
        cache_dir=getattr(args, "cache_dir", None),
        allow_stale=bool(getattr(args, "allow_stale", False)),
        timeout=float(getattr(args, "timeout", 30.0)),
        table_url=getattr(args, "table_url", None),
        categories_url=getattr(args, "categories_url", None),
        cost_url=getattr(args, "cost_url", None),
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
        return success(
            command,
            project_data(context, model=args.model, include_rank=False),
        )
    if command == "compare":
        selectors = [
            item.strip() for item in str(args.models).split(",") if item.strip()
        ]
        data = project_data(context, models=selectors, include_rank=True)
        data["comparison"] = _comparison(data["rows"])
        return success(command, data)
    if command == "category":
        return success(
            command,
            project_data(context, category=args.category, include_rank=True),
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
    output = getattr(args, "output", None)
    if output:
        Path(output).write_text(compact_json(data), encoding="utf-8")
    return success(command, data)


def _snapshot(
    command: str, args: argparse.Namespace, context: ReleaseContext
) -> dict[str, object]:
    manifest = snapshot_manifest(context, getattr(args, "output", None))
    data = project_data(context)
    data["snapshot"] = manifest
    return success(command, data)


def _subtasks(
    command: str, args: argparse.Namespace, context: ReleaseContext
) -> dict[str, object]:
    data = project_data(
        context,
        model=args.model,
        category=args.category,
        include_rank=False,
    )
    category_key = canonical_category(args.category)
    for row in data["rows"]:
        row["subtasks"] = [
            item
            for item in row.get("subtasks", [])
            if item.get("category_id") == f"livebench:category:{category_key}"
        ]
        row["selected_category"] = category_key
    return success(command, data)


def canonical_category(value: str) -> str:
    """Canonical category for the LiveBench adapter."""
    return canonical_token(value)


def _comparison(rows: object) -> dict[str, object]:
    if not isinstance(rows, list):
        return {"status": "blocked", "blocked_reasons": ["rows_unavailable"]}
    release_ids = {
        str(row.get("release", {}).get("id"))
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("release"), dict)
    }
    blocked: list[str] = []
    if len(release_ids) != 1:
        blocked.append("release_identity_mismatch")
    for row in rows:
        overall = row.get("overall") if isinstance(row, dict) else None
        if not isinstance(overall, dict) or overall.get("normalized_value") is None:
            blocked.append("missing_overall")
        if isinstance(row, dict) and row.get("_duplicate_conflict"):
            blocked.append("duplicate_identity")
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
