#!/usr/bin/env python3
"""UI/UX Pro Max Search - BM25 search engine for UI/UX style guides.

Usage:
    python search.py "<query>" [--domain <domain>] [--stack <stack>]
        [--max-results 3]
    python search.py "<query>" --design-system [-p "Project Name"]
    python search.py "<query>" --design-system --persist [-p "Project Name"]
        [--page "dashboard"]
    python search.py "<query>" --design-system --variance 8 --motion 9
        --density 7

Domains: style, color, chart, landing, product, ux, typography,
    google-fonts, icons, gsap, react, web
Stacks: react, nextjs, vue, svelte, astro, swiftui, react-native, flutter,
    nuxtjs, nuxt-ui, html-tailwind, shadcn, jetpack-compose, threejs, angular,
    laravel, javafx, wpf, winui, avalonia, uno, uwp

Design dials (1-10, only with --design-system):
  --variance   DESIGN_VARIANCE: 1=centered/minimal, 10=bold/asymmetric
  --motion     MOTION_INTENSITY: 1=subtle, 10=complex; attaches a GSAP
    snippet from motion.csv
  --density    VISUAL_DENSITY: 1=spacious, 10=dense/dashboard; overrides
    the spacing scale

Persistence (Master + Overrides pattern):
  --persist    Save design system to design-system/MASTER.md
  --page       Also create a page-specific override file in design-system/pages/
"""

import argparse
import io
import json
import sys
from collections.abc import Mapping
from typing import TypeIs

from core import (
    AVAILABLE_STACKS,
    CSV_CONFIG,
    MAX_RESULTS,
    UNTRUNCATED_COLS,
    search,
    search_stack,
)
from design_system import generate_design_system

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


def _is_object_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


def _is_str_mapping(val: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(val, Mapping)


_MAX_VALUE_CHARS = 300


def _opt_str(args: argparse.Namespace, field: str) -> str | None:
    """Narrow an optional string CLI value."""
    value = getattr(args, field, None)
    return value if isinstance(value, str) else None


def _req_str(args: argparse.Namespace, field: str) -> str:
    """Narrow a required string CLI value."""
    value = getattr(args, field, None)
    if not isinstance(value, str):
        message = f"Missing required CLI value: {field}."
        raise TypeError(message)
    return value


def _opt_int(args: argparse.Namespace, field: str) -> int | None:
    """Narrow an optional integer CLI value."""
    value = getattr(args, field, None)
    return value if isinstance(value, int) else None


def _req_int(args: argparse.Namespace, field: str, default: int) -> int:
    """Narrow a required integer CLI value."""
    value = getattr(args, field, None)
    return value if isinstance(value, int) else default


def _flag(args: argparse.Namespace, field: str) -> bool:
    """Narrow a boolean CLI flag."""
    value = getattr(args, field, None)
    return value if isinstance(value, bool) else False


def format_output(result: Mapping[str, object], full: bool = False) -> str:  # noqa: C901 - format handles all search result variants
    """Format results for Claude consumption (token-optimized)."""
    if "error" in result:
        return f"Error: {result['error']}"

    output: list[str] = []
    if result.get("stack"):
        output.append("## UI Pro Max Stack Guidelines")
        output.append(f"**Stack:** {result['stack']} | **Query:** {result['query']}")
    else:
        output.append("## UI Pro Max Search Results")
        domain_note = str(result["domain"])
        if result.get("auto_detected"):
            domain_note += " (auto-detected"
            if result.get("runner_up_domain"):
                domain_note += f", runner-up: {result['runner_up_domain']}"
            domain_note += ")"
        output.append(f"**Domain:** {domain_note} | **Query:** {result['query']}")
    output.append(
        f"**Source:** {result['file']} | **Found:** {result['count']} results\n",
    )
    if result.get("count") == 0:
        redirect = result.get("redirect")
        if _is_str_mapping(redirect):
            output.append(
                "This legacy style label is now modeled in the "
                + f"`{redirect['domain']}` domain as `{redirect['id']}`. "
                + "Search that domain instead of treating a page composition "
                + "as a visual style."
            )
            return "\n".join(output)
        output.append(
            "No matches. This is not a match with an empty value -- the query "
            + "did not hit the database. Retry with broader/different keywords "
            + "before falling back to general defaults, and say explicitly that "
            + "no database match was found if you do fall back."
        )
        suggestions = result.get("suggestions")
        if _is_object_list(suggestions) and suggestions:
            terms = ", ".join(str(term) for term in suggestions)
            output.append(f"**Closest known terms:** {terms}")
        return "\n".join(output)

    rows = result.get("results")
    if not _is_object_list(rows):
        return "\n".join(output)
    for i, row in enumerate(rows, 1):
        if not _is_str_mapping(row):
            continue
        output.append(f"### Result {i}")
        for key, value in row.items():
            value_str = str(value)
            if (
                not full
                and key not in UNTRUNCATED_COLS
                and len(value_str) > _MAX_VALUE_CHARS
            ):
                value_str = value_str[:_MAX_VALUE_CHARS] + "..."
            output.append(f"- **{key}:** {value_str}")
        output.append("")
    return "\n".join(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UI Pro Max Search")
    _ = parser.add_argument("query", help="Search query")
    _ = parser.add_argument(
        "--domain",
        "-d",
        choices=list(CSV_CONFIG.keys()),
        help="Search domain",
    )
    _ = parser.add_argument(
        "--stack",
        "-s",
        choices=AVAILABLE_STACKS,
        help=f"Stack-specific search. Available: {', '.join(AVAILABLE_STACKS)}",
    )
    _ = parser.add_argument(
        "--max-results",
        "-n",
        type=int,
        choices=range(1, 21),
        metavar="1-20",
        default=MAX_RESULTS,
        help="Max results (default: 3)",
    )
    _ = parser.add_argument("--json", action="store_true", help="Output as JSON")
    _ = parser.add_argument(
        "--full", action="store_true", help="Do not truncate long field values"
    )
    # Design system generation
    _ = parser.add_argument(
        "--design-system",
        "-ds",
        action="store_true",
        help="Generate complete design system recommendation",
    )
    _ = parser.add_argument(
        "--project-name",
        "-p",
        type=str,
        default=None,
        help="Project name for design system output",
    )
    _ = parser.add_argument(
        "--format",
        "-f",
        choices=["ascii", "markdown"],
        default="ascii",
        help="Output format for design system",
    )
    # Persistence (Master + Overrides pattern)
    _ = parser.add_argument(
        "--persist",
        action="store_true",
        help="Save design system to design-system/MASTER.md "
        + "(creates hierarchical structure)",
    )
    _ = parser.add_argument(
        "--page",
        type=str,
        default=None,
        help="Create page-specific override file in design-system/pages/",
    )
    _ = parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Output directory for persisted files (default: current directory)",
    )
    _ = parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing MASTER.md"
    )
    # Design dials (1-10), only applied with --design-system
    _ = parser.add_argument(
        "--variance",
        type=int,
        choices=range(1, 11),
        metavar="1-10",
        help="DESIGN_VARIANCE dial: 1=centered/minimal, 10=bold/asymmetric "
        + "(only with --design-system)",
    )
    _ = parser.add_argument(
        "--motion",
        type=int,
        choices=range(1, 11),
        metavar="1-10",
        help="MOTION_INTENSITY dial: 1=subtle, 10=complex; "
        + "pulls a matching GSAP snippet from motion.csv (only with --design-system)",
    )
    _ = parser.add_argument(
        "--density",
        type=int,
        choices=range(1, 11),
        metavar="1-10",
        help="VISUAL_DENSITY dial: 1=spacious, 10=dense/dashboard; "
        + "overrides the spacing scale (only with --design-system)",
    )

    args = parser.parse_args()

    # Design system takes priority
    if _flag(args, "design_system"):
        query = _req_str(args, "query")
        result = generate_design_system(
            query,
            _opt_str(args, "project_name"),
            _req_str(args, "format"),
            persist=_flag(args, "persist"),
            page=_opt_str(args, "page"),
            output_dir=_opt_str(args, "output_dir"),
            variance=_opt_int(args, "variance"),
            motion=_opt_int(args, "motion"),
            density=_opt_int(args, "density"),
            force=_flag(args, "force"),
        )
        if _flag(args, "json"):
            print(
                json.dumps(
                    {
                        "design_system": result["design_system"],
                        "persistence": result["persistence"],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print(result["text"])
            persistence = result.get("persistence")
            if _flag(args, "persist") and _is_str_mapping(persistence):
                print("\n" + "=" * 60)
                if persistence.get("status") == "skipped_exists":
                    message = persistence.get(
                        "message", "MASTER.md already exists; not overwritten."
                    )
                    print(f"⚠️  {message}")
                else:
                    ds_dir = persistence.get(
                        "design_system_dir", "design-system/<project>"
                    )
                    print(f"✅ Design system persisted to {ds_dir}/")
                    created_files = persistence.get("created_files")
                    if _is_object_list(created_files):
                        for file in created_files:
                            print(f"   📄 {file}")
                    print(
                        "\n📖 Usage: When building a page, check "
                        + f"{ds_dir}/pages/[page].md first."
                    )
                    print(
                        "   If it exists, its rules override MASTER.md. "
                        + "Otherwise, use MASTER.md."
                    )
                print("=" * 60)
    # Stack search
    elif _opt_str(args, "stack"):
        result = search_stack(
            _req_str(args, "query"),
            _req_str(args, "stack"),
            _req_int(args, "max_results", MAX_RESULTS),
        )
        if _flag(args, "json"):
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(format_output(result, full=_flag(args, "full")))
    # Domain search
    else:
        result = search(
            _req_str(args, "query"),
            _opt_str(args, "domain"),
            _req_int(args, "max_results", MAX_RESULTS),
        )
        if _flag(args, "json"):
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(format_output(result, full=_flag(args, "full")))
