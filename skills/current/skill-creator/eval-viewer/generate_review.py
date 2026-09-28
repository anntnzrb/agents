#!/usr/bin/env -S uv run --script
# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Generate and serve a review page for eval results.

Reads the workspace directory, discovers runs (directories with outputs/),
embeds all output data into a self-contained HTML page, and serves it via
a tiny HTTP server. Feedback auto-saves to feedback.json in the workspace.

Usage:
    python generate_review.py <workspace-path> [--port PORT]
        [--skill-name NAME]
    python generate_review.py <workspace-path>
        --previous-feedback /path/to/old/feedback.json

No dependencies beyond the Python stdlib are required.
"""

import argparse
import base64
import contextlib
import json
import mimetypes
import os
import re
import signal
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Final, TypeIs, override

if TYPE_CHECKING:
    import socket
    import socketserver
    from collections.abc import Callable

# Files to exclude from output listings
METADATA_FILES: Final[set[str]] = {"transcript.md", "user_notes.md", "metrics.json"}

# Extensions we render as inline text
TEXT_EXTENSIONS: Final[set[str]] = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".css",
    ".sh",
    ".rb",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".sql",
    ".r",
    ".toml",
}

# Extensions we render as inline images
IMAGE_EXTENSIONS: Final[set[str]] = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}

# MIME type overrides for common types
MIME_OVERRIDES: Final[dict[str, str]] = {
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
}


def _parse_json(text: str | bytes) -> object:
    fn: Callable[..., object] = json.loads
    return fn(text)


def _is_str_dict(val: object) -> TypeIs[dict[str, object]]:
    return isinstance(val, dict)


def _is_object_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


def get_mime_type(path: Path) -> str:
    """Determine MIME type for a file path, checking overrides first."""
    ext = path.suffix.lower()
    if ext in MIME_OVERRIDES:
        return MIME_OVERRIDES[ext]
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def _sort_runs_key(r: dict[str, object]) -> tuple[float, str]:
    raw_eval_id = r.get("eval_id")
    numeric_id = (
        float(raw_eval_id) if isinstance(raw_eval_id, (int, float)) else float("inf")
    )
    raw_id = r.get("id")
    str_id = str(raw_id) if raw_id is not None else ""
    return numeric_id, str_id


def find_runs(workspace: Path) -> list[dict[str, object]]:
    """Recursively find directories that contain an outputs/ subdirectory."""
    runs: list[dict[str, object]] = []
    _find_runs_recursive(workspace, workspace, runs)
    runs.sort(key=_sort_runs_key)
    return runs


def _find_runs_recursive(
    root: Path, current: Path, runs: list[dict[str, object]]
) -> None:
    if not current.is_dir():
        return

    outputs_dir = current / "outputs"
    if outputs_dir.is_dir():
        run = build_run(root, current)
        if run:
            runs.append(run)
        return

    skip = {"node_modules", ".git", "__pycache__", "skill", "inputs"}
    for child in sorted(current.iterdir()):
        if child.is_dir() and child.name not in skip:
            _find_runs_recursive(root, child, runs)


def _read_eval_metadata(run_dir: Path) -> tuple[str, object | None]:
    """Extract (prompt, eval_id) from eval_metadata.json when present."""
    for candidate in [
        run_dir / "eval_metadata.json",
        run_dir.parent / "eval_metadata.json",
    ]:
        if candidate.exists():
            with contextlib.suppress(json.JSONDecodeError, OSError):
                raw = _parse_json(candidate.read_text(encoding="utf-8"))
                if _is_str_dict(raw):
                    prompt = str(raw.get("prompt", ""))
                    eval_id = raw.get("eval_id")
                    if prompt:
                        return prompt, eval_id
    return "", None


def _read_transcript_prompt(run_dir: Path) -> str:
    """Extract the eval prompt from transcript.md when present."""
    for candidate in [
        run_dir / "transcript.md",
        run_dir / "outputs" / "transcript.md",
    ]:
        if candidate.exists():
            with contextlib.suppress(OSError):
                text = candidate.read_text(encoding="utf-8")
                match = re.search(r"## Eval Prompt\n\n([\s\S]*?)(?=\n##|$)", text)
                if match:
                    return match.group(1).strip()
    return ""


def _read_grading(run_dir: Path) -> dict[str, object] | None:
    """Read grading.json from the run or its parent directory."""
    for candidate in [run_dir / "grading.json", run_dir.parent / "grading.json"]:
        if candidate.exists():
            with contextlib.suppress(json.JSONDecodeError, OSError):
                raw = _parse_json(candidate.read_text(encoding="utf-8"))
                if _is_str_dict(raw):
                    return dict(raw)
    return None


def _collect_outputs(run_dir: Path) -> list[dict[str, object]]:
    """Collect and embed all non-metadata outputs from the run."""
    outputs_dir = run_dir / "outputs"
    if not outputs_dir.is_dir():
        return []
    return [
        embed_file(f)
        for f in sorted(outputs_dir.iterdir())
        if f.is_file() and f.name not in METADATA_FILES
    ]


def build_run(root: Path, run_dir: Path) -> dict[str, object] | None:
    """Build a run dict with prompt, outputs, and grading data."""
    prompt, eval_id = _read_eval_metadata(run_dir)
    if not prompt:
        prompt = _read_transcript_prompt(run_dir)
    if not prompt:
        prompt = "(No prompt found)"
    run_id = str(run_dir.relative_to(root)).replace("/", "-").replace("\\", "-")
    return {
        "id": run_id,
        "prompt": prompt,
        "eval_id": eval_id,
        "outputs": _collect_outputs(run_dir),
        "grading": _read_grading(run_dir),
    }


def embed_file(path: Path) -> dict[str, object]:
    """Read a file and return an embedded representation."""
    ext = path.suffix.lower()
    mime = get_mime_type(path)

    if ext in TEXT_EXTENSIONS:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = "(Error reading file)"
        return {
            "name": path.name,
            "type": "text",
            "content": content,
        }
    if ext in IMAGE_EXTENSIONS:
        try:
            raw = path.read_bytes()
            b64 = base64.b64encode(raw).decode("ascii")
        except OSError:
            return {
                "name": path.name,
                "type": "error",
                "content": "(Error reading file)",
            }
        return {
            "name": path.name,
            "type": "image",
            "mime": mime,
            "data_uri": f"data:{mime};base64,{b64}",
        }
    if ext == ".pdf":
        try:
            raw = path.read_bytes()
            b64 = base64.b64encode(raw).decode("ascii")
        except OSError:
            return {
                "name": path.name,
                "type": "error",
                "content": "(Error reading file)",
            }
        return {
            "name": path.name,
            "type": "pdf",
            "data_uri": f"data:{mime};base64,{b64}",
        }
    if ext == ".xlsx":
        try:
            raw = path.read_bytes()
            b64 = base64.b64encode(raw).decode("ascii")
        except OSError:
            return {
                "name": path.name,
                "type": "error",
                "content": "(Error reading file)",
            }
        return {
            "name": path.name,
            "type": "xlsx",
            "data_b64": b64,
        }
    # Binary / unknown - base64 download link
    try:
        raw = path.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
    except OSError:
        return {
            "name": path.name,
            "type": "error",
            "content": "(Error reading file)",
        }
    return {
        "name": path.name,
        "type": "binary",
        "mime": mime,
        "data_uri": f"data:{mime};base64,{b64}",
    }


def _extract_feedback_map(feedback_path: Path) -> dict[str, str]:
    """Extract map of run_id to feedback text from feedback.json."""
    if not feedback_path.exists():
        return {}
    try:
        raw = _parse_json(feedback_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError, OSError:
        return {}
    if not _is_str_dict(raw):
        return {}
    reviews = raw.get("reviews")
    if not _is_object_list(reviews):
        return {}
    feedback_map: dict[str, str] = {}
    for r in reviews:
        if _is_str_dict(r):
            run_id = r.get("run_id")
            fb = r.get("feedback")
            if isinstance(run_id, str) and isinstance(fb, str) and fb.strip():
                feedback_map[run_id] = fb.strip()
    return feedback_map


def load_previous_iteration(workspace: Path) -> dict[str, dict[str, object]]:
    """Load previous iteration's feedback and outputs."""
    result: dict[str, dict[str, object]] = {}
    feedback_map = _extract_feedback_map(workspace / "feedback.json")

    for run in find_runs(workspace):
        run_id_obj = run.get("id")
        if isinstance(run_id_obj, str):
            outputs_obj = run.get("outputs")
            outputs_list = outputs_obj if _is_object_list(outputs_obj) else []
            result[run_id_obj] = {
                "feedback": feedback_map.get(run_id_obj, ""),
                "outputs": outputs_list,
            }

    for run_id, fb in feedback_map.items():
        if run_id not in result:
            result[run_id] = {"feedback": fb, "outputs": []}

    return result


def generate_html(
    runs: list[dict[str, object]],
    skill_name: str,
    previous: dict[str, dict[str, object]] | None = None,
    benchmark: dict[str, object] | None = None,
) -> str:
    """Generate the complete standalone HTML page with embedded data."""
    template_path = Path(__file__).parent / "viewer.html"
    template = template_path.read_text(encoding="utf-8")

    # Build previous_feedback and previous_outputs maps for the template
    previous_feedback: dict[str, str] = {}
    previous_outputs: dict[str, list[object]] = {}
    if previous:
        for run_id, data in previous.items():
            fb = data.get("feedback")
            if isinstance(fb, str) and fb:
                previous_feedback[run_id] = fb
            outputs = data.get("outputs")
            if isinstance(outputs, list) and outputs:
                previous_outputs[run_id] = outputs

    embedded: dict[str, object] = {
        "skill_name": skill_name,
        "runs": runs,
        "previous_feedback": previous_feedback,
        "previous_outputs": previous_outputs,
    }
    if benchmark:
        embedded["benchmark"] = benchmark

    data_json = json.dumps(embedded)

    return template.replace(
        "/*__EMBEDDED_DATA__*/",
        f"const EMBEDDED_DATA = {data_json};",
    )


# ---------------------------------------------------------------------------
# HTTP server (stdlib only, zero dependencies)
# ---------------------------------------------------------------------------


def _kill_port(port: int) -> None:
    """Kill any process listening on the given port."""
    try:
        # Fixed argv, no shell: checking local port usage via system lsof.
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        for pid_str in result.stdout.strip().split("\n"):
            if pid_str.strip():
                with contextlib.suppress(ProcessLookupError, ValueError):
                    os.kill(int(pid_str.strip()), signal.SIGTERM)
        if result.stdout.strip():
            time.sleep(0.5)
    except subprocess.TimeoutExpired:
        pass
    except FileNotFoundError:
        print(
            "Note: lsof not found, cannot check if port is in use",
            file=sys.stderr,
        )


@dataclass(frozen=True, slots=True)
class ServerConfig:
    """Configuration for running the review HTTP server."""

    workspace: Path
    skill_name: str
    feedback_path: Path
    previous: dict[str, dict[str, object]]
    previous_workspace: Path | None
    benchmark_path: Path | None
    port: int


class ReviewHandler(BaseHTTPRequestHandler):
    """Serves the review HTML and handles feedback saves."""

    config: ServerConfig

    def __init__(
        self,
        config: ServerConfig,
        request: socket.socket | tuple[bytes, socket.socket],
        client_address: tuple[str, int] | str,
        server: socketserver.BaseServer,
    ) -> None:
        """Initialize review handler with server config."""
        self.config = config
        super().__init__(request, client_address, server)

    def do_GET(self) -> None:
        """Handle GET requests for HTML and feedback data."""
        if self.path in {"/", "/index.html"}:
            # Regenerate HTML on each request (re-scans workspace for new outputs)
            runs = find_runs(self.config.workspace)
            benchmark: dict[str, object] | None = None
            if self.config.benchmark_path and self.config.benchmark_path.exists():
                with contextlib.suppress(json.JSONDecodeError, OSError):
                    raw_bm = _parse_json(
                        self.config.benchmark_path.read_text(encoding="utf-8")
                    )
                    if _is_str_dict(raw_bm):
                        benchmark = dict(raw_bm)
            html = generate_html(
                runs,
                self.config.skill_name,
                self.config.previous,
                benchmark,
            )
            content = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            _ = self.wfile.write(content)
        elif self.path == "/api/feedback":
            data = b"{}"
            if self.config.feedback_path.exists():
                data = self.config.feedback_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            _ = self.wfile.write(data)
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        """Handle POST feedback updates from the viewer."""
        if self.path != "/api/feedback":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = _parse_json(body)
            if not _is_str_dict(data) or "reviews" not in data:
                msg = "Expected JSON object with 'reviews' key"
                raise ValueError(msg)
            _ = self.config.feedback_path.write_text(
                json.dumps(data, indent=2) + "\n", encoding="utf-8"
            )
            resp = b'{"ok":true}'
            self.send_response(200)
        except (json.JSONDecodeError, OSError, ValueError) as e:
            resp = json.dumps({"error": str(e)}).encode()
            self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        _ = self.wfile.write(resp)

    @override
    def log_message(self, format: str, *args: object) -> None:
        """Suppress request logging to keep terminal clean."""


def _print_server_banner(url: str, config: ServerConfig) -> None:
    """Print the startup banner for the review HTTP server."""
    print("\n  Eval Viewer")
    print("  ─────────────────────────────────")
    print(f"  URL:       {url}")
    print(f"  Workspace: {config.workspace}")
    print(f"  Feedback:  {config.feedback_path}")
    if config.previous_workspace:
        count = len(config.previous)
        print(f"  Previous:  {config.previous_workspace} ({count} runs)")
    if config.benchmark_path:
        print(f"  Benchmark: {config.benchmark_path}")
    print("\n  Press Ctrl+C to stop.\n")


def _serve(config: ServerConfig) -> None:
    """Start the review HTTP server and open the browser."""
    _kill_port(config.port)
    handler = partial(ReviewHandler, config)
    try:
        server = HTTPServer(("127.0.0.1", config.port), handler)
    except OSError:
        # Port still in use after kill attempt - find a free one
        server = HTTPServer(("127.0.0.1", 0), handler)
        config = ServerConfig(
            workspace=config.workspace,
            skill_name=config.skill_name,
            feedback_path=config.feedback_path,
            previous=config.previous,
            previous_workspace=config.previous_workspace,
            benchmark_path=config.benchmark_path,
            port=server.server_address[1],
        )

    url = f"http://localhost:{config.port}"
    _print_server_banner(url, config)
    _ = webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


def main() -> None:
    """Generate and serve the review page, or write standalone HTML."""
    parser = argparse.ArgumentParser(description="Generate and serve eval review")
    _ = parser.add_argument("workspace", type=Path, help="Path to workspace directory")
    _ = parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=3117,
        help="Server port (default: 3117)",
    )
    _ = parser.add_argument(
        "--skill-name",
        "-n",
        type=str,
        default=None,
        help="Skill name for header",
    )
    _ = parser.add_argument(
        "--previous-workspace",
        type=Path,
        default=None,
        help=(
            "Path to previous iteration's workspace"
            " (shows old outputs and feedback as context)"
        ),
    )
    _ = parser.add_argument(
        "--benchmark",
        type=Path,
        default=None,
        help="Path to benchmark.json to show in the Benchmark tab",
    )
    _ = parser.add_argument(
        "--static",
        "-s",
        type=Path,
        default=None,
        help="Write standalone HTML to this path instead of starting a server",
    )
    ns = parser.parse_args()

    raw_workspace = getattr(ns, "workspace", None)
    if not isinstance(raw_workspace, Path):
        print("Error: missing workspace directory", file=sys.stderr)
        sys.exit(1)
    workspace = raw_workspace.resolve()
    if not workspace.is_dir():
        print(f"Error: {workspace} is not a directory", file=sys.stderr)
        sys.exit(1)

    runs = find_runs(workspace)
    if not runs:
        print(f"No runs found in {workspace}", file=sys.stderr)
        sys.exit(1)

    raw_skill_name = getattr(ns, "skill_name", None)
    skill_name = (
        str(raw_skill_name)
        if isinstance(raw_skill_name, str)
        else workspace.name.replace("-workspace", "")
    )
    feedback_path = workspace / "feedback.json"

    previous: dict[str, dict[str, object]] = {}
    prev_ws = getattr(ns, "previous_workspace", None)
    if isinstance(prev_ws, Path):
        previous = load_previous_iteration(prev_ws.resolve())

    bm_path = getattr(ns, "benchmark", None)
    benchmark_path = bm_path.resolve() if isinstance(bm_path, Path) else None
    benchmark: dict[str, object] | None = None
    if benchmark_path and benchmark_path.exists():
        with contextlib.suppress(json.JSONDecodeError, OSError):
            raw_data = _parse_json(benchmark_path.read_text(encoding="utf-8"))
            if _is_str_dict(raw_data):
                benchmark = dict(raw_data)

    static_path = getattr(ns, "static", None)
    if isinstance(static_path, Path):
        html = generate_html(runs, skill_name, previous, benchmark)
        static_path.parent.mkdir(parents=True, exist_ok=True)
        _ = static_path.write_text(html, encoding="utf-8")
        print(f"\n  Static viewer written to: {static_path}\n")
        sys.exit(0)

    raw_port = getattr(ns, "port", 3117)
    port = int(raw_port) if isinstance(raw_port, int) else 3117
    _serve(
        ServerConfig(
            workspace=workspace,
            skill_name=skill_name,
            feedback_path=feedback_path,
            previous=previous,
            previous_workspace=prev_ws if isinstance(prev_ws, Path) else None,
            benchmark_path=benchmark_path,
            port=port,
        )
    )


if __name__ == "__main__":
    main()
