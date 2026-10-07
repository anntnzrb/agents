"""Exercise the public process with captured Amazon responses at a loopback HTTP boundary."""

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, TypeIs, override
from urllib.parse import parse_qs, urlparse

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from amz_live.protocol import SearchResultsPayload


def _loads_json(text: str) -> object:
    load: Callable[..., object] = json.loads
    return load(text)


def _is_envelope(value: object) -> TypeIs[SearchResultsPayload]:
    return isinstance(value, dict)


def _is_response(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
MODAL_CONFIG = json.dumps(
    {
        "name": "glow-modal",
        "url": "/portal-migration/hz/glow/get-rendered-address-selections",
        "ajaxHeaders": {"anti-csrftoken-a2z": "bootstrap-token"},
    }
)
BOOTSTRAP = (
    f"<span id='nav-global-location-data-modal-action' data-a-modal='{MODAL_CONFIG}'></span>"
)


@dataclass
class _AmazonBoundary:
    failure: str | None = None
    events: list[tuple[str, str, str, str | None]] = field(default_factory=list)
    updated: bool = False
    search_count: int = 0
    deal_id: str = "987654321"
    deal_label: str = "Today's Deals"
    empty_from_page: int | None = None


class _AmazonHTTPServer(ThreadingHTTPServer):
    state: _AmazonBoundary | None = None


class _AmazonHandler(BaseHTTPRequestHandler):
    @property
    def state(self) -> _AmazonBoundary:
        assert isinstance(self.server, _AmazonHTTPServer)
        assert self.server.state is not None
        return self.server.state

    @override
    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _respond(self, body: str, *, status: int = 200, cookie: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if cookie:
            self.send_header("Set-Cookie", "guest-session=captured-session; Path=/")
        self.end_headers()
        _ = self.wfile.write(body.encode("utf-8"))

    def do_GET(self) -> None:
        path = urlparse(self.path)
        cookie = self.headers.get("Cookie")
        self.state.events.append(("GET", self.path, "", cookie))
        if path.path == "/s":
            self.state.search_count += 1
            query = parse_qs(path.query)
            assert "p_47" not in query.get("rh", [""])[0]
            if self.state.failure == "blocked":
                self._respond("Robot Check", status=503)
                return
            body = self._search_body(cookie)
            if self._is_empty_page(query):
                self._respond(
                    '<span id="glow-ingress-line2">Miami 33101</span><h2>No results for x</h2>'
                )
                return
            body = self._apply_deal_filter(body, query)
            self._respond(body, cookie=True)
        elif path.path.endswith("get-rendered-address-selections"):
            assert cookie == "guest-session=captured-session"
            assert self.headers.get("anti-csrftoken-a2z") == "bootstrap-token"
            self._respond('P.declare("GLUXWidget", { CSRF_TOKEN : "location-token" });')
        elif path.path.startswith("/dp/"):
            assert self.state.updated
            assert cookie == "guest-session=captured-session"
            if self.state.failure == "detail_blocked":
                self._respond("Robot Check", status=503)
            else:
                self._respond(
                    (FIXTURES / "product_detail_B07CWC39TL.html").read_text(encoding="utf-8")
                )
        else:
            self._respond("Unexpected fixture path", status=404)

    def _search_body(self, cookie: str | None) -> str:
        if self.state.updated:
            assert cookie == "guest-session=captured-session"
            body = (FIXTURES / "us_prime_offers.html").read_text(encoding="utf-8")
            if self.state.failure == "wrong_location":
                body = body.replace("Miami 33101", "Ecuador")
            if self.state.failure == "missing_refinement":
                body = body.replace('aria-current="true"', 'aria-current="false"')
        else:
            body = BOOTSTRAP + '<span id="glow-ingress-line2">Ecuador</span>'
            body += (FIXTURES / "current_offers_fragment.html").read_text(encoding="utf-8")
            if self.state.search_count > 1:
                body = body.replace("128.47", "120.00")
        return body

    def _is_empty_page(self, query: dict[str, list[str]]) -> bool:
        return (
            bool(query.get("rh"))
            and self.state.empty_from_page is not None
            and int(query.get("page", ["1"])[0]) >= self.state.empty_from_page
        )

    def _apply_deal_filter(self, body: str, query: dict[str, list[str]]) -> str:
        if query.get("rh"):
            assert query["rh"] == [f"p_n_deal_type:{self.state.deal_id}"]
            if not self.state.updated:
                body += (
                    '<ul id="filter-p_n_deal_type"><a aria-current="true">'
                    f"{self.state.deal_label}</a></ul>"
                )
            if self.state.failure == "changed_label":
                return body.replace("Prime Big Deals", "Unexpected filter")
            return body.replace("Prime Big Deals", self.state.deal_label)
        body = body.replace('aria-current="true"', 'aria-current="false"')
        if self.state.failure == "no_deals":
            return body
        return body + (
            '<ul id="filter-p_n_deal_type">'
            f'<a href="/s?rh=p_n_deal_type%3A{self.state.deal_id}">'
            f"{self.state.deal_label}</a></ul>"
        )

    def do_POST(self) -> None:
        cookie = self.headers.get("Cookie")
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
        self.state.events.append(("POST", self.path, body, cookie))
        assert self.path == "/portal-migration/hz/glow/address-change?actionSource=glow"
        assert cookie == "guest-session=captured-session"
        assert self.headers.get("anti-csrftoken-a2z") == "location-token"
        request = _loads_json(body)
        assert _is_response(request)
        assert request["zipCode"] == "33101"
        assert request["locationType"] == "LOCATION_INPUT"
        self.state.updated = self.state.failure != "rejected_zip"
        response = {
            "isValidAddress": int(self.state.updated),
            "isAddressUpdated": int(self.state.updated),
        }
        self._respond(json.dumps(response))


@contextmanager
def _amazon_server(state: _AmazonBoundary) -> Generator[str]:
    with _AmazonHTTPServer(("127.0.0.1", 0), _AmazonHandler) as server:
        server.state = state
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join(timeout=5)


def _run_process(
    base: str, home: Path, args: list[str], *, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "cli.py"), *args],
        input=stdin,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        cwd=home,
        env={
            **{
                key: os.environ[key]
                for key in ("PATH", "SYSTEMROOT", "WINDIR")
                if key in os.environ
            },
            "HOME": str(home),
            "USERPROFILE": str(home),
            "AMZ_LIVE_BASE_URL": base,
        },
    )


def test_cli_sets_zip_once_and_keeps_session_through_pages_and_details(tmp_path: Path) -> None:
    state = _AmazonBoundary()
    with _amazon_server(state) as base:
        result = _run_process(
            base,
            tmp_path,
            [
                "earbuds",
                "--zip",
                "33101",
                "--deals",
                "--pages",
                "2",
                "--details",
                "--detail-limit",
                "2",
                "--llm-json",
            ],
        )
    assert result.returncode == 0, result.stderr
    payload = _loads_json(result.stdout)
    assert _is_envelope(payload)
    assert payload["summary"]["delivery_location"] == "Miami 33101"
    assert payload["query"]["deal_refinement"] == "Today's Deals"
    assert payload["enrichment"]["succeeded"] == 2
    assert not any("/sspa/click" in event[1] for event in state.events)
    assert len([event for event in state.events if event[1].startswith("/dp/")]) == 2
    assert "checked_at" in payload["source"]
    assert payload["source"]["checked_at"].endswith("+00:00")
    assert len([event for event in state.events if event[0] == "POST"]) == 1
    search_urls = [event[1] for event in state.events if event[1].startswith("/s?")]
    assert len(search_urls) == 4
    assert [parse_qs(urlparse(url).query).get("rh") for url in search_urls] == [
        None,
        None,
        ["p_n_deal_type:987654321"],
        ["p_n_deal_type:987654321"],
    ]


def test_rpc_refreshes_prices_between_identical_requests(tmp_path: Path) -> None:
    state = _AmazonBoundary()
    request = json.dumps({"type": "search", "query": "earbuds"}) + "\n"
    with _amazon_server(state) as base:
        result = _run_process(base, tmp_path, ["--mode", "rpc"], stdin=request * 2)
    assert result.returncode == 0, result.stderr
    responses = [_loads_json(line) for line in result.stdout.splitlines()]
    prices: list[float | None] = []
    for response in responses:
        assert _is_response(response)
        assert response["success"] is True
        payload = response["data"]
        assert _is_envelope(payload)
        assert payload["summary"]["delivery_location"] == "Ecuador"
        assert "warnings" in payload
        assert payload["warnings"]
        prices.append(payload["results"][0]["price"])
    assert prices == [128.47, 120.00]
    assert state.search_count == 2


@pytest.mark.parametrize(
    "failure",
    [
        "rejected_zip",
        "wrong_location",
        "missing_refinement",
        "blocked",
        "no_deals",
        "changed_label",
    ],
)
def test_cli_reports_session_and_upstream_failures(failure: str, tmp_path: Path) -> None:
    state = _AmazonBoundary(failure=failure)
    with _amazon_server(state) as base:
        result = _run_process(
            base, tmp_path, ["earbuds", "--zip", "33101", "--deals", "--llm-json"]
        )
    assert result.returncode == 1
    assert not result.stdout
    assert "error:" in result.stderr


def test_detail_block_does_not_discard_valid_search_results(tmp_path: Path) -> None:
    state = _AmazonBoundary(failure="detail_blocked")
    with _amazon_server(state) as base:
        result = _run_process(
            base,
            tmp_path,
            [
                "earbuds",
                "--zip",
                "33101",
                "--deals",
                "--details",
                "--detail-limit",
                "2",
                "--llm-json",
            ],
        )
    assert result.returncode == 0, result.stderr
    payload = _loads_json(result.stdout)
    assert _is_envelope(payload)
    assert payload["enrichment"] == {
        "details": True,
        "detail_limit": 2,
        "attempted": 1,
        "succeeded": 0,
    }
    assert payload["results"]
    assert payload["results"][0].get("details") is None
    assert len([event for event in state.events if event[1].startswith("/dp/")]) == 1


@pytest.mark.parametrize(
    ("deal_id", "label"),
    [("123", "All Deals"), ("456", "Prime Day Deals"), ("789", "Holiday Deals")],
)
def test_cli_discovers_changing_deal_ids_and_labels(
    deal_id: str, label: str, tmp_path: Path
) -> None:
    state = _AmazonBoundary(deal_id=deal_id, deal_label=label)
    with _amazon_server(state) as base:
        result = _run_process(
            base, tmp_path, ["earbuds", "--zip", "33101", "--deals", "--llm-json"]
        )
    assert result.returncode == 0, result.stderr
    payload = _loads_json(result.stdout)
    assert _is_envelope(payload)
    assert payload["query"]["deal_refinement"] == label
    assert any(
        parse_qs(urlparse(event[1]).query).get("rh") == [f"p_n_deal_type:{deal_id}"]
        for event in state.events
    )


def test_cli_discovers_deals_without_zip_and_warns_about_location(tmp_path: Path) -> None:
    state = _AmazonBoundary(deal_id="222", deal_label="All Deals")
    with _amazon_server(state) as base:
        result = _run_process(base, tmp_path, ["earbuds", "--deals", "--llm-json"])
    assert result.returncode == 0, result.stderr
    payload = _loads_json(result.stdout)
    assert _is_envelope(payload)
    assert payload["query"]["deal_refinement"] == "All Deals"
    assert "warnings" in payload
    assert payload["summary"]["delivery_location"] == "Ecuador"
    assert state.search_count == 2
    assert not any(event[0] == "POST" for event in state.events)


@pytest.mark.parametrize("empty_from_page", [1, 3])
def test_cli_stops_at_empty_deal_page_and_keeps_earlier_results(
    empty_from_page: int, tmp_path: Path
) -> None:
    state = _AmazonBoundary(empty_from_page=empty_from_page)
    with _amazon_server(state) as base:
        result = _run_process(
            base, tmp_path, ["earbuds", "--zip", "33101", "--deals", "--pages", "5", "--llm-json"]
        )
    assert result.returncode == 0, result.stderr
    payload = _loads_json(result.stdout)
    assert _is_envelope(payload)
    filtered_pages = [
        parse_qs(urlparse(e[1]).query)["page"][0] for e in state.events if "rh=" in e[1]
    ]
    assert filtered_pages == [str(p) for p in range(1, empty_from_page + 1)]
    if empty_from_page == 1:
        assert not payload["results"]
        assert "warnings" in payload
    else:
        assert payload["results"]
        assert payload["query"]["deal_refinement"] == "Today's Deals"
        assert "warnings" not in payload
