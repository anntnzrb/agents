from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Mapping
from datetime import date, timedelta
from functools import lru_cache
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

from .models import FlightLiveError, MissingExecutableError, PlannerOffer, ResolvedPlace

_IATA_RE = re.compile(r"^[A-Za-z]{3}$")

_KIWI_LOCATIONS_URL = "https://api.skypicker.com/locations"
_AGENT_BROWSER_FLAKE = "github:numtide/llm-agents.nix#agent-browser"

_KIWI_PRICE_BUTTON_RE = re.compile(
    r'button\s+"\s*([A-Za-z]{3,9}\s+\d{1,2})\s*[-–]\s*([A-Za-z]{3,9}\s+\d{1,2})\s*\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)',
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


def resolve_place(
    query: str,
    *,
    locale: str,
    client: object | None = None,
) -> ResolvedPlace:
    del client
    clean = " ".join(query.strip().split())
    if clean == "":
        raise FlightLiveError("Place query must be non-empty")

    place = _lookup_kiwi_place(clean, locale=locale)
    return ResolvedPlace(
        query=clean,
        iata=place["iata"],
        name=place["name"],
        resolved_via_autocomplete=True,
    )


def fetch_kiwi_web_calendar(
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


def build_kiwi_results_url(
    *,
    origin_slug: str,
    destination_slug: str,
    depart_date: date,
    return_date: date,
    currency: str,
    market: str,
) -> str:
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
    _ensure_agent_browser_available()

    _safe_close_agent_browser()
    try:
        _run_agent_browser(["open", url], timeout=150)
        _run_agent_browser(["wait", "--load", "networkidle"], timeout=150)
        return _run_agent_browser(["snapshot", "-i"], timeout=150)
    finally:
        _safe_close_agent_browser()


def parse_kiwi_price_buttons(
    snapshot_text: str,
    *,
    default_origin: str,
    default_destination: str,
    month_hint: date,
    include_return: bool,
) -> list[PlannerOffer]:
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
    if len(parts) != 2:
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
    if delta <= -7:
        return year + 1
    if delta >= 7:
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
        raise FlightLiveError("Kiwi locations endpoint returned non-object payload")

    locations = payload.get("locations")
    if not isinstance(locations, list) or len(locations) == 0:
        raise FlightLiveError(f"Could not resolve location on Kiwi: {term}")

    first = locations[0]
    if not isinstance(first, Mapping):
        raise FlightLiveError(f"Could not parse location payload for: {term}")

    code = first.get("code")
    if not isinstance(code, str) or _IATA_RE.fullmatch(code) is None:
        raise FlightLiveError(f"Could not resolve IATA code for: {term}")

    city = first.get("city")
    city_slug: str | None = None
    if isinstance(city, Mapping):
        raw_city_slug = city.get("slug")
        if isinstance(raw_city_slug, str) and raw_city_slug.strip() != "":
            city_slug = raw_city_slug.strip()

    fallback_slug = first.get("slug")
    if city_slug is None:
        if isinstance(fallback_slug, str) and fallback_slug.strip() != "":
            city_slug = fallback_slug.strip()
        else:
            raise FlightLiveError(f"Could not resolve URL slug for: {term}")

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
        raise MissingExecutableError(
            "Kiwi web scraper requires `nix` in PATH. Install Nix, then run: "
            "nix run github:numtide/llm-agents.nix#agent-browser -- --version",
        )

    try:
        result = subprocess.run(
            ["nix", "run", _AGENT_BROWSER_FLAKE, "--", "--version"],
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except FileNotFoundError as exc:
        raise MissingExecutableError(
            "`nix` executable is missing. Install Nix and retry.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FlightLiveError(
            "Timed out while validating agent-browser via nix. Check network/Nix setup, then retry.",
        ) from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()[:240]
        raise FlightLiveError(
            "agent-browser is unavailable through nix wrapper. "
            "Run `nix run github:numtide/llm-agents.nix#agent-browser -- --version` manually. "
            f"stderr: {stderr or 'no stderr'}",
        )


def _safe_close_agent_browser() -> None:
    try:
        _run_agent_browser(["close"], timeout=45)
    except FlightLiveError:
        return


def _run_agent_browser(args: list[str], *, timeout: int) -> str:
    cmd = ["nix", "run", _AGENT_BROWSER_FLAKE, "--", *args]

    last_error: FlightLiveError | None = None
    for attempt in range(2):
        try:
            completed = subprocess.run(
                cmd,
                check=True,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return completed.stdout
        except FileNotFoundError as exc:
            raise MissingExecutableError(
                "`nix` executable is missing. Install Nix and retry.",
            ) from exc
        except subprocess.TimeoutExpired:
            last_error = FlightLiveError(
                "agent-browser command timed out. Retry with a narrower date window or better connectivity.",
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()[:320]
            stdout = (exc.stdout or "").strip()[:320]
            diagnostic = stderr or stdout or "no output"
            transient = "Daemon process exited during startup" in diagnostic
            last_error = FlightLiveError(
                "agent-browser execution failed via nix wrapper. "
                "Check `nix run github:numtide/llm-agents.nix#agent-browser -- --version` and network access. "
                f"command={' '.join(args)}; output: {diagnostic}",
            )
            if not transient or attempt == 1:
                break
            if len(args) == 0 or args[0] != "close":
                _safe_close_agent_browser()
            continue

        if attempt == 0:
            if len(args) == 0 or args[0] != "close":
                _safe_close_agent_browser()
            continue

    if last_error is not None:
        raise last_error
    raise FlightLiveError("agent-browser execution failed with unknown error")


def _http_get_json(url: str, *, params: Mapping[str, object]) -> object:
    query = urlencode({key: str(value) for key, value in params.items()})
    request = Request(
        f"{url}?{query}",
        headers={
            "User-Agent": "flight-live/0.1",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310
            status = getattr(response, "status", 200)
            body = response.read().decode("utf-8", errors="replace")
    except OSError as exc:
        raise FlightLiveError(f"Network error calling provider {url}: {exc}") from exc

    if status >= 400:
        raise FlightLiveError(
            f"HTTP {status} from provider {url}: {body[:200].strip()}",
        )

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise FlightLiveError(f"Invalid JSON from provider {url}") from exc
