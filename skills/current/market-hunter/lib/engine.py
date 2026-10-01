"""Multi-marketplace scan engine (port of lib/engine.ts)."""

import json
import os
import shutil
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, TypedDict
from urllib.parse import urlsplit

from adapters import register_builtin_adapters
from models import EngineError
from registry import get_available_adapters, resolve_adapters
from scoring import score_listing
lazy from firecrawl import Firecrawl

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from contextlib import AbstractContextManager

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


def _load_json(text: str | bytes) -> object:
    """Parse JSON text or bytes to an unconstrained object tree."""
    loader: Callable[..., object] = json.loads
    return loader(text)


def _fetch_api_target(target: SearchTarget, timeout_seconds: float) -> object | None:
    """Fetch an ``api`` format target directly; return JSON or text, else None."""
    try:
        ua_prefix = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        request = urllib.request.Request(  # noqa: S310
            target["url"],
            headers={
                "User-Agent": f"{ua_prefix} AppleWebKit/537.36",
                "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                **target.get("headers", {}),
            },
        )
        opener: Callable[..., AbstractContextManager[object]] = urllib.request.urlopen
        with opener(request, timeout=timeout_seconds) as res:
            status_val: object = getattr(res, "status", None)
            if (
                not isinstance(status_val, int)
                or not _HTTP_OK_MIN <= status_val < _HTTP_OK_MAX
            ):
                return None
            headers_val: object = getattr(res, "headers", None)
            content_type = ""
            if headers_val is not None:
                header_get = getattr(headers_val, "get", None)
                if callable(header_get):
                    ct_val: object = header_get("content-type")
                    content_type = str(ct_val) if ct_val is not None else ""
            read_fn = getattr(res, "read", None)
            body_obj: object = read_fn() if callable(read_fn) else b""
            body = (
                body_obj
                if isinstance(body_obj, bytes)
                else str(body_obj).encode("utf-8")
            )
            if "json" in content_type:
                return _load_json(body.decode("utf-8", errors="replace"))
            return body.decode("utf-8", errors="replace")
    except OSError, ValueError:
        return None


def _scrape_with_sdk(
    target: SearchTarget, api_key: str, timeout_seconds: float
) -> object | None:
    """Scrape via the Firecrawl SDK; return the json payload, else None."""
    try:
        api_url = os.environ.get("FIRECRAWL_API_URL") or "https://api.firecrawl.dev"
        app = Firecrawl(api_key=api_key, api_url=api_url, timeout=timeout_seconds)
        wait_for_ms = target.get("waitForMs")
        scrape_fn: Callable[..., object] = app.scrape
        res = scrape_fn(
            target["url"],
            formats=["json"],
            wait_for=wait_for_ms if wait_for_ms is not None else _DEFAULT_WAIT_FOR_MS,
            only_main_content=True,
        )
    except Exception:  # noqa: BLE001 - SDK scrape failure deliberately degraded at request boundary
        return None
    json_attr: object = getattr(res, "json", None)
    if json_attr:
        return json_attr
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
    except subprocess.SubprocessError, OSError:
        return None
    if text and text.strip():
        return text
    return None


def _scrape_target(
    target: SearchTarget, firecrawl_api_key: str | None, timeout_seconds: float
) -> object | None:
    """Scrape a target via the Firecrawl SDK with a keyless CLI fallback."""
    try:
        api_key = firecrawl_api_key or os.environ.get("FIRECRAWL_API_KEY")
        if api_key:
            scraped = _scrape_with_sdk(target, api_key, timeout_seconds)
            if scraped:
                return scraped

        # Fallback to keyless Firecrawl CLI scraper
        return _scrape_with_cli(target["url"], timeout_seconds)
    except OSError, RuntimeError, ValueError:
        return None


def _request_timeout(options: Mapping[str, object]) -> float:
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
    url: str | None = None,
) -> list[RawMarketListing]:
    """Fetch and normalize listings for one adapter; degrade to [] on failure."""
    target = adapter.build_search_target(query)
    if url is not None:
        target["url"] = url

    if target["format"] == "api":
        raw_data = _fetch_api_target(target, timeout_seconds)
        if raw_data:
            try:
                return adapter.parse_listings(raw_data)
            except Exception:  # noqa: BLE001 - adapter parse errors degrade to empty listings
                return []
        return []

    # Web scraping via Firecrawl SDK with keyless fallback
    scraped_data = _scrape_target(target, firecrawl_api_key, timeout_seconds)

    if scraped_data:
        try:
            return adapter.parse_listings(scraped_data)
        except Exception:  # noqa: BLE001 - adapter parse errors degrade to empty listings
            return []

    return []


class _AdapterRunResult(TypedDict):
    id: MarketplaceId
    listings: list[RawMarketListing]
    failed: bool


def _resolve_warning(
    *, has_firecrawl_key: bool, cli_fallback_available: bool
) -> str | None:
    """Build warning message if Firecrawl API key is missing."""
    if has_firecrawl_key:
        return None
    prefix = "FIRECRAWL_API_KEY is not configured. Web scraping adapters"
    markets = "(G2A, Kinguin, Z2U, FunPay)"
    if not cli_fallback_available:
        suffix = "only direct API adapters (Plati) returned live results."
        cta = "Configure FIRECRAWL_API_KEY for complete multi-marketplace coverage."
        return f"{prefix} {markets} are degraded; {suffix} {cta}"
    fallback = (
        "fall back to the keyless firecrawl CLI, which is slower and rate-limited."
    )
    cta = "Configure FIRECRAWL_API_KEY for reliable multi-marketplace coverage."
    return f"{prefix} {markets} {fallback} {cta}"


def _filter_deals(
    scored_deals: list[ScoredDeal], options: ScanOptions
) -> tuple[list[ScoredDeal], int]:
    """Filter deals by circuit breaker, minScore, budget, and type."""
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

    return valid_deals, filtered_scams_count


def _resolve_jobs(
    options: ScanOptions,
) -> list[tuple[MarketplaceAdapter, str | None]]:
    """Pair adapters with explicit --url pages by host, else default targets."""
    urls = options.get("urls")
    if not urls:
        return [(a, None) for a in resolve_adapters(options.get("markets"))]
    jobs: list[tuple[MarketplaceAdapter, str | None]] = []
    for url in urls:
        host = (urlsplit(url).hostname or "").lower()
        adapter = next(
            (a for a in get_available_adapters() if a.id in host.split(".")), None
        )
        if adapter is None:
            raise EngineError(
                "unsupported_url",
                f"no marketplace adapter matches {host or url}",
                {"url": url},
            )
        jobs.append((adapter, url))
    return jobs


def execute_scan(options: ScanOptions) -> ScanResultData:
    """Run the multi-marketplace scan and return the result payload."""
    register_builtin_adapters()
    has_firecrawl_key = bool(
        os.environ.get("FIRECRAWL_API_KEY") or os.environ.get("FIRECRAWL_API_URL")
    )
    cli_fallback_available = bool(shutil.which("firecrawl") or shutil.which("bun"))
    warning_message = _resolve_warning(
        has_firecrawl_key=has_firecrawl_key,
        cli_fallback_available=cli_fallback_available,
    )

    jobs = _resolve_jobs(options)
    markets_queried: list[MarketplaceId] = list(dict.fromkeys(a.id for a, _ in jobs))
    degraded_markets: list[MarketplaceId] = []
    timeout_seconds = _request_timeout(options)

    def _run_adapter(job: tuple[MarketplaceAdapter, str | None]) -> _AdapterRunResult:
        adapter, url = job
        listings = fetch_adapter_listings(
            adapter, options["query"], timeout_seconds=timeout_seconds, url=url
        )
        return {
            "id": adapter.id,
            "listings": listings,
            "failed": len(listings) == 0,
        }

    with ThreadPoolExecutor(max_workers=2) as pool:
        adapter_results = list(pool.map(_run_adapter, jobs))

    raw_listings: list[RawMarketListing] = []
    for r in adapter_results:
        if r["failed"]:
            degraded_markets.append(r["id"])
        raw_listings.extend(r["listings"])

    scored_deals = [score_listing(listing) for listing in raw_listings]
    valid_deals, filtered_scams_count = _filter_deals(scored_deals, options)
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
