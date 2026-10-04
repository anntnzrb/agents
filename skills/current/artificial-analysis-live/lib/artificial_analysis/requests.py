"""One option contract for argparse, RPC decoding, and capability schemas."""

import argparse
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_ARTIFACT_DIR = Path(tempfile.gettempdir()) / "artifacts" / "artificial-analysis"
DEFAULT_OUTPUT_JSON = DEFAULT_ARTIFACT_DIR / "full-data.json"
DEFAULT_OUTPUT_ENDPOINTS = DEFAULT_ARTIFACT_DIR / "endpoints.txt"
DEFAULT_OUTPUT_URL = DEFAULT_ARTIFACT_DIR / "full-url.txt"


def default_cache_dir() -> Path:
    """Resolve the conditional-request cache using the existing environment policy."""
    configured = os.environ.get("XDG_CACHE_HOME")
    return (
        Path(configured) if configured else Path.home() / ".cache"
    ) / "artificial-analysis"


@dataclass(frozen=True, slots=True)
class Option:
    """Transport-independent option conversion, choices, default, and help."""

    name: str
    convert: Callable[[str], object]
    default: object
    description: str
    choices: tuple[str, ...] | None = None
    action: str | None = None
    help: str | None = None

    def add(self, parser: argparse.ArgumentParser) -> None:
        """Publish the contract through argparse."""
        if self.action is not None:
            _ = parser.add_argument(
                "--" + self.name.replace("_", "-"),
                action=self.action,
                default=self.default,
                help=self.help,
            )
        else:
            _ = parser.add_argument(
                "--" + self.name.replace("_", "-"),
                type=self.convert,
                choices=self.choices,
                default=self.default,
                help=self.help,
            )

    def decode(self, args: dict[str, object]) -> object:
        """Apply the CLI conversion and choice checks to an RPC value."""
        camel = "".join(
            part.capitalize() if index else part
            for index, part in enumerate(self.name.split("_"))
        )
        value = args.get(self.name, args.get(camel))
        if value is None:
            return self.default
        if self.action == "store_true":
            if not isinstance(value, bool):
                raise TypeError(f"invalid {self.name}")
            return value
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Path)):
            raise TypeError(f"invalid {self.name}")
        converted = self.convert(str(value))
        if self.choices is not None and converted not in self.choices:
            raise ValueError(f"invalid {self.name}: {value}")
        return converted


FETCH_OPTIONS = (
    Option(
        "output_json",
        Path,
        DEFAULT_OUTPUT_JSON,
        "Path (default <temp-dir>/artifacts/artificial-analysis/full-data.json)",
    ),
    Option(
        "output_endpoints",
        Path,
        DEFAULT_OUTPUT_ENDPOINTS,
        "Path (default <temp-dir>/artifacts/artificial-analysis/endpoints.txt)",
    ),
    Option(
        "output_url",
        Path,
        DEFAULT_OUTPUT_URL,
        "Path (default <temp-dir>/artifacts/artificial-analysis/full-url.txt)",
    ),
    Option("timeout_seconds", float, 60.0, "float network timeout"),
    Option("min_endpoints", int, 700, "int sanity threshold (default {default})"),
    Option("min_providers", int, 40, "int sanity threshold (default {default})"),
    Option(
        "stale_policy",
        str,
        "error",
        "{choices} (default {default})",
        ("error", "allow-last-good"),
        help="Refresh failure policy; stale fallback is opt-in.",
    ),
    Option(
        name="allow_stale",
        convert=str,
        default=False,
        description="bool alias for stale_policy allow-last-good",
        action="store_true",
        help="Alias for --stale-policy allow-last-good.",
    ),
    Option(
        name="strict",
        convert=str,
        default=False,
        description="bool alias for stale_policy error",
        action="store_true",
        help="Alias for --stale-policy error.",
    ),
)
STATS_OPTIONS = (Option("top", int, 10, "int top N providers (default {default})"),)
QUERY_OPTIONS = (
    Option(
        "model",
        str,
        None,
        "str contains filter on model slug/name",
        help="Model slug/name contains filter.",
    ),
    Option(
        "provider",
        str,
        None,
        "str contains filter on provider slug/name",
        help="Provider slug/name contains filter.",
    ),
    Option(
        "endpoint",
        str,
        None,
        "str contains filter on endpoint slug",
        help="Endpoint slug contains filter.",
    ),
    Option(
        "sort_by",
        str,
        "intelligence",
        "{choices}",
        (
            "intelligence",
            "agentic",
            "coding",
            "math",
            "price_blended",
            "speed",
            "ttfc",
            "e2e",
        ),
    ),
    Option("order", str, "auto", "{choices}", ("auto", "asc", "desc")),
    Option("limit", int, 20, "int max rows (default {default})"),
)
EVALUATION_OPTIONS = (
    Option(
        "input",
        Path,
        None,
        "Path to saved HTML/RSC response",
        help="read a saved HTML/RSC response instead of fetching a URL",
    ),
    Option("output_json", Path, None, "Optional path for the full extracted row set"),
    FETCH_OPTIONS[3],
    Option("min_rows", int, 1, "minimum recognizable rows (default {default})"),
    Option("sort_by", str, None, "optional dotted numeric field path"),
    QUERY_OPTIONS[4],
    Option("limit", int, None, "optional maximum returned rows"),
)
QA_OPTIONS = (
    replace(
        QUERY_OPTIONS[0],
        description="override inferred model",
        help="Override inferred model filter.",
    ),
    replace(
        QUERY_OPTIONS[1],
        description="override inferred provider",
        help="Override inferred provider filter.",
    ),
    replace(QUERY_OPTIONS[3], default=None, description="override inferred metric"),
    replace(
        QUERY_OPTIONS[4],
        default=None,
        description="override inferred order",
        choices=("asc", "desc"),
        help="Override inferred order.",
    ),
    replace(
        QUERY_OPTIONS[5],
        default=None,
        description="override inferred limit",
        help="Override inferred result limit.",
    ),
)


def fetch_options() -> tuple[Option, ...]:
    """Resolve the environment-dependent default at request construction time."""
    return (
        *FETCH_OPTIONS[:3],
        Option(
            "cache_dir",
            Path,
            default_cache_dir(),
            "Path to ETag/Last-Modified/payload cache",
        ),
        *FETCH_OPTIONS[3:],
    )


def decode_options(
    options: tuple[Option, ...], args: dict[str, object]
) -> dict[str, object]:
    """Decode a request using the same options used to construct its parser."""
    return {option.name: option.decode(args) for option in options}


def schema_options(options: tuple[Option, ...]) -> dict[str, str]:
    """Project the public descriptions from the request definition."""
    return {
        option.name: option.description.format(
            default=option.default, choices="|".join(option.choices or ())
        )
        for option in options
    }
