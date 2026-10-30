"""Open-Meteo forecasts and AviationWeather observations."""

import json
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated, Literal, TypedDict, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import click
import httpx2
import typer
from pydantic import BaseModel, Field, ValidationError
from rich.console import Console
from rich.table import Table

LAT_LIMIT = 90
LON_LIMIT = 180
MAX_HOURS = 384

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class Location:
    """Resolved location used by forecast and observation logic."""

    name: str | None = None
    admin1: str | None = None
    country: str | None = None
    country_code: str | None = None
    latitude: float
    longitude: float


class GeocodedLocation(BaseModel):
    """Untrusted geocoding result."""

    name: str | None = None
    admin1: str | None = None
    country: str | None = None
    country_code: str | None = None
    latitude: float
    longitude: float


class Geocoding(BaseModel):
    """Geocoding response."""

    results: list[GeocodedLocation] = []


class Hourly(BaseModel):
    """Hourly forecast columns."""

    time: list[str]
    temperature_2m: list[float | None]
    precipitation: list[float | None]
    precipitation_probability: list[float | None]
    weather_code: list[int | None]


class Forecast(BaseModel):
    """Forecast response."""

    latitude: float
    longitude: float
    timezone: str
    utc_offset_seconds: int
    hourly: Hourly | None = None


@dataclass(frozen=True, slots=True)
class Station:
    """Airport station used by the nearest-station calculation."""

    icao_id: str
    lat: float
    lon: float
    site_type: list[str]


class StationResponse(BaseModel):
    """Untrusted airport station response."""

    icao_id: str = Field(alias="icaoId")
    site: str | None = None
    lat: float
    lon: float
    site_type: list[str] = Field(default_factory=list, alias="siteType")


class Metar(BaseModel):
    """Decoded METAR observation."""

    icao_id: str = Field(alias="icaoId")
    report_time: str = Field(alias="reportTime")
    lat: float
    lon: float
    name: str | None = None
    temp: float | None = None
    dewp: float | None = None
    wdir: int | str | None = None
    wspd: float | None = None
    visib: float | str | None = None
    wx_string: str | None = Field(default=None, alias="wxString")
    raw_ob: str = Field(alias="rawOb")


class WeatherError(Exception):
    """Actionable external-service error."""


def get(base: str, path: str, params: dict[str, str | int | float]) -> object:
    """Request and decode a service response."""
    try:
        response = httpx2.get(
            base.rstrip("/") + path,
            params=params,
            headers={"User-Agent": "weather-live/0.1"},
            timeout=20,
            follow_redirects=True,
        )
        if response.status_code == HTTPStatus.NO_CONTENT:
            return []
        if response.is_error:
            try:
                body = cast("object", response.json())
                reason = (
                    cast("dict[str, object]", body).get("reason")
                    if isinstance(body, dict)
                    else None
                )
            except ValueError:
                reason = None
            raise WeatherError(
                f"Service returned HTTP {response.status_code}: "
                + f"{reason or 'try again later'}"
            )
        payload = cast("object", response.json())
    except httpx2.HTTPError as exc:
        raise WeatherError(f"Network request failed: {exc}") from exc
    except ValueError as exc:
        raise WeatherError("Service returned invalid JSON") from exc
    return payload


def geo_base() -> str:
    """Return the geocoding service base URL."""
    return os.environ.get("WEATHER_GEOCODE_URL", "https://geocoding-api.open-meteo.com")


def forecast_base() -> str:
    """Return the forecast service base URL."""
    return os.environ.get("WEATHER_FORECAST_URL", "https://api.open-meteo.com")


def awc_base() -> str:
    """Return the aviation service base URL."""
    return os.environ.get("WEATHER_AWC_URL", "https://aviationweather.gov")


def location(
    place: str | None,
    country: str | None,
    lat: float | None,
    lon: float | None,
    station: str | None = None,
) -> Location | None:
    """Validate selectors and resolve the requested location."""
    if country and (not place or not re.fullmatch(r"[A-Za-z]{2}", country)):
        raise click.UsageError(
            "--country requires --place and a two-letter country code"
        )
    if (lat is None) != (lon is None) or sum(
        (bool(place), lat is not None, bool(station))
    ) != 1:
        raise click.UsageError(
            "Choose exactly one of --place, --lat with --lon, or --station"
        )
    if lat is not None and lon is not None:
        if (
            not math.isfinite(lat)
            or not math.isfinite(lon)
            or not -LAT_LIMIT <= lat <= LAT_LIMIT
            or not -LON_LIMIT <= lon <= LON_LIMIT
        ):
            raise click.UsageError(
                "Coordinates must be finite latitude [-90,90] and longitude [-180,180]"
            )
        return Location(latitude=lat, longitude=lon)
    if place:
        params: dict[str, str | int | float] = {
            "name": place,
            "count": 10,
            "language": "en",
            "format": "json",
        }
        if country:
            params["countryCode"] = country.upper()
        result = Geocoding.model_validate(get(geo_base(), "/v1/search", params))
        matches = [
            item
            for item in result.results
            if not country or item.country_code == country.upper()
        ]
        if not matches:
            raise WeatherError(
                f"No location found for {place}; try a different place or country"
            )
        match = matches[0]
        return Location(
            name=match.name,
            admin1=match.admin1,
            country=match.country,
            country_code=match.country_code,
            latitude=match.latitude,
            longitude=match.longitude,
        )
    return None


def distance(lat: float, lon: float, other_lat: float, other_lon: float) -> float:
    """Calculate great-circle distance in kilometers."""
    a, b = math.radians(lat), math.radians(other_lat)
    dlat = b - a
    dlon = math.radians(other_lon - lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1, h)))


def nearest(loc: Location) -> Station:
    """Find the nearest METAR station in widening bounding boxes."""
    for span in (0.5, 1.5, 3.0):
        low, high = loc.longitude - span, loc.longitude + span
        intervals = [(max(-180.0, low), min(180.0, high))]
        if low < -LON_LIMIT:
            intervals.append((low + 360, 180.0))
        if high > LON_LIMIT:
            intervals.append((-180.0, high - 360))
        stations: list[Station] = []
        for left, right in intervals:
            bbox = (
                f"{max(-90, loc.latitude - span)},{left},"
                f"{min(90, loc.latitude + span)},{right}"
            )
            raw = get(
                awc_base(), "/api/data/stationinfo", {"bbox": bbox, "format": "json"}
            )
            if not isinstance(raw, list):
                raise WeatherError("Station service returned an invalid response")
            for item in cast("list[object]", raw):
                station = StationResponse.model_validate(item)
                if "METAR" in station.site_type:
                    stations.append(
                        Station(
                            icao_id=station.icao_id,
                            lat=station.lat,
                            lon=station.lon,
                            site_type=station.site_type,
                        )
                    )
        if stations:
            return min(
                stations,
                key=lambda s: distance(loc.latitude, loc.longitude, s.lat, s.lon),
            )
    raise WeatherError(
        "No METAR station found within the final ±3 degree search; specify --station"
    )


class PresentWeather(TypedDict):
    """Weather actually observed at the station and in its vicinity."""

    rain: bool
    intensity: Literal["light", "moderate", "heavy"] | None
    shower: bool
    thunderstorm: bool
    drizzle: bool
    vicinity_showers: bool


def present_weather(wx: str | None) -> PresentWeather:
    """Decode only the upstream present-weather field."""
    tokens = (wx or "").upper().split()
    vicinity = any(token.startswith("VC") and "SH" in token for token in tokens)
    actual = [token for token in tokens if not token.startswith("VC")]
    rain_tokens = [token for token in actual if "RA" in token]
    intensity: Literal["light", "moderate", "heavy"] | None = None
    if rain_tokens:
        intensity = (
            "heavy"
            if any(t.startswith("+") for t in rain_tokens)
            else "light"
            if all(t.startswith("-") for t in rain_tokens)
            else "moderate"
        )
    return {
        "rain": bool(rain_tokens),
        "intensity": intensity,
        "shower": any("SH" in t for t in actual),
        "thunderstorm": any("TS" in t for t in actual),
        "drizzle": any("DZ" in t for t in actual),
        "vicinity_showers": vicinity,
    }


class LocationOutput(TypedDict):
    """Resolved location presented to the user."""

    name: str | None
    admin1: str | None
    country: str | None
    country_code: str | None
    latitude: float
    longitude: float


def location_output(loc: Location) -> LocationOutput:
    """Convert a resolved location to its public shape."""
    return {
        "name": loc.name,
        "admin1": loc.admin1,
        "country": loc.country,
        "country_code": loc.country_code,
        "latitude": loc.latitude,
        "longitude": loc.longitude,
    }


class ForecastRow(TypedDict):
    """One forecast hour."""

    time_local: str
    temp_c: float | None
    precip_mm: float | None
    pop_pct: float | None
    weather_code: int | None


class Coordinates(TypedDict):
    """Coordinates of a model grid cell."""

    latitude: float
    longitude: float


class ForecastOutput(TypedDict):
    """JSON forecast output."""

    location: LocationOutput
    model: str
    timezone: str
    utc_offset_seconds: int
    grid_coordinates: Coordinates
    hourly: list[ForecastRow]
    caveats: list[str]


class StationOutput(TypedDict):
    """Airport identification."""

    icao: str
    name: str | None
    latitude: float
    longitude: float


class ObservationOutput(TypedDict):
    """JSON airport observation output."""

    station: StationOutput
    location: LocationOutput | None
    distance_km: float | None
    time_utc: str
    time_local: str
    timezone: str
    temp_c: float | None
    dewpoint_c: float | None
    wind_direction: int | str | None
    wind_speed_kt: float | None
    visibility_sm: float | str | None
    present_weather: PresentWeather
    wx_string: str | None
    raw_ob: str


def output_forecast(data: ForecastOutput, *, text: bool) -> None:
    """Print a forecast as JSON or a readable hourly table."""
    if not text:
        print(json.dumps(data, ensure_ascii=False))
        return
    console = Console()
    loc = data["location"]
    console.print(
        f"{loc['name'] or 'Coordinates'}, {loc['admin1'] or ''} "
        + f"{loc['country'] or ''} ({loc['latitude']}, {loc['longitude']}) "
        + f"| {data['model']} | {data['timezone']}"
    )
    table = Table("Local time", "Temp °C", "Precip mm", "Chance %", "Code")
    for row in data["hourly"]:
        table.add_row(
            *(
                str(row[key]) if row[key] is not None else "—"
                for key in (
                    "time_local",
                    "temp_c",
                    "precip_mm",
                    "pop_pct",
                    "weather_code",
                )
            )
        )
    console.print(table)
    for caveat in data["caveats"]:
        console.print(caveat)


def output_observation(data: ObservationOutput, *, text: bool) -> None:
    """Print an observation as JSON or readable station details."""
    if not text:
        print(json.dumps(data, ensure_ascii=False))
        return
    console = Console()
    station = data["station"]
    console.print(
        f"{station['icao']} {station['name']} | "
        + f"{data['time_local']} ({data['timezone']})"
    )
    console.print(
        f"Distance: {data['distance_km']} km | Temperature: {data['temp_c']} °C | "
        + f"Dew point: {data['dewpoint_c']} °C"
    )
    console.print(
        f"Wind: {data['wind_direction']} at {data['wind_speed_kt']} kt | "
        + f"Visibility: {data['visibility_sm']} mi"
    )
    console.print(
        f"Present weather: {data['wx_string'] or 'none'} | {data['present_weather']}"
    )
    console.print(f"METAR: {data['raw_ob']}")


@app.command()
def forecast(  # noqa: PLR0913, PLR0917 - CLI options.
    place: Annotated[str | None, typer.Option()] = None,
    country: Annotated[str | None, typer.Option()] = None,
    lat: Annotated[float | None, typer.Option()] = None,
    lon: Annotated[float | None, typer.Option()] = None,
    hours: Annotated[int, typer.Option()] = 48,
    model: Annotated[str, typer.Option()] = "icon_seamless",
    text: Annotated[bool, typer.Option("--text")] = False,  # noqa: FBT002 - CLI flag.
) -> None:
    """Get hourly forecasts for a place or coordinates."""
    if not 1 <= hours <= MAX_HOURS:
        raise click.UsageError("--hours must be between 1 and 384")
    if not model.strip() or "," in model:
        raise click.UsageError("--model must be one model ID")
    loc = location(place, country, lat, lon)
    if loc is None:
        raise click.UsageError("A location is required")
    data = Forecast.model_validate(
        get(
            forecast_base(),
            "/v1/forecast",
            {
                "latitude": loc.latitude,
                "longitude": loc.longitude,
                "models": model,
                "hourly": (
                    "temperature_2m,precipitation,"
                    "precipitation_probability,weather_code"
                ),
                "timezone": "auto",
                "forecast_hours": hours,
            },
        )
    )
    h = data.hourly
    if (
        h is None
        or len(
            {
                len(h.time),
                len(h.temperature_2m),
                len(h.precipitation),
                len(h.precipitation_probability),
                len(h.weather_code),
            }
        )
        != 1
    ):
        raise WeatherError("Forecast service returned mismatched hourly data")
    rows: list[ForecastRow] = [
        {
            "time_local": t,
            "temp_c": temp,
            "precip_mm": precip,
            "pop_pct": pop,
            "weather_code": code,
        }
        for t, temp, precip, pop, code in zip(
            h.time,
            h.temperature_2m,
            h.precipitation,
            h.precipitation_probability,
            h.weather_code,
            strict=True,
        )
    ]
    caveats = (
        [
            (
                "AIFS precipitation repeats in six-hour blocks; hourly timing "
                "is unavailable. Precipitation probability is null."
            )
        ]
        if model == "ecmwf_aifs025_single"
        else []
    )
    output_forecast(
        {
            "location": location_output(loc),
            "model": model,
            "timezone": data.timezone,
            "utc_offset_seconds": data.utc_offset_seconds,
            "grid_coordinates": {
                "latitude": data.latitude,
                "longitude": data.longitude,
            },
            "hourly": rows,
            "caveats": caveats,
        },
        text=text,
    )


@app.command()
def now(  # noqa: PLR0913, PLR0917 - CLI options.
    place: Annotated[str | None, typer.Option()] = None,
    country: Annotated[str | None, typer.Option()] = None,
    lat: Annotated[float | None, typer.Option()] = None,
    lon: Annotated[float | None, typer.Option()] = None,
    station: Annotated[str | None, typer.Option()] = None,
    text: Annotated[bool, typer.Option("--text")] = False,  # noqa: FBT002 - CLI flag.
) -> None:
    """Get the latest decoded airport METAR."""
    if station and not re.fullmatch(r"[A-Za-z]{4}", station):
        raise click.UsageError("--station must be a four-letter ICAO identifier")
    loc = location(place, country, lat, lon, station)
    chosen = nearest(loc) if loc else None
    icao = chosen.icao_id if chosen else station.upper() if station else ""
    raw = get(
        awc_base(), "/api/data/metar", {"ids": icao, "format": "json", "hours": 1}
    )
    if not isinstance(raw, list) or not raw:
        raise WeatherError(
            f"No recent METAR for {icao}; check the station or try again later"
        )
    observations = [Metar.model_validate(item) for item in cast("list[object]", raw)]
    obs = max(
        observations,
        key=lambda item: parse_time(item.report_time),
    )
    timezone = Forecast.model_validate(
        get(
            forecast_base(),
            "/v1/forecast",
            {
                "latitude": obs.lat,
                "longitude": obs.lon,
                "timezone": "auto",
                "forecast_days": 1,
            },
        )
    ).timezone
    stamp = parse_time(obs.report_time)
    local = stamp.astimezone(ZoneInfo(timezone)).isoformat()
    output_observation(
        {
            "station": {
                "icao": obs.icao_id,
                "name": obs.name,
                "latitude": obs.lat,
                "longitude": obs.lon,
            },
            "location": location_output(loc) if loc else None,
            "distance_km": round(
                distance(loc.latitude, loc.longitude, obs.lat, obs.lon), 1
            )
            if loc
            else None,
            "time_utc": stamp.isoformat(),
            "time_local": local,
            "timezone": timezone,
            "temp_c": obs.temp,
            "dewpoint_c": obs.dewp,
            "wind_direction": obs.wdir,
            "wind_speed_kt": obs.wspd,
            "visibility_sm": obs.visib,
            "present_weather": present_weather(obs.wx_string),
            "wx_string": obs.wx_string,
            "raw_ob": obs.raw_ob,
        },
        text=text,
    )


def parse_time(value: str) -> datetime:
    """Parse an observation timestamp and normalize it to UTC."""
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("timezone missing")
        return stamp.astimezone(UTC)
    except ValueError as exc:
        raise WeatherError(
            "METAR service returned an invalid observation time"
        ) from exc


def main() -> int:
    """Run the CLI with one-line error messages."""
    try:
        app(standalone_mode=False)
    except click.ClickException as exc:
        print(f"Error: {exc.format_message()}".replace("\n", " "), file=sys.stderr)
        return 2
    except ValidationError:
        print(
            "Error: Service returned an invalid response; try again later",
            file=sys.stderr,
        )
        return 1
    except (WeatherError, ValueError, ZoneInfoNotFoundError) as exc:
        print(f"Error: {exc}".replace("\n", " "), file=sys.stderr)
        return 1
    return 0
