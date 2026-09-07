# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Standalone direct runner for autommit with pluggable AI providers."""

from __future__ import annotations

import argparse
import http
import json
import os
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

LIB_PATH = Path(__file__).resolve().parent.parent / "lib"
if str(LIB_PATH) not in sys.path:
    sys.path.insert(0, str(LIB_PATH))

# ruff: noqa: E402
from autommit.errors import AutommitError
from autommit.service import apply, prepare, validate_plan


@dataclass(frozen=True, slots=True)
class ParsedModel:
    """Parsed model specification matching OMP / Pi notation (<provider>/<model>:<effort>)."""

    provider: str | None
    model_id: str
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None


def parse_model_string(raw: str) -> ParsedModel:
    """Parse <provider>/<model>:<effort> format."""
    trimmed = raw.strip()
    provider: str | None = None
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None

    if "/" in trimmed:
        provider, rest = trimmed.split("/", 1)
    else:
        rest = trimmed

    if ":" in rest:
        model_id, effort_str = rest.rsplit(":", 1)
        if effort_str in ("low", "medium", "high", "xhigh", "max"):
            effort = effort_str
        else:
            model_id = rest
    else:
        model_id = rest

    return ParsedModel(provider=provider, model_id=model_id, effort=effort)


PLAN_SYSTEM_PROMPT = """You are an expert Git commit planner. Given a Git diff, output ONLY a valid JSON object matching this exact schema:
{
  "commits": [
    {
      "summary": "<type>(<scope>): <subject>",
      "details": ["<optional point 1>", "<optional point 2>"],
      "changes": [
        {
          "path": "<relative file path>",
          "hunks": "all" | {"indices": [1, 2]} | {"start": 10, "end": 25}
        }
      ]
    }
  ]
}

Rules:
1. Read the REPOSITORY POLICY and RECENT COMMITS carefully. Match the repository's commit conventions (e.g. `skills(<skill>): ...`, `<harness>: ...`, `docs: ...`, or specific prefixes). Do not use generic conventional commits like `feat(...)` or `fix(...)` unless explicitly requested by the repo policy.
2. Every staged file and every staged hunk MUST be covered exactly once across all commits.
3. Hunk indices in {"indices": [...]} are 1-based (index 1 is the first hunk). Never use 0.
4. Group related changes into the smallest independently-revertible atomic commits.
5. If multiple changes belong to distinct features or concerns, split them into separate commits.
6. Output ONLY valid JSON. Do not include markdown formatting, backticks, or any explanatory text."""


CRITIC_SYSTEM_PROMPT = """You are an independent atomicity critic. Review a single-commit proposal for an unattended commit workflow.

An atomic commit expresses exactly one independently-revertible change with all necessary implementation, tests, and metadata.
Reject the proposal and choose "split" when:
- Multiple independent behaviors, bug fixes, or features are bundled together.
- Unrelated files, docs, or configs are lumped into the same commit.

Output ONLY a JSON object matching this exact schema:
{
  "decision": "accept" | "split",
  "concerns": ["<concern 1>", "<concern 2>"],
  "rationale": "<brief explanation>"
}"""


KNOWN_CA_LOCATIONS: tuple[str, ...] = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/ca-bundle.pem",
    "/etc/ssl/cert.pem",
)


def _create_secure_ssl_context() -> ssl.SSLContext:
    """Create an SSL context with resilient CA bundle resolution across Linux distros and macOS."""
    ctx = ssl.create_default_context()
    for ca_path in KNOWN_CA_LOCATIONS:
        try:
            ctx.load_verify_locations(ca_path)
            break
        except OSError:
            pass
    return ctx


@dataclass(frozen=True, slots=True)
class PlanRequest:
    """Input payload for generating an atomic commit plan."""

    diff: str
    staged_files: Sequence[str]
    repository_context: str
    user_context: Sequence[str]
    model: ParsedModel
    api_key: str
    forced_split_context: str | None = None


@dataclass(frozen=True, slots=True)
class ApiCallOptions:
    """Network call options for OpenCode API."""

    endpoint: str
    headers: dict[str, str]
    payload: dict[str, object]
    timeout: float
    is_go: bool
    max_retries: int = 3


def _call_opencode_api(options: ApiCallOptions) -> str:
    ssl_context = _create_secure_ssl_context()
    last_error: Exception | None = None

    for attempt in range(options.max_retries):
        req = urllib.request.Request(  # noqa: S310
            options.endpoint,
            data=json.dumps(options.payload).encode("utf-8"),
            headers=options.headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310
                req, timeout=options.timeout, context=ssl_context
            ) as response:
                if response.status != http.HTTPStatus.OK:
                    raise AutommitError(
                        "provider_error",
                        f"OpenCode API returned status {response.status}",
                        exit_code=1,
                    )
                raw_data = response.read().decode("utf-8")
                break
        except urllib.error.HTTPError as err:
            if (
                err.code == http.HTTPStatus.TOO_MANY_REQUESTS
                and attempt < options.max_retries - 1
            ):
                # Exponential backoff on rate limit (1.5s, 3.0s)
                time.sleep(1.5 * (2**attempt))
                last_error = err
                continue
            err_body = err.read().decode("utf-8", "replace")
            raise AutommitError(
                "provider_error",
                f"OpenCode API error ({err.code}): {err_body}",
                exit_code=1,
            ) from err
        except TimeoutError as err:
            raise AutommitError(
                "network_timeout",
                f"OpenCode API timed out after {options.timeout}s. Retry with a higher --timeout or a faster model.",
                exit_code=1,
            ) from err
        except OSError as err:
            raise AutommitError(
                "network_error",
                f"Failed to connect to OpenCode API: {err}",
                exit_code=1,
            ) from err
    else:
        raise AutommitError(
            "rate_limit_exceeded",
            f"OpenCode API rate limit exceeded after {options.max_retries} attempts: {last_error}",
            exit_code=1,
        )
    data = json.loads(raw_data)
    if options.is_go:
        content_parts: list[str] = []
        for item in data.get("output", []):
            if isinstance(item, dict) and item.get("type") == "message":
                for block in item.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "output_text":
                        content_parts.append(str(block.get("text", "")))
        content = "".join(content_parts)
    else:
        content = data["choices"][0]["message"]["content"]

    if not isinstance(content, str) or not content.strip():
        raise AutommitError("provider_error", "Empty completion from provider.")
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    return json.loads(cleaned)


def build_parser() -> argparse.ArgumentParser:
    """Build the direct runner command-line parser."""
    parser = argparse.ArgumentParser(
        prog="autommit-run",
        description="Direct headless commit runner with pluggable AI providers.",
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--scope", choices=["staged", "all"], default="all", type=str)
    parser.add_argument(
        "--ogo",
        action="store_true",
        help="Use OpenCode Go provider (reads OPENCODE_API_KEY).",
    )
    parser.add_argument(
        "--ozen",
        action="store_true",
        help="Use OpenCode Zen keyless/free tier (Bearer public).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model string in <provider>/<model>:<effort> format (e.g. ogo/muse-spark-1.3-contributor, ozen/big-pickle).",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Explicit API key (overrides OPENCODE_API_KEY environment variable).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Inference HTTP timeout in seconds (default: 300.0).",
    )
    parser.add_argument("--context", action="append", default=[])
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    """Execute the end-to-end direct autommit workflow."""
    parser = build_parser()
    args = parser.parse_args(argv)
    repo: Path = args.repo.resolve()

    # Determine default model and provider flags
    raw_model = args.model
    if not raw_model:
        raw_model = "muse-spark-1.3-contributor" if args.ogo else "big-pickle"

    parsed_model = parse_model_string(raw_model)

    # Determine provider & API key
    is_ozen = args.ozen or parsed_model.provider in ("ozen", "zen", "free")
    is_ogo = args.ogo or parsed_model.provider in ("ogo", "opencode", "opencode-go")

    if is_ozen:
        api_key = "public"
    elif args.api_key:
        api_key = args.api_key
    elif is_ogo:
        api_key = os.environ.get("OPENCODE_API_KEY")
        if not api_key:
            sys.stderr.write(
                "Error: --ogo requires OPENCODE_API_KEY in environment or via --api-key.\n"
            )
            return 2
    else:
        api_key = os.environ.get("OPENCODE_API_KEY", "public")

    # Step 1: Prepare
    sys.stdout.write(f"Preparing diff in {repo}...\n")
    prep = prepare(repo, tuple(args.context), scope=args.scope)
    snapshot = str(prep["snapshot"])
    diff = str(prep["diff"])
    staged_files = cast("list[str]", prep["staged_files"])
    hunk_count = prep["changed_hunk_count"]
    sys.stdout.write(
        f"Staged {len(staged_files)} file(s), {hunk_count} hunk(s) (snapshot {snapshot[:8]})\n"
    )

    # Step 2: Inference
    model_display = f"{parsed_model.model_id}" + (
        f":{parsed_model.effort}" if parsed_model.effort else ""
    )
    provider_name = (
        "OpenCode Go (Contributor)"
        if "contributor" in parsed_model.model_id
        else "OpenCode Zen (Keyless)"
        if api_key == "public"
        else "OpenCode Go"
    )
    sys.stdout.write(
        f"Generating split plan via {provider_name} ({model_display})...\n"
    )
    plan_obj = generate_plan_opencode(
        diff, staged_files, parsed_model, api_key, timeout=args.timeout
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as temp_plan:
        temp_plan.write(json.dumps(plan_obj, indent=2))
        plan_path = Path(temp_plan.name)

    try:
        # Step 3: Validate plan
        sys.stdout.write("Validating atomic plan...\n")
        val = validate_plan(repo, snapshot, plan_path)
        commit_count = val["commit_count"]
        sys.stdout.write(f"Plan validated: {commit_count} commit(s) planned.\n")

        # Step 4: Apply
        sys.stdout.write("Applying atomic commits to Git...\n")
        result = apply(repo, snapshot, plan_path, decision_file=None)
        commits = cast("list[dict[str, str]]", result.get("commits", []))
        sys.stdout.write(f"Successfully published {len(commits)} commit(s):\n")
        for c in commits:
            sys.stdout.write(f"  {c['sha'][:7]} {c['summary']}\n")
        return 0
    finally:
        plan_path.unlink(missing_ok=True)
