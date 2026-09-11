"""Multi-marketplace scan engine (port of lib/engine.ts)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from adapters import register_builtin_adapters
from firecrawl import Firecrawl
from registry import resolve_adapters
from scoring import score_listing

if TYPE_CHECKING:
    from models import (
        MarketplaceAdapter,
        MarketplaceId,
        RawMarketListing,
        ScanOptions,
        ScanResultData,
        ScoredDeal,
        SearchTarget,
    )

# Ensure built-in marketplace adapters are initialized
register_builtin_adapters()

# Response status range equivalent to fetch's res.ok
_HTTP_OK_MIN = 200
_HTTP_OK_MAX = 300
_DEFAULT_WAIT_FOR_MS = 2000
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0


def _fetch_api_target(target: SearchTarget, timeout_seconds: float) -> Any:
    """Fetch an ``api`` format target directly; return JSON or text, else None."""
    try:
        request = urllib.request.Request(  # noqa: S310
            target["url"],
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36",
                "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as res:  # noqa: S310
            status = res.status
            if status is None or not _HTTP_OK_MIN <= status < _HTTP_OK_MAX:
                return None
            content_type = res.headers.get("content-type") or ""
            body = res.read()
            if "json" in content_type:
                return json.loads(body.decode("utf-8", errors="replace"))
            return body.decode("utf-8", errors="replace")
    except Exception:
        return None


def _scrape_with_sdk(target: SearchTarget, api_key: str, timeout_seconds: float) -> Any:
    """Scrape via the Firecrawl SDK; return the json payload, else None."""
    try:
        api_url = os.environ.get("FIRECRAWL_API_URL") or "https://api.firecrawl.dev"
        app = Firecrawl(api_key=api_key, api_url=api_url, timeout=timeout_seconds)
        wait_for_ms = target.get("waitForMs")
        res = app.scrape(
            target["url"],
            formats=["json"],
            wait_for=wait_for_ms if wait_for_ms is not None else _DEFAULT_WAIT_FOR_MS,
            only_main_content=True,
        )
    except Exception:
        return None
    if res is not None and res.json:
        return res.json
    return None


def _cli_scrape_command(url: str) -> list[str] | None:
    """Build the keyless scrape command: installed ``firecrawl``, else ``bun x``."""
    firecrawl_bin = shutil.which("firecrawl")
    if firecrawl_bin:
        return [firecrawl_bin, "scrape", url, "--only-main-content"]
    bun_bin = shutil.which("bun")
    if bun_bin:
        return [
            bun_bin,
            "x",
            "firecrawl-cli@latest",
            "scrape",
            url,
            "--only-main-content",
        ]
    return None


def _scrape_with_cli(url: str, timeout_seconds: float) -> str | None:
    """Scrape via the keyless firecrawl CLI subprocess; return text or None."""
    command = _cli_scrape_command(url)
    if command is None:
        return None
    try:
        proc = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout_seconds,
        )
        text = proc.stdout.decode("utf-8", errors="replace")
    except Exception:
        return None
    if text and text.strip():
        return text
    return None


def _scrape_target(
    target: SearchTarget, firecrawl_api_key: str | None, timeout_seconds: float
) -> Any:
    """Scrape a target via the Firecrawl SDK with a keyless CLI fallback."""
    try:
        api_key = firecrawl_api_key or os.environ.get("FIRECRAWL_API_KEY")
        if api_key:
            scraped = _scrape_with_sdk(target, api_key, timeout_seconds)
            if scraped:
                return scraped

        # Fallback to keyless Firecrawl CLI scraper
        return _scrape_with_cli(target["url"], timeout_seconds)
    except Exception:
        return None


def _request_timeout(options: ScanOptions) -> float:
    """Resolve the per-request timeout from scan options or the default."""
    configured = options.get("timeoutSeconds")
    if (
        isinstance(configured, (int, float))
        and not isinstance(configured, bool)
        and configured > 0
    ):
        return float(configured)
    return _DEFAULT_REQUEST_TIMEOUT_SECONDS


def fetch_adapter_listings(
    adapter: MarketplaceAdapter,
    query: str,
    firecrawl_api_key: str | None = None,
    timeout_seconds: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> list[RawMarketListing]:
    """Fetch and normalize listings for one adapter; degrade to [] on failure."""
    target = adapter.build_search_target(query)

    if target["format"] == "api":
        raw_data = _fetch_api_target(target, timeout_seconds)
        if raw_data:
            try:
                return adapter.parse_listings(raw_data)
            except Exception:
                return []
        return []

    # Web scraping via Firecrawl SDK with keyless fallback
    scraped_data = _scrape_target(target, firecrawl_api_key, timeout_seconds)

    if scraped_data:
        try:
            return adapter.parse_listings(scraped_data)
        except Exception:
            return []

    return []


def execute_scan(options: ScanOptions) -> ScanResultData:
    """Run the multi-marketplace scan and return the result payload."""
    register_builtin_adapters()
    has_firecrawl_key = bool(
        os.environ.get("FIRECRAWL_API_KEY") or os.environ.get("FIRECRAWL_API_URL")
    )
    cli_fallback_available = bool(shutil.which("firecrawl") or shutil.which("bun"))
    warning_message = None
    if not has_firecrawl_key:
        warning_message = (
            "FIRECRAWL_API_KEY is not configured. Web scraping adapters "
            "(G2A, Kinguin, Z2U, FunPay) are degraded; only direct API adapters "
            "(Plati) returned live results. Configure FIRECRAWL_API_KEY for "
            "complete multi-marketplace coverage."
            if not cli_fallback_available
            else "FIRECRAWL_API_KEY is not configured. Web scraping adapters "
            "(G2A, Kinguin, Z2U, FunPay) fall back to the keyless firecrawl "
            "CLI, which is slower and rate-limited. Configure "
            "FIRECRAWL_API_KEY for reliable multi-marketplace coverage."
        )

    adapters = resolve_adapters(options.get("markets"))
    markets_queried: list[MarketplaceId] = [a.id for a in adapters]
    degraded_markets: list[MarketplaceId] = []
    timeout_seconds = _request_timeout(options)

    # Query enabled adapters with concurrency of 2 to prevent CLI process locks
    def _run_adapter(adapter: MarketplaceAdapter) -> dict[str, Any]:
        listings = fetch_adapter_listings(
            adapter, options["query"], timeout_seconds=timeout_seconds
        )
        return {
            "id": adapter.id,
            "listings": listings,
            "failed": len(listings) == 0,
        }

    with ThreadPoolExecutor(max_workers=2) as pool:
        adapter_results = list(pool.map(_run_adapter, adapters))

    raw_listings: list[RawMarketListing] = []
    for r in adapter_results:
        if r["failed"]:
            degraded_markets.append(r["id"])
        raw_listings.extend(r["listings"])

    # Score and evaluate all listings through the decision engine
    scored_deals: list[ScoredDeal] = [
        score_listing(listing) for listing in raw_listings
    ]

    # Filter deals based on budget, minScore, and type
    min_score_raw = options.get("minScore")
    min_score = 50 if min_score_raw is None else min_score_raw
    filtered_scams_count = 0
    valid_deals: list[ScoredDeal] = []

    for deal in scored_deals:
        if deal["isCircuitBreakerTripped"] or deal["trustScore"] < min_score:
            filtered_scams_count += 1
            if not options.get("full"):
                continue

        budget = options.get("budget")
        if budget is not None and deal["priceUsd"] > budget:
            continue

        type_filter = options.get("typeFilter")
        if type_filter and type_filter != "all":
            tf = type_filter.lower()
            df = deal["deliveryFormat"].lower()
            if tf not in df:
                continue

        valid_deals.append(deal)

    # Sort by trust score descending, then price ascending
    valid_deals.sort(key=lambda d: (-d["trustScore"], d["priceUsd"]))

    result: ScanResultData = {
        "query": options["query"],
        "budget": options.get("budget"),
        "total_scanned": len(raw_listings),
        "valid_deals_count": len(valid_deals),
        "filtered_scams_count": filtered_scams_count,
        "top_deals": valid_deals,
        "markets_queried": markets_queried,
        "degraded_markets": degraded_markets,
        "is_degraded_mode": not has_firecrawl_key,
    }
    if warning_message is not None:
        result["warning"] = warning_message
    return result
