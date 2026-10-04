# Copyright (c) 2026
"""Exercise trigger evaluation through its public CLI and a loopback provider."""

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, cast, final, override

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

CLI = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"
USAGE_ERROR = 2


@pytest.fixture
def provider() -> Iterator[tuple[str, list[str | None], list[str]]]:
    """Serve queued replies, with None dropping the connection before headers."""
    replies: list[str | None] = []
    requests: list[str] = []

    @final
    class Handler(BaseHTTPRequestHandler):
        @override
        def log_message(self, format: str, *args: object) -> None:
            del format, args

        def do_POST(self) -> None:
            requests.append(
                self.rfile.read(int(self.headers["Content-Length"])).decode()
            )
            assert self.path == "/v1/chat/completions"
            reply = replies.pop(0)
            if reply is None:
                self.close_connection = True
                return
            body = json.dumps({"choices": [{"message": {"content": reply}}]}).encode()
            self.send_response(200)
            self.end_headers()
            _ = self.wfile.write(body)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1", replies, requests
        finally:
            server.shutdown()
            thread.join()


def invoke(
    tmp_path: Path,
    url: str,
    *args: str,
    cases_json: str = '[{"query": "do alpha", "expect": "alpha"}]',
    env_settings: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Build a listing and invoke the dispatcher with isolated endpoint settings."""
    for name in ("alpha", "beta", "hidden"):
        folder = tmp_path / name
        folder.mkdir(exist_ok=True)
        disabled = "disable-model-invocation: true\n" if name == "hidden" else ""
        _ = (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Use when doing {name}.\n{disabled}---\n",
            encoding="utf-8",
        )
    cases = tmp_path / "cases.json"
    _ = cases.write_text(cases_json, encoding="utf-8")
    endpoint_flags = (
        []
        if env_settings
        else [
            "--base-url",
            url,
            "--api-key",
            "test",
            "--model",
            "fixture",
        ]
    )
    return subprocess.run(
        [
            "uv",
            "run",
            "--quiet",
            "--script",
            str(CLI),
            "trigger-eval",
            "--skills-dir",
            str(tmp_path),
            "--cases",
            str(cases),
            *endpoint_flags,
            "--json",
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env={k: v for k, v in os.environ.items() if not k.startswith("OPENAI_")}
        | (env_settings or {}),
    )


def test_listing_override_majority_and_retry(
    tmp_path: Path, provider: tuple[str, list[str | None], list[str]]
) -> None:
    """Full enabled metadata reaches each call; normalized majority wins after retry."""
    url, replies, requests = provider
    replies.extend([None, " `ALPHA`\n", "beta", '"alpha"'])
    result = invoke(tmp_path, url, "--override", "alpha=Use when testing candidates.")
    assert result.returncode == 0, result.stderr
    report = cast("dict[str, object]", json.loads(result.stdout))
    assert isinstance(report, dict)
    assert report["score"] == {"passed": 1, "total": 1}
    assert report["cases"] == [
        {
            "query": "do alpha",
            "expected": "alpha",
            "majority": "alpha",
            "votes": {"alpha": 2, "beta": 1},
            "passed": True,
        }
    ]
    expected_requests = 4
    assert len(requests) == expected_requests
    for request in requests:
        assert "alpha: Use when testing candidates." in request
        assert "beta: Use when doing beta." in request
        assert "hidden" not in request


@pytest.mark.parametrize("answers", [["none"] * 3, ["alpha", "beta", "none"]])
def test_miss_or_no_majority_exits_one(
    tmp_path: Path,
    provider: tuple[str, list[str | None], list[str]],
    answers: list[str],
) -> None:
    """A miss or tie is not a passing evaluation."""
    url, replies, _ = provider
    replies.extend(answers)
    result = invoke(tmp_path, url)
    assert result.returncode == 1, result.stderr
    assert '"passed": 0' in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ("--base-url", ""),
        ("--api-key", ""),
        ("--model", ""),
        ("--runs", "2"),
        ("--jobs", "0"),
        ("--override", "hidden=Use when hidden."),
    ],
)
def test_config_errors_exit_two(tmp_path: Path, args: tuple[str, ...]) -> None:
    """Configuration errors refuse before inference."""
    result = invoke(tmp_path, "http://127.0.0.1:1/v1", *args)
    assert result.returncode == USAGE_ERROR, result.stderr


@pytest.mark.parametrize(
    "cases_json",
    [
        "[]",
        "not JSON",
        '[{"query": 42, "expect": "alpha"}]',
        '[{"query": "hi", "expect": "hidden"}]',
    ],
)
def test_bad_cases_refuse(tmp_path: Path, cases_json: str) -> None:
    """Invalid cases fail as usage errors rather than calling the provider."""
    result = invoke(tmp_path, "http://127.0.0.1:1/v1", cases_json=cases_json)
    assert result.returncode == USAGE_ERROR, result.stderr


def test_none_label_environment_and_parallel_calls(
    tmp_path: Path,
    provider: tuple[str, list[str | None], list[str]],
) -> None:
    """Environment-only configuration and bounded parallel trials support none."""
    url, replies, requests = provider
    replies.extend(["NONE"] * 3)
    result = invoke(
        tmp_path,
        url,
        "--jobs",
        "2",
        cases_json='[{"query": "hello", "expect": "none"}]',
        env_settings={
            "OPENAI_BASE_URL": url,
            "OPENAI_API_KEY": "test",
            "OPENAI_MODEL": "fixture",
        },
    )
    assert result.returncode == 0, result.stderr
    report = cast("dict[str, object]", json.loads(result.stdout))
    assert report["score"] == {"passed": 1, "total": 1}
    expected_requests = 3
    assert len(requests) == expected_requests


def test_retry_exhaustion_exits_one(
    tmp_path: Path,
    provider: tuple[str, list[str | None], list[str]],
) -> None:
    """Repeated dropped connections stop after the bounded retry budget."""
    url, replies, requests = provider
    replies.extend([None] * 3)
    result = invoke(tmp_path, url)
    assert result.returncode == 1
    assert "trigger-eval:" in result.stderr
    expected_requests = 3
    assert len(requests) == expected_requests
