#!/usr/bin/env -S uv run --script
# ruff: noqa: T201
"""Generate and serve a review page for eval results.

Reads the workspace directory, discovers runs (directories with outputs/),
embeds all output data into a self-contained HTML page, and serves it via
a tiny HTTP server. Feedback auto-saves to feedback.json in the workspace.

Usage:
    python generate_review.py <workspace-path> [--port PORT] [--skill-name NAME]
    python generate_review.py <workspace-path> \
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
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socket import socket
from socketserver import BaseServer
from typing import cast, override

# Files to exclude from output listings
METADATA_FILES = {"transcript.md", "user_notes.md", "metrics.json"}

# Extensions we render as inline text
TEXT_EXTENSIONS = {
    ".c",
    ".cpp",
    ".css",
    ".csv",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".py",
    ".r",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

# Extensions we render as inline images
IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}

# MIME type overrides for common types
MIME_OVERRIDES = {
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    ".svg": "image/svg+xml",
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
}

DEFAULT_PORT = 3117

type RunDict = dict[str, object]
type FileEmbed = dict[str, object]


def _safe_dict(val: object) -> dict[str, object]:
    """Extract dict safely from an untyped object."""
    if isinstance(val, dict):
        return cast("dict[str, object]", val)
    return {}


def _safe_list(val: object) -> list[object]:
    """Extract list safely from an untyped object."""
    if isinstance(val, list):
        return cast("list[object]", val)
    return []


def _safe_int(val: object, default: int = 0) -> int:
    """Extract int safely from an untyped object."""
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    return default


def get_mime_type(path: Path) -> str:
    """Determine the MIME type for a file path."""
    ext = path.suffix.lower()
    if ext in MIME_OVERRIDES:
        return MIME_OVERRIDES[ext]
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def find_runs(workspace: Path) -> list[RunDict]:
    """Recursively find directories that contain an outputs/ subdirectory."""
    runs: list[RunDict] = []
    _find_runs_recursive(workspace, workspace, runs)
    runs.sort(
        key=lambda r: (
            _safe_int(r.get("eval_id"), int(1e9)),
            str(r.get("id", "")),
        ),
    )
    return runs


def _find_runs_recursive(root: Path, current: Path, runs: list[RunDict]) -> None:
    """Recursively traverse directory tree to discover run directories."""
    if not current.is_dir():
        return

    outputs_dir = current / "outputs"
    if outputs_dir.is_dir():
        run = build_run(root, current)
        if run:
            runs.append(run)
        return

    skip = {".git", "__pycache__", "inputs", "node_modules", "skill"}
    for child in sorted(current.iterdir()):
        if child.is_dir() and child.name not in skip:
            _find_runs_recursive(root, child, runs)


def _find_prompt_and_eval_id(run_dir: Path) -> tuple[str, int | None]:
    """Extract prompt text and optional eval ID from metadata or transcript."""
    prompt = ""
    eval_id: int | None = None

    for candidate in [
        run_dir / "eval_metadata.json",
        run_dir.parent / "eval_metadata.json",
    ]:
        if candidate.exists():
            with contextlib.suppress(
                json.JSONDecodeError, OSError, TypeError, ValueError
            ):
                meta_raw = cast(
                    "object",
                    json.loads(candidate.read_text(encoding="utf-8")),
                )
                if isinstance(meta_raw, dict):
                    meta_dict = cast("dict[str, object]", meta_raw)
                    prompt = str(meta_dict.get("prompt", ""))
                    if "eval_id" in meta_dict and meta_dict["eval_id"] is not None:
                        eval_id = int(cast("int | float", meta_dict["eval_id"]))
            if prompt:
                return prompt, eval_id

    for candidate in [
        run_dir / "transcript.md",
        run_dir / "outputs" / "transcript.md",
    ]:
        if candidate.exists():
            with contextlib.suppress(OSError):
                text = candidate.read_text(encoding="utf-8")
                match = re.search(r"## Eval Prompt\n\n([\s\S]*?)(?=\n##|$)", text)
                if match:
                    prompt = match.group(1).strip()
            if prompt:
                return prompt, eval_id

    return prompt or "(No prompt found)", eval_id


def _load_grading(run_dir: Path) -> dict[str, object] | None:
    """Load grading.json data from run directory or its parent."""
    for candidate in [run_dir / "grading.json", run_dir.parent / "grading.json"]:
        if candidate.exists():
            with contextlib.suppress(json.JSONDecodeError, OSError):
                grading_raw = cast(
                    "object",
                    json.loads(candidate.read_text(encoding="utf-8")),
                )
                if isinstance(grading_raw, dict):
                    return cast("dict[str, object]", grading_raw)
    return None


def build_run(root: Path, run_dir: Path) -> RunDict | None:
    """Build a run dict with prompt, outputs, and grading data."""
    prompt, eval_id = _find_prompt_and_eval_id(run_dir)
    run_id = str(run_dir.relative_to(root)).replace("/", "-").replace("\\", "-")

    # Collect output files
    outputs_dir = run_dir / "outputs"
    output_files: list[FileEmbed] = []
    if outputs_dir.is_dir():
        output_files.extend(
            embed_file(f)
            for f in sorted(outputs_dir.iterdir())
            if f.is_file() and f.name not in METADATA_FILES
        )

    grading = _load_grading(run_dir)

    return {
        "id": run_id,
        "prompt": prompt,
        "eval_id": eval_id,
        "outputs": output_files,
        "grading": grading,
    }


def embed_file(path: Path) -> FileEmbed:
    """Read a file and return an embedded representation."""
    ext = path.suffix.lower()
    mime = get_mime_type(path)

    if ext in TEXT_EXTENSIONS:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = "(Error reading file)"
        return {"name": path.name, "type": "text", "content": content}

    try:
        raw = path.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
    except OSError:
        return {
            "name": path.name,
            "type": "error",
            "content": "(Error reading file)",
        }

    if ext in IMAGE_EXTENSIONS:
        return {
            "name": path.name,
            "type": "image",
            "mime": mime,
            "data_uri": f"data:{mime};base64,{b64}",
        }
    if ext == ".pdf":
        return {
            "name": path.name,
            "type": "pdf",
            "data_uri": f"data:{mime};base64,{b64}",
        }
    if ext == ".xlsx":
        return {"name": path.name, "type": "xlsx", "data_b64": b64}

    return {
        "name": path.name,
        "type": "binary",
        "mime": mime,
        "data_uri": f"data:{mime};base64,{b64}",
    }


def load_previous_iteration(workspace: Path) -> dict[str, dict[str, object]]:
    """Load previous iteration's feedback and outputs.

    Returns a map of run_id -> {"feedback": str, "outputs": list[dict]}.
    """
    result: dict[str, dict[str, object]] = {}

    # Load feedback
    feedback_map: dict[str, str] = {}
    feedback_path = workspace / "feedback.json"
    if feedback_path.exists():
        with contextlib.suppress(json.JSONDecodeError, OSError, KeyError):
            raw_data = cast(
                "object",
                json.loads(feedback_path.read_text(encoding="utf-8")),
            )
            data_dict = _safe_dict(raw_data)
            for r_obj in _safe_list(data_dict.get("reviews")):
                r = _safe_dict(r_obj)
                fb_str = str(r.get("feedback", "")).strip()
                r_id = str(r.get("run_id", ""))
                if fb_str and r_id:
                    feedback_map[r_id] = fb_str

    # Load runs (to get outputs)
    prev_runs = find_runs(workspace)
    for run in prev_runs:
        run_id_val = str(run.get("id", ""))
        result[run_id_val] = {
            "feedback": feedback_map.get(run_id_val, ""),
            "outputs": run.get("outputs", []),
        }

    # Also add feedback for run_ids that had feedback but no matching run
    for r_id_key, fb_val in feedback_map.items():
        if r_id_key not in result:
            result[r_id_key] = {"feedback": fb_val, "outputs": []}

    return result


def generate_html(
    runs: list[RunDict],
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
            if data.get("feedback"):
                previous_feedback[run_id] = str(data["feedback"])
            if data.get("outputs"):
                previous_outputs[run_id] = _safe_list(data["outputs"])

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
        result = subprocess.run(  # noqa: S603 - invoke lsof utility
            ["lsof", "-ti", f":{port}"],  # noqa: S607 - system utility
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for pid_str in result.stdout.strip().split("\n"):
            clean_pid = pid_str.strip()
            if clean_pid:
                with contextlib.suppress(ProcessLookupError, ValueError):
                    os.kill(int(clean_pid), signal.SIGTERM)
        if result.stdout.strip():
            time.sleep(0.5)
    except subprocess.TimeoutExpired:
        pass
    except FileNotFoundError:
        print("Note: lsof not found, cannot check if port is in use", file=sys.stderr)


class ReviewHandler(BaseHTTPRequestHandler):
    """Serves the review HTML and handles feedback saves.

    Regenerates the HTML on each page load so that refreshing the browser
    picks up new eval outputs without restarting the server.
    """

    workspace: Path
    skill_name: str
    feedback_path: Path
    previous: dict[str, dict[str, object]]
    benchmark_path: Path | None

    def __init__(  # noqa: PLR0913, PLR0917 - HTTP handler initialized via partial
        self,
        workspace: Path,
        skill_name: str,
        feedback_path: Path,
        previous: dict[str, dict[str, object]],
        benchmark_path: Path | None,
        request: socket | tuple[bytes, socket],
        client_address: tuple[str, int] | str,
        server: BaseServer,
    ) -> None:
        """Initialize handler with workspace context and paths."""
        self.workspace = workspace
        self.skill_name = skill_name
        self.feedback_path = feedback_path
        self.previous = previous
        self.benchmark_path = benchmark_path
        super().__init__(request, client_address, server)

    def _serve_index(self) -> None:
        """Generate and serve review HTML page."""
        runs = find_runs(self.workspace)
        benchmark: dict[str, object] | None = None
        if self.benchmark_path and self.benchmark_path.exists():
            with contextlib.suppress(json.JSONDecodeError, OSError):
                raw = cast(
                    "object",
                    json.loads(self.benchmark_path.read_text(encoding="utf-8")),
                )
                if isinstance(raw, dict):
                    benchmark = cast("dict[str, object]", raw)
        html = generate_html(runs, self.skill_name, self.previous, benchmark)
        content = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        _ = self.wfile.write(content)

    def _serve_feedback_get(self) -> None:
        """Serve existing feedback JSON."""
        data = b"{}"
        if self.feedback_path.exists():
            with contextlib.suppress(OSError):
                data = self.feedback_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        _ = self.wfile.write(data)

    def do_GET(self) -> None:
        """Handle GET requests for review page and feedback API."""
        if self.path in {"/", "/index.html"}:
            self._serve_index()
        elif self.path == "/api/feedback":
            self._serve_feedback_get()
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        """Handle POST requests to save reviewer feedback."""
        if self.path == "/api/feedback":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                raw_data = cast("object", json.loads(body))
                if not isinstance(raw_data, dict) or "reviews" not in raw_data:
                    err_msg = "Expected JSON object with 'reviews' key"
                    raise ValueError(err_msg)  # noqa: TRY301 - inner validation
                data_dict = cast("dict[str, object]", raw_data)
                _ = self.feedback_path.write_text(
                    json.dumps(data_dict, indent=2) + "\n",
                    encoding="utf-8",
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
        else:
            self.send_error(404)

    @override
    def log_message(
        self,
        format: str,
        *args: object,
    ) -> None:
        """Suppress standard request logging to keep terminal clean."""
        _ = (format, args)


def _print_server_banner(  # noqa: PLR0913, PLR0917 - banner parameter list
    url: str,
    workspace: Path,
    feedback_path: Path,
    previous_count: int,
    previous_workspace: Path | None,
    benchmark_path: Path | None,
) -> None:
    """Print terminal startup banner with connection information."""
    print("\n  Eval Viewer")
    print("  ─────────────────────────────────")
    print(f"  URL:       {url}")
    print(f"  Workspace: {workspace}")
    print(f"  Feedback:  {feedback_path}")
    if previous_count > 0:
        print(f"  Previous:  {previous_workspace} ({previous_count} runs)")
    if benchmark_path:
        print(f"  Benchmark: {benchmark_path}")
    print("\n  Press Ctrl+C to stop.\n")


def _load_benchmark_data(benchmark_path: Path | None) -> dict[str, object] | None:
    """Load benchmark data if benchmark path exists."""
    if benchmark_path and benchmark_path.exists():
        with contextlib.suppress(json.JSONDecodeError, OSError):
            raw = cast(
                "object",
                json.loads(benchmark_path.read_text(encoding="utf-8")),
            )
            if isinstance(raw, dict):
                return cast("dict[str, object]", raw)
    return None


def _parse_args() -> dict[str, object]:
    """Parse command-line arguments for eval review generator."""
    parser = argparse.ArgumentParser(description="Generate and serve eval review")
    _ = parser.add_argument(
        "workspace",
        type=Path,
        help="Path to workspace directory",
    )
    _ = parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"Server port (default: {DEFAULT_PORT})",
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
            "Path to previous iteration's workspace "
            + "(shows old outputs and feedback as context)"
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
    return cast("dict[str, object]", vars(parser.parse_args()))


def main() -> None:
    """CLI entry point to generate and serve eval review."""
    args_dict = _parse_args()
    workspace_val = args_dict.get("workspace")
    workspace = (
        workspace_val.resolve()
        if isinstance(workspace_val, Path)
        else Path(str(workspace_val)).resolve()
    )
    if not workspace.is_dir():
        print(f"Error: {workspace} is not a directory", file=sys.stderr)
        sys.exit(1)

    runs = find_runs(workspace)
    if not runs:
        print(f"No runs found in {workspace}", file=sys.stderr)
        sys.exit(1)

    skill_name_val = args_dict.get("skill_name")
    skill_name = (
        str(skill_name_val)
        if skill_name_val
        else workspace.name.replace("-workspace", "")
    )
    feedback_path = workspace / "feedback.json"

    prev_ws_val = args_dict.get("previous_workspace")
    prev_ws = (
        prev_ws_val.resolve()
        if isinstance(prev_ws_val, Path)
        else Path(str(prev_ws_val)).resolve()
        if prev_ws_val
        else None
    )
    previous: dict[str, dict[str, object]] = {}
    if prev_ws:
        previous = load_previous_iteration(prev_ws)

    bench_val = args_dict.get("benchmark")
    benchmark_path = (
        bench_val.resolve()
        if isinstance(bench_val, Path)
        else Path(str(bench_val)).resolve()
        if bench_val
        else None
    )
    benchmark = _load_benchmark_data(benchmark_path)

    static_val = args_dict.get("static")
    static_path = (
        static_val
        if isinstance(static_val, Path)
        else Path(str(static_val))
        if static_val
        else None
    )
    if static_path:
        html = generate_html(runs, skill_name, previous, benchmark)
        static_path.parent.mkdir(parents=True, exist_ok=True)
        _ = static_path.write_text(html, encoding="utf-8")
        print(f"\n  Static viewer written to: {static_path}\n")
        sys.exit(0)

    # Kill any existing process on the target port
    port = _safe_int(args_dict.get("port"), DEFAULT_PORT)
    _kill_port(port)
    handler = partial(
        ReviewHandler,
        workspace,
        skill_name,
        feedback_path,
        previous,
        benchmark_path,
    )
    try:
        server = HTTPServer(("127.0.0.1", port), handler)
    except OSError:
        # Port still in use after kill attempt — find a free one
        server = HTTPServer(("127.0.0.1", 0), handler)
        port = int(server.server_address[1])

    url = f"http://localhost:{port}"
    _print_server_banner(
        url,
        workspace,
        feedback_path,
        len(previous),
        prev_ws,
        benchmark_path,
    )

    _ = webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
