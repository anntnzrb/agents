"""Kiwi and agent-browser providers for flight-live."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Mapping
from datetime import date, timedelta
from functools import lru_cache
from typing import TYPE_CHECKING, cast
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

from .models import FlightLiveError, MissingExecutableError, PlannerOffer, ResolvedPlace

if TYPE_CHECKING:
    import http.client

_IATA_RE = re.compile(r"^[A-Za-z]{3}$")

_KIWI_LOCATIONS_URL = "https://api.skypicker.com/locations"
_AGENT_BROWSER_FLAKE = "github:numtide/llm-agents.nix#agent-browser"

_KIWI_PRICE_BUTTON_RE = re.compile(
    r'button\s+"\s*([A-Za-z]{3,9}\s+\d{1,2})\s*[-–]\s*([A-Za-z]{3,9}\s+\d{1,2})\s*\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)',  # noqa: RUF001 - pattern intentionally matches hyphen and en-dash
    re.IGNORECASE,
)

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_MONTH_DAY_PARTS = 2
_SEASON_ROLLOVER_MONTHS = 7
_HTTP_ERROR_STATUS = 400


def resolve_place(
    query: str,
    *,
    locale: str,
    client: object | None = None,
) -> ResolvedPlace:
    """Resolve a place query to an IATA code via the Kiwi API."""
    del client
    clean = " ".join(query.strip().split())
    if clean == "":
        message = "Place query must be non-empty"
        raise FlightLiveError(message)
    place = _lookup_kiwi_place(clean, locale=locale)
    return ResolvedPlace(
        query=clean,
        iata=place["iata"],
        name=place["name"],
        resolved_via_autocomplete=True,
    )


def fetch_kiwi_web_calendar(  # noqa: PLR0913 - public provider surface mirrors the search domain; tests pin the signature
    *,
    origin: str,
    destination: str,
    depart_start: date,
    depart_end: date,
    trip_type: str,
    currency: str,
    locale: str,
    market: str,
    stay_min: int | None,
    stay_max: int | None,
) -> list[PlannerOffer]:
    """Fetch planner offers across the departure window via agent-browser scraping."""
    _ensure_agent_browser_available()

    origin_place = _lookup_kiwi_place(origin, locale=locale)
    destination_place = _lookup_kiwi_place(destination, locale=locale)

    stay_days = _pick_stay_days(stay_min=stay_min, stay_max=stay_max)
    all_offers: list[PlannerOffer] = []

    errors: list[str] = []
    for anchor in _search_anchors(depart_start, depart_end, step_days=5):
        return_anchor = anchor + timedelta(days=stay_days)
        url = build_kiwi_results_url(
            origin_slug=origin_place["slug"],
            destination_slug=destination_place["slug"],
            depart_date=anchor,
            return_date=return_anchor,
            currency=currency,
            market=market,
        )
        try:
            snapshot = scrape_kiwi_snapshot_text(url)
        except FlightLiveError as exc:
            errors.append(str(exc))
            continue

        all_offers.extend(
            parse_kiwi_price_buttons(
                snapshot,
                default_origin=origin_place["iata"],
                default_destination=destination_place["iata"],
                month_hint=anchor,
                include_return=trip_type == "roundtrip",
            ),
        )

    if len(all_offers) == 0 and len(errors) > 0:
        raise FlightLiveError(errors[0])

    deduped: dict[tuple[date, date | None, float, str], PlannerOffer] = {}
    for offer in all_offers:
        deduped[(offer.depart_date, offer.return_date, offer.price, offer.currency)] = (
            offer
        )

    return sorted(
        deduped.values(),
        key=lambda item: (
            item.depart_date,
            item.price,
            item.return_date or item.depart_date,
        ),
    )


def build_kiwi_results_url(  # noqa: PLR0913 - public provider surface mirrors the search domain; tests pin the signature
    *,
    origin_slug: str,
    destination_slug: str,
    depart_date: date,
    return_date: date,
    currency: str,
    market: str,
) -> str:
    """Build a Kiwi search-results URL from slugs, dates, and market settings."""
    market_part = market.strip().lower()[:2] if market.strip() else "us"
    query = urlencode(
        {
            "adults": 1,
            "children": 0,
            "infants": 0,
            "cabinClass": "ECONOMY",
            "currency": currency.lower(),
        },
    )
    return (
        f"https://www.kiwi.com/{quote_plus(market_part)}/search/results/"
        f"{quote_plus(origin_slug)}/{quote_plus(destination_slug)}/"
        f"{depart_date.isoformat()}/{return_date.isoformat()}?{query}"
    )


def scrape_kiwi_snapshot_text(url: str) -> str:
    """Scrape a Kiwi results page to snapshot text via agent-browser."""
    _ensure_agent_browser_available()

    _ = _safe_close_agent_browser()
    try:
        _ = _run_agent_browser(["open", url], timeout=150)
        _ = _run_agent_browser(["wait", "--load", "networkidle"], timeout=150)
        return _run_agent_browser(["snapshot", "-i"], timeout=150)
    finally:
        _ = _safe_close_agent_browser()


def parse_kiwi_price_buttons(
    snapshot_text: str,
    *,
    default_origin: str,
    default_destination: str,
    month_hint: date,
    include_return: bool,
) -> list[PlannerOffer]:
    """Parse scraped price buttons into planner offers."""
    offers: list[PlannerOffer] = []

    for raw_line in snapshot_text.splitlines():
        line = raw_line.strip()
        match = _KIWI_PRICE_BUTTON_RE.search(line)
        if match is None:
            continue

        depart_raw, return_raw, price_raw = match.groups()
        depart_date = _parse_month_day(depart_raw, month_hint=month_hint)
        return_date = _parse_month_day(
            return_raw,
            month_hint=depart_date if depart_date is not None else month_hint,
        )

        if depart_date is None:
            continue

        try:
            price = float(price_raw.replace(",", ""))
        except ValueError:
            continue

        normalized_return = return_date if include_return else None

        offers.append(
            PlannerOffer(
                origin=default_origin,
                destination=default_destination,
                depart_date=depart_date,
                return_date=normalized_return,
                price=price,
                currency="USD",
                transfers=None,
                airline=None,
                source="kiwi_web_scrape",
            ),
        )

    return offers


def _parse_month_day(value: str, *, month_hint: date) -> date | None:
    parts = value.strip().replace(",", "").split()
    if len(parts) != _MONTH_DAY_PARTS:
        return None

    month = _MONTHS.get(parts[0].lower())
    if month is None:
        return None

    try:
        day = int(parts[1])
    except ValueError:
        return None

    year = _infer_year(month=month, month_hint=month_hint)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _infer_year(*, month: int, month_hint: date) -> int:
    year = month_hint.year
    delta = month - month_hint.month
    if delta <= -_SEASON_ROLLOVER_MONTHS:
        return year + 1
    if delta >= _SEASON_ROLLOVER_MONTHS:
        return year - 1
    return year


def _pick_stay_days(*, stay_min: int | None, stay_max: int | None) -> int:
    match (stay_min, stay_max):
        case (None, None):
            return 7
        case (None, max_days):
            return max(1, max_days)
        case (min_days, None):
            return max(1, min_days)
        case (min_days, max_days):
            if max_days < min_days:
                return max(1, min_days)
            return max(1, (min_days + max_days) // 2)


def _search_anchors(start: date, end: date, *, step_days: int) -> list[date]:
    anchors: list[date] = []
    cursor = start

    while cursor <= end:
        anchors.append(cursor)
        cursor = cursor + timedelta(days=step_days)

    if anchors[-1] != end:
        anchors.append(end)

    return anchors


@lru_cache(maxsize=128)
def _lookup_kiwi_place(term: str, *, locale: str) -> dict[str, str]:
    params = {
        "term": term,
        "locale": "en-US" if locale.strip() == "" else locale,
        "location_types": "airport",
        "limit": 5,
        "active_only": "true",
        "sort": "name",
    }

    payload = _http_get_json(_KIWI_LOCATIONS_URL, params=params)
    if not isinstance(payload, Mapping):
        message = "Kiwi locations endpoint returned non-object payload"
        raise FlightLiveError(message)
    data = cast("Mapping[str, object]", payload)
    locations = data.get("locations")
    if not isinstance(locations, list) or not locations:
        message = f"Could not resolve location on Kiwi: {term}"
        raise FlightLiveError(message)
    first_raw = cast("object", locations[0])
    if not isinstance(first_raw, Mapping):
        message = f"Could not parse location payload for: {term}"
        raise FlightLiveError(message)
    first = cast("Mapping[str, object]", first_raw)

    code = first.get("code")
    if not isinstance(code, str) or _IATA_RE.fullmatch(code) is None:
        message = f"Could not resolve IATA code for: {term}"
        raise FlightLiveError(message)

    city = first.get("city")
    city_slug: str | None = None
    if isinstance(city, Mapping):
        city_data = cast("Mapping[str, object]", city)
        raw_city_slug = city_data.get("slug")
        if isinstance(raw_city_slug, str) and raw_city_slug.strip() != "":
            city_slug = raw_city_slug.strip()

    fallback_slug = first.get("slug")
    if city_slug is None:
        if isinstance(fallback_slug, str) and fallback_slug.strip() != "":
            city_slug = fallback_slug.strip()
        else:
            message = f"Could not resolve URL slug for: {term}"
            raise FlightLiveError(message)

    name = first.get("name")
    resolved_name = name if isinstance(name, str) and name.strip() != "" else term

    return {
        "iata": code.upper(),
        "slug": city_slug,
        "name": resolved_name,
    }


@lru_cache(maxsize=1)
def _ensure_agent_browser_available() -> None:
    if shutil.which("nix") is None:
        message = (
            "Kiwi web scraper requires `nix` in PATH. Install Nix, then run: "
            + "nix run github:numtide/llm-agents.nix#agent-browser -- --version"
        )
        raise MissingExecutableError(message)

    version_cmd = ["nix", "run", _AGENT_BROWSER_FLAKE, "--", "--version"]
    try:
        result = subprocess.run(  # noqa: S603 - controlled nix/agent-browser toolchain invocation
            version_cmd,
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except FileNotFoundError as exc:
        message = "`nix` executable is missing. Install Nix and retry."
        raise MissingExecutableError(message) from exc
    except subprocess.TimeoutExpired as exc:
        message = (
            "Timed out while validating agent-browser via nix. "
            + "Check network/Nix setup, then retry."
        )
        raise FlightLiveError(message) from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()[:240]
        message = (
            "agent-browser is unavailable through nix wrapper. "
            + "Run `nix run github:numtide/llm-agents.nix#agent-browser "
            + "-- --version` manually. "
            + f"stderr: {stderr or 'no stderr'}"
        )
        raise FlightLiveError(message)


def _safe_close_agent_browser() -> None:
    try:
        _ = _run_agent_browser(["close"], timeout=45)
    except FlightLiveError:
        return


def _maybe_close_browser(args: list[str]) -> None:
    """Close the browser unless the issued command already closes it."""
    if len(args) == 0 or args[0] != "close":
        _ = _safe_close_agent_browser()


def _run_agent_browser(args: list[str], *, timeout: int) -> str:
    cmd = ["nix", "run", _AGENT_BROWSER_FLAKE, "--", *args]

    last_error: FlightLiveError | None = None
    for attempt in range(2):
        try:
            completed = subprocess.run(  # noqa: S603 - controlled nix/agent-browser toolchain invocation
                cmd,
                check=True,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            message = "`nix` executable is missing. Install Nix and retry."
            raise MissingExecutableError(message) from exc
        except subprocess.TimeoutExpired:
            last_error = FlightLiveError(
                "agent-browser command timed out. "
                + "Retry with a narrower date window or better connectivity."
            )
        except subprocess.CalledProcessError as exc:
            raw_stderr = cast("object", exc.stderr)
            raw_stdout = cast("object", exc.stdout)
            stderr_text = (
                raw_stderr.strip()[:320] if isinstance(raw_stderr, str) else ""
            )
            stdout_text = (
                raw_stdout.strip()[:320] if isinstance(raw_stdout, str) else ""
            )
            diagnostic = stderr_text or stdout_text or "no output"
            transient = "Daemon process exited during startup" in diagnostic
            last_error = FlightLiveError(
                "agent-browser execution failed via nix wrapper. "
                + "Check `nix run github:numtide/llm-agents.nix#agent-browser "
                + "-- --version` and network access. "
                + f"command={' '.join(args)}; output: {diagnostic}"
            )
            if not transient or attempt == 1:
                break
            _maybe_close_browser(args)
        else:
            return completed.stdout
        if attempt == 0:
            _maybe_close_browser(args)
            continue

    if last_error is not None:
        raise last_error
    message = "agent-browser execution failed with unknown error"
    raise FlightLiveError(message)


def _http_get_json(url: str, *, params: Mapping[str, object]) -> object:
    """Fetch a JSON document from a provider endpoint."""
    query = urlencode({key: str(value) for key, value in params.items()})
    request = Request(  # noqa: S310 - Kiwi API client; URL is a module constant plus encoded params
        f"{url}?{query}",
        headers={
            "User-Agent": "flight-live/0.1",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(  # noqa: S310 - Kiwi API client over https
            request, timeout=20
        ) as raw_response:  # pyright: ignore[reportAny] - typeshed types urlopen() as Any
            response = cast("http.client.HTTPResponse", raw_response)
            status = cast("int", getattr(response, "status", 200))
            body = response.read().decode("utf-8", errors="replace")
    except OSError as exc:
        message = f"Network error calling provider {url}: {exc}"
        raise FlightLiveError(message) from exc

    if status >= _HTTP_ERROR_STATUS:
        message = f"HTTP {status} from provider {url}: {body[:200].strip()}"
        raise FlightLiveError(message)

    try:
        return cast("object", json.loads(body))
    except json.JSONDecodeError as exc:
        message = f"Invalid JSON from provider {url}"
        raise FlightLiveError(message) from exc
