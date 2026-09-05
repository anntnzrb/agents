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

Domains: style, prompt, color, chart, landing, product, ux, typography,
    google-fonts, gsap
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
from typing import BinaryIO, TextIO, cast

from core import AVAILABLE_STACKS, CSV_CONFIG, MAX_RESULTS, search, search_stack
from design_system import generate_design_system


def _force_utf8(stream: TextIO) -> TextIO:
    """Rewrap a text stream in UTF-8 unless it already uses UTF-8."""
    encoding = stream.encoding
    if encoding and encoding.lower() == "utf-8":
        return stream
    raw_buffer = cast("object", getattr(stream, "buffer", None))
    if raw_buffer is None:
        return stream
    buffer = cast("BinaryIO", raw_buffer)
    return io.TextIOWrapper(buffer, encoding="utf-8")


# Force UTF-8 for stdout/stderr to handle emojis on Windows (cp1252 default)
sys.stdout = _force_utf8(sys.stdout)
sys.stderr = _force_utf8(sys.stderr)


_MAX_VALUE_CHARS = 300


def _opt_str(args: argparse.Namespace, field: str) -> str | None:
    """Narrow an optional string CLI value."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, str) else None


def _req_str(args: argparse.Namespace, field: str) -> str:
    """Narrow a required string CLI value."""
    value = cast("object", getattr(args, field))
    if not isinstance(value, str):
        message = f"Missing required CLI value: {field}."
        raise TypeError(message)
    return value


def _opt_int(args: argparse.Namespace, field: str) -> int | None:
    """Narrow an optional integer CLI value."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, int) else None


def _req_int(args: argparse.Namespace, field: str, default: int) -> int:
    """Narrow a required integer CLI value."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, int) else default


def _flag(args: argparse.Namespace, field: str) -> bool:
    """Narrow a boolean CLI flag."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, bool) else False


def format_output(result: Mapping[str, object]) -> str:
    """Format results for Claude consumption (token-optimized)."""
    if "error" in result:
        return f"Error: {result['error']}"

    output: list[str] = []
    if result.get("stack"):
        output.append("## UI Pro Max Stack Guidelines")
        output.append(f"**Stack:** {result['stack']} | **Query:** {result['query']}")
    else:
        output.append("## UI Pro Max Search Results")
        output.append(f"**Domain:** {result['domain']} | **Query:** {result['query']}")
    output.append(
        f"**Source:** {result['file']} | **Found:** {result['count']} results\n",
    )

    rows = cast("list[object]", result["results"])
    for i, row in enumerate(rows, 1):
        mapping = cast("Mapping[str, object]", row)
        output.append(f"### Result {i}")
        for key, value in mapping.items():
            value_str = str(value)
            if len(value_str) > _MAX_VALUE_CHARS:
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
        default=MAX_RESULTS,
        help="Max results (default: 3)",
    )
    _ = parser.add_argument("--json", action="store_true", help="Output as JSON")
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
        )
        print(result)

        # Print persistence confirmation
        if _flag(args, "persist"):
            project_name = _opt_str(args, "project_name")
            project_slug = (project_name or query).lower().replace(" ", "-")
            print("\n" + "=" * 60)
            print(f"✅ Design system persisted to design-system/{project_slug}/")
            print(
                f"   📄 design-system/{project_slug}/MASTER.md "
                + "(Global Source of Truth)",
            )
            page = _opt_str(args, "page")
            if page:
                page_filename = page.lower().replace(" ", "-")
            print()
            print(
                f"📖 Usage: When building a page, check design-system/{project_slug}/"
                + "pages/[page].md first.",
            )
            print(
                "   If exists, its rules override MASTER.md. Otherwise, use MASTER.md.",
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
            print(format_output(result))
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
            print(format_output(result))
