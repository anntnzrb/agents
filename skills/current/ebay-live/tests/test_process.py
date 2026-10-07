# ruff: noqa: PLR2004 - assertions use literal captured values.
"""Public subprocess tests with real curl and SDK calls over loopback only."""

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, cast, override

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping, Sequence

import pytest
from ebay_live.detail_parser import load_json
from ebay_live.protocol import get_schema_document
from jsonschema import validate

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


@contextmanager
def server(
    *,
    blocked: bool = False,
    detail_failure: bool = False,
    fallback: str = "search.html",
    proxy_error: bool = False,
) -> Generator[tuple[str, list[dict[str, object]]]]:
    """Serve captured HTML and the Firecrawl v2 scrape response shape."""
    requests: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        """Loopback external boundary fixture."""

        def do_GET(self) -> None:
            """Return a real search, block page, or item response."""
            if self.path.startswith("/itm/"):
                filename = "item.html"
                status = 404 if detail_failure else 200
            else:
                filename = "challenge.html" if blocked else "search.html"
                status = 200
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            _ = self.wfile.write((FIXTURES / filename).read_bytes())

        def do_POST(self) -> None:
            """Expose the SDK's real HTTP API without replacing the SDK."""
            request = cast(
                "dict[str, object]",
                load_json(
                    self.rfile.read(int(self.headers["Content-Length"])).decode()
                ),
            )
            requests.append(request)
            body = {
                "success": True,
                "data": {
                    "rawHtml": (FIXTURES / fallback).read_text(encoding="utf-8")
                    if fallback
                    else "",
                    "metadata": {
                        "sourceURL": request["url"],
                        "url": request["url"],
                        "statusCode": 200,
                    },
                },
            }
            if proxy_error:
                body = {"success": False, "error": "Fixture scrape failed"}
            self.send_response(500 if proxy_error else 200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            _ = self.wfile.write(json.dumps(body).encode())

        @override
        def log_message(self, format: str, *args: object) -> None:
            """Keep test output focused on the observed process."""

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", requests
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def run_cli(
    home: Path,
    args: Sequence[str],
    env: Mapping[str, str] | None = None,
    *,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the real PEP 723 launcher in an isolated temporary home."""
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "cli.py"), *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        cwd=home,
        env={
            **{
                key: value
                for key, value in os.environ.items()
                if key in ("PATH", "SYSTEMROOT", "WINDIR")
            },
            "HOME": str(home),
            "USERPROFILE": str(home),
            **(env or {}),
        },
    )


def payload(output: str) -> dict[str, object]:
    """Decode process JSON for assertions."""
    return cast("dict[str, object]", load_json(output))


def test_live_entrypoint_and_schema(tmp_path: Path) -> None:
    """The serving transport and every mandatory envelope field are public."""
    with server() as (url, _requests):
        result = run_cli(
            tmp_path,
            ["sony", "--llm-json", "--limit", "2"],
            {"EBAY_LIVE_BASE_URL": url},
        )
    assert result.returncode == 0, result.stderr
    data = payload(result.stdout)
    assert data["summary"] == {
        "raw_result_count": 12,
        "exact_result_count": 12,
        "rewrite_excluded_count": 0,
        "returned_result_count": 2,
        "transport": ["direct"],
        "fetches": [
            {
                "url": f"{url}/sch/i.html?_nkw=sony&_sop=12&_ipg=60&_pgn=1",
                "final_url": f"{url}/sch/i.html?_nkw=sony&_sop=12&_ipg=60&_pgn=1",
                "transport": "direct",
                "ok": True,
            }
        ],
    }
    schema = cast("dict[str, object]", get_schema_document()["llm_json"])
    validate_json: Callable[..., None] = validate
    validate_json(data, schema)
    assert set(data) == set(cast("list[str]", schema["required"]))
    assert [r["item_id"] for r in cast("list[dict[str, object]]", data["results"])] == [
        "178557756440",
        "960014091123",
    ]


def test_auto_fallback_calls_real_sdk(tmp_path: Path) -> None:
    """A challenge triggers one raw-HTML SDK call with caching disabled."""
    with server(blocked=True) as (url, calls):
        result = run_cli(
            tmp_path,
            ["sony", "--llm-json", "--limit", "1"],
            {
                "EBAY_LIVE_BASE_URL": url,
                "FIRECRAWL_API_KEY": "fixture-key",
                "FIRECRAWL_API_URL": url,
            },
        )
    assert result.returncode == 0, result.stderr
    data = payload(result.stdout)
    assert cast("dict[str, object]", data["summary"])["transport"] == ["firecrawl"]
    assert len(calls) == 1
    assert calls[0]["formats"] == ["rawHtml"]
    assert calls[0]["maxAge"] == 0
    assert calls[0]["storeInCache"] is False
    assert "Direct eBay request blocked" in str(data["warnings"])


def test_block_without_key_and_direct_mode(tmp_path: Path) -> None:
    """Missing credentials fail; forced direct never spends a proxy call."""
    with server(blocked=True) as (url, calls):
        result = run_cli(tmp_path, ["sony", "--llm-json"], {"EBAY_LIVE_BASE_URL": url})
        direct = run_cli(
            tmp_path,
            ["sony", "--transport", "direct"],
            {
                "EBAY_LIVE_BASE_URL": url,
                "FIRECRAWL_API_KEY": "fixture-key",
                "FIRECRAWL_API_URL": url,
            },
        )
    assert result.returncode == direct.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("error:")
    assert "FIRECRAWL_API_KEY" in result.stderr
    assert calls == []


def test_bad_fallback_stays_failed(tmp_path: Path) -> None:
    """A proxy returning a challenge must not yield an empty success."""
    with server(blocked=True, fallback="challenge.html") as (url, calls):
        result = run_cli(
            tmp_path,
            ["sony", "--llm-json"],
            {
                "EBAY_LIVE_BASE_URL": url,
                "FIRECRAWL_API_KEY": "fixture-key",
                "FIRECRAWL_API_URL": url,
            },
        )
    assert result.returncode == 1
    assert "blocked access" in result.stderr
    assert len(calls) == 1


def test_details_success_and_failure(tmp_path: Path) -> None:
    """Item enrichment is bounded and failures preserve the search card."""
    for failure in (False, True):
        with server(detail_failure=failure) as (url, _calls):
            result = run_cli(
                tmp_path,
                [
                    "sony",
                    "--llm-json",
                    "--limit",
                    "2",
                    "--scoring",
                    "--details",
                    "--detail-limit",
                    "1",
                ],
                {"EBAY_LIVE_BASE_URL": url},
            )
        assert result.returncode == 0, result.stderr
        data = payload(result.stdout)
        validate_json: Callable[..., None] = validate
        validate_json(data, get_schema_document()["llm_json"])
        assert data["enrichment"] == {
            "requested": True,
            "detail_limit": 1,
            "attempted": 1,
            "succeeded": 0 if failure else 1,
        }
        rows = cast("list[dict[str, object]]", data["results"])
        assert rows[0]["item_id"] == "377534750427"
        assert rows[0]["price"] == 36.0
        if failure:
            assert "Detail fetch failed" in str(data["warnings"])
        else:
            assert cast("dict[str, object]", rows[0]["details"])["brand"] == "Sony"


def test_rpc_and_usage_errors(tmp_path: Path) -> None:
    """RPC continues after malformed lines and rejects invalid field types."""
    result = run_cli(
        tmp_path,
        ["--mode", "rpc"],
        stdin='oops\n{"id":1,"type":"ping"}\n{"type":"search","query":"sony","pages":true}\n{"type":"wat"}\n',
    )
    assert result.returncode == 0, result.stderr
    responses = [payload(line) for line in result.stdout.splitlines()]
    assert responses[1] == {
        "id": 1,
        "type": "response",
        "command": "ping",
        "success": True,
        "data": {"ok": True, "version": "1"},
    }
    assert [
        cast("dict[str, object]", r["error"])["code"]
        for r in (responses[0], responses[2], responses[3])
    ] == ["parse_error", "invalid_request", "unknown_command"]
    usage = run_cli(tmp_path, ["sony", "--min-price", "20", "--max-price", "10"])
    assert usage.returncode == 2
    assert "minPrice must not exceed maxPrice" in usage.stderr


def test_forced_firecrawl_and_rpc_search(tmp_path: Path) -> None:
    """Forced proxy and camelCase RPC fields reach the real pipeline."""
    with server() as (url, calls):
        result = run_cli(
            tmp_path,
            ["sony", "--transport", "firecrawl", "--json", "--limit", "1"],
            {
                "EBAY_LIVE_BASE_URL": url,
                "FIRECRAWL_API_URL": url,
                "FIRECRAWL_API_KEY": "fixture-key",
            },
        )
    assert result.returncode == 0, result.stderr
    assert (
        cast("list[dict[str, object]]", load_json(result.stdout))[0]["seller_name"]
        == "crislomcam"
    )
    assert len(calls) == 1
    request = {
        "id": "cards",
        "type": "search",
        "query": "sony",
        "htmlPath": str(FIXTURES / "search.html"),
        "titleContains": "headphones",
        "minSellerFeedback": 99,
        "freeShipping": True,
        "limit": 1,
    }
    rpc = run_cli(tmp_path, ["--mode", "rpc"], stdin=json.dumps(request) + "\n")
    response = payload(rpc.stdout)
    assert response["success"] is True
    assert response["id"] == "cards"
    data = cast("dict[str, object]", response["data"])
    assert (
        cast("list[dict[str, object]]", data["results"])[0]["item_id"] == "287138167642"
    )


@pytest.mark.parametrize("proxy_error", [False, True])
def test_proxy_empty_and_error_responses(tmp_path: Path, *, proxy_error: bool) -> None:
    """Real SDK errors and empty documents fail once with a clear stderr error."""
    with server(blocked=True, fallback="", proxy_error=proxy_error) as (url, calls):
        result = run_cli(
            tmp_path,
            ["sony", "--llm-json"],
            {
                "EBAY_LIVE_BASE_URL": url,
                "FIRECRAWL_API_URL": url,
                "FIRECRAWL_API_KEY": "fixture-key",
            },
        )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("error:")
    assert "Firecrawl" in result.stderr
    assert len(calls) == 1


def test_captured_rewrite_and_deal_ranking(tmp_path: Path) -> None:
    """Real cards after rewrite are excluded and cheap parts cannot win."""
    result = run_cli(
        tmp_path,
        [
            "steam deck oled",
            "--html",
            str(FIXTURES / "steam-rewrite.html"),
            "--llm-json",
            "--scoring",
        ],
    )
    assert result.returncode == 0, result.stderr
    data = payload(result.stdout)
    validate_json: Callable[..., None] = validate
    validate_json(data, get_schema_document()["llm_json"])
    summary = cast("dict[str, object]", data["summary"])
    assert summary["exact_result_count"] == 11
    assert summary["rewrite_excluded_count"] == 2
    rows = cast("list[dict[str, object]]", data["results"])
    assert len(rows) == 11
    assert all("OLED" in str(r["title"]).upper() for r in rows[:4])
    assert all(cast("float", r["total_cost"]) > 200 for r in rows[:4])
    bag = next(r for r in rows if "Carrying Bag" in str(r["title"]))
    board = next(r for r in rows if "Audio Button Board" in str(r["title"]))
    assert bag["query_match"] == pytest.approx(2 / 3)
    assert board["query_match"] == 1
    assert "likely accessory/part price outlier" in str(board["reasons"])
    assert cast("float", rows[0]["score"]) > cast("float", board["score"])


def test_captured_rtx_rewrite(tmp_path: Path) -> None:
    """The expanded RTX 3070 match never appears as an exact RTX 4070 result."""
    result = run_cli(
        tmp_path,
        ["rtx 4070", "--html", str(FIXTURES / "rtx-rewrite.html"), "--llm-json"],
    )
    assert result.returncode == 0, result.stderr
    data = payload(result.stdout)
    rows = cast("list[dict[str, object]]", data["results"])
    assert len(rows) == 2
    assert all("4070" in str(r["title"]) for r in rows)
    assert cast("dict[str, object]", data["summary"])["rewrite_excluded_count"] == 1


def test_zero_exact_matches_warns(tmp_path: Path) -> None:
    """A real rewrite section is successful empty evidence, with a warning."""
    result = run_cli(
        tmp_path,
        ["rtx 4070", "--html", str(FIXTURES / "zero-exact.html"), "--llm-json"],
    )
    assert result.returncode == 0, result.stderr
    data = payload(result.stdout)
    assert data["results"] == []
    summary = cast("dict[str, object]", data["summary"])
    assert summary["exact_result_count"] == 0
    assert summary["rewrite_excluded_count"] == 1
    assert "Zero exact matches" in str(data["warnings"])
    validate_json: Callable[..., None] = validate
    validate_json(data, get_schema_document()["llm_json"])
