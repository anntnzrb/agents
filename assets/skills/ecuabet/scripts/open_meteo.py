#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx>=0.27,<1.0",
# ]
# ///
"""CLI client for Open-Meteo snapshots and live weather context."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

__all__: list[str] = []

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
MIN_LATITUDE = -90
MAX_LATITUDE = 90
MIN_LONGITUDE = -180
MAX_LONGITUDE = 180
TEMP_FREEZING = 2
TEMP_COLD = 8
TEMP_HOT = 30
TEMP_WARM = 26
HIGH_HUMIDITY = 90
COMFORT_GOOD = 75
COMFORT_OK = 55

DEFAULT_CURRENT_FIELDS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_gusts_10m",
]

DEFAULT_HOURLY_FIELDS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_gusts_10m",
]

DEFAULT_DAILY_FIELDS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "wind_speed_10m_max",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_lat_lon(value: str) -> tuple[float, float] | None:
    if "," not in value:
        return None
    left, right = [x.strip() for x in value.split(",", maxsplit=1)]
    try:
        lat = float(left)
        lon = float(right)
    except ValueError:
        return None
    if not (
        MIN_LATITUDE <= lat <= MAX_LATITUDE and MIN_LONGITUDE <= lon <= MAX_LONGITUDE
    ):
        return None
    return lat, lon


def parse_iso_no_tz(value: str) -> datetime:
    text = value.strip().replace(" ", "T")
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        msg = "Invalid --at format. Use 'YYYY-MM-DDTHH:MM' or 'YYYY-MM-DD HH:MM'."
        raise ValueError(msg) from exc


def resolve_location(
    client: httpx.Client,
    location: str | None,
    latitude: float | None,
    longitude: float | None,
    country_code: str | None,
) -> dict[str, Any]:
    if latitude is not None and longitude is not None:
        return {
            "name": None,
            "latitude": latitude,
            "longitude": longitude,
            "country": None,
            "timezone": None,
            "source": "explicit-lat-lon",
        }

    if not location:
        msg = "Pass location as 'lat,lon' or city text, or use --latitude/--longitude."
        raise ValueError(msg)

    lat_lon = parse_lat_lon(location)
    if lat_lon:
        return {
            "name": None,
            "latitude": lat_lon[0],
            "longitude": lat_lon[1],
            "country": None,
            "timezone": None,
            "source": "inline-lat-lon",
        }

    params: dict[str, Any] = {
        "name": location,
        "count": 5,
        "language": "en",
        "format": "json",
    }
    if country_code:
        params["countryCode"] = country_code.upper()

    response = client.get(GEOCODE_URL, params=params)
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results") or []
    if not results:
        msg = f"No location match for '{location}'."
        raise ValueError(msg)

    best = results[0]
    return {
        "name": best.get("name"),
        "admin1": best.get("admin1"),
        "country": best.get("country"),
        "countryCode": best.get("country_code"),
        "latitude": best.get("latitude"),
        "longitude": best.get("longitude"),
        "timezone": best.get("timezone"),
        "source": "geocoding",
        "alternatives": [
            {
                "name": row.get("name"),
                "admin1": row.get("admin1"),
                "country": row.get("country"),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "timezone": row.get("timezone"),
            }
            for row in results[:5]
        ],
    }


def hourly_rows(payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return []

    keys = [k for k in hourly if k != "time"]
    rows = []
    max_len = min(limit, len(times))
    for idx in range(max_len):
        row = {"time": times[idx]}
        for key in keys:
            values = hourly.get(key) or []
            row[key] = values[idx] if idx < len(values) else None
        rows.append(row)
    return rows


def nearest_hour(payload: dict[str, Any], at_time: datetime) -> dict[str, Any] | None:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None

    keys = [k for k in hourly if k != "time"]
    parsed = []
    for i, ts in enumerate(times):
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            continue
        parsed.append((i, dt))

    if not parsed:
        return None

    best_idx, _ = min(parsed, key=lambda x: abs((x[1] - at_time).total_seconds()))
    row = {"time": times[best_idx]}
    for key in keys:
        values = hourly.get(key) or []
        row[key] = values[best_idx] if best_idx < len(values) else None
    return row


def comfort_index(current: dict[str, Any]) -> dict[str, Any]:
    temp = current.get("temperature_2m")
    wind = current.get("wind_speed_10m")
    rain = current.get("precipitation")
    humidity = current.get("relative_humidity_2m")

    if not isinstance(temp, (int, float)):
        return {}

    score = 100.0
    if temp < TEMP_FREEZING:
        score -= 35
    elif temp < TEMP_COLD:
        score -= 15
    elif temp > TEMP_HOT:
        score -= 25
    elif temp > TEMP_WARM:
        score -= 10

    if isinstance(wind, (int, float)):
        score -= max(0.0, wind - 20) * 0.8
    if isinstance(rain, (int, float)):
        score -= min(30.0, rain * 20)
    if isinstance(humidity, (int, float)) and humidity > HIGH_HUMIDITY:
        score -= 7

    score = max(0.0, min(100.0, score))
    return {
        "score": round(score, 1),
        "label": (
            "good"
            if score >= COMFORT_GOOD
            else ("ok" if score >= COMFORT_OK else "poor")
        ),
    }


def build_snapshot(
    payload: dict[str, Any],
    resolved: dict[str, Any],
    at_time: datetime | None,
    *,
    include_raw: bool,
    hourly_limit: int,
) -> dict[str, Any]:
    current = payload.get("current") or {}
    units = {
        "current": payload.get("current_units") or {},
        "hourly": payload.get("hourly_units") or {},
        "daily": payload.get("daily_units") or {},
    }

    snapshot: dict[str, Any] = {
        "fetchedAtUtc": utc_now_iso(),
        "source": {
            "provider": "open-meteo",
            "forecastEndpoint": FORECAST_URL,
            "geocodingEndpoint": GEOCODE_URL,
        },
        "location": {
            "inputResolution": resolved,
            "forecastLatitude": payload.get("latitude"),
            "forecastLongitude": payload.get("longitude"),
            "elevation": payload.get("elevation"),
            "timezone": payload.get("timezone"),
            "timezoneAbbreviation": payload.get("timezone_abbreviation"),
            "utcOffsetSeconds": payload.get("utc_offset_seconds"),
        },
        "current": current,
        "units": units,
        "computed": {
            "comfort": comfort_index(current),
        },
        "hourlySample": hourly_rows(payload, max(0, hourly_limit)),
        "daily": payload.get("daily") or {},
    }

    if at_time is not None:
        snapshot["atTime"] = {
            "requestedLocal": at_time.isoformat(),
            "nearestHourly": nearest_hour(payload, at_time),
        }

    if include_raw:
        snapshot["raw"] = {
            "forecast": payload,
        }

    return snapshot


def write_snapshot(
    snapshot: dict[str, Any],
    output: Path,
    iteration: int,
    *,
    watch_mode: bool,
) -> Path:
    output = output.expanduser()
    if watch_mode:
        output.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = output / f"open_meteo_{ts}_{iteration:04d}.json"
    else:
        target = output
        target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Open-Meteo weather by location or coordinates."
    )
    parser.add_argument(
        "location",
        nargs="?",
        help="City name or 'lat,lon'. Optional if --latitude and --longitude are set.",
    )
    parser.add_argument("--latitude", type=float)
    parser.add_argument("--longitude", type=float)
    parser.add_argument(
        "--country-code", help="Optional geocoding country filter, e.g. ES"
    )
    parser.add_argument(
        "--at",
        help="Optional local time to inspect nearest forecast hour (YYYY-MM-DDTHH:MM).",
    )
    parser.add_argument("--hourly-limit", type=int, default=12)
    parser.add_argument(
        "--timezone",
        default="auto",
        help="Forecast timezone parameter, default 'auto'.",
    )
    parser.add_argument("--forecast-days", type=int, default=3)
    parser.add_argument("--past-days", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--watch", type=float, default=0)
    parser.add_argument("--max-iterations", type=int, default=0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-raw", action="store_true")
    parser.add_argument("--compact", action="store_true")
    return parser.parse_args()


def main() -> int:  # noqa: C901,PLR0911,PLR0912
    args = parse_args()
    if args.watch < 0:
        print("error: --watch must be >= 0", file=sys.stderr)
        return 2
    if args.max_iterations < 0:
        print("error: --max-iterations must be >= 0", file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print("error: --timeout must be > 0", file=sys.stderr)
        return 2
    if (args.latitude is None) ^ (args.longitude is None):
        print("error: use both --latitude and --longitude together", file=sys.stderr)
        return 2

    at_time = None
    if args.at:
        try:
            at_time = parse_iso_no_tz(args.at)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    client = httpx.Client(
        timeout=args.timeout,
        headers={"Accept": "application/json", "User-Agent": "open-meteo-cli/1.0"},
    )

    try:
        resolved = resolve_location(
            client=client,
            location=args.location,
            latitude=args.latitude,
            longitude=args.longitude,
            country_code=args.country_code,
        )

        watch_mode = args.watch > 0
        iteration = 0

        while True:
            iteration += 1
            params = {
                "latitude": resolved["latitude"],
                "longitude": resolved["longitude"],
                "current": ",".join(DEFAULT_CURRENT_FIELDS),
                "hourly": ",".join(DEFAULT_HOURLY_FIELDS),
                "daily": ",".join(DEFAULT_DAILY_FIELDS),
                "timezone": args.timezone,
                "forecast_days": max(1, args.forecast_days),
                "past_days": max(0, args.past_days),
            }
            response = client.get(FORECAST_URL, params=params)
            response.raise_for_status()
            payload = response.json()

            snapshot = build_snapshot(
                payload=payload,
                resolved=resolved,
                at_time=at_time,
                include_raw=not args.no_raw,
                hourly_limit=args.hourly_limit,
            )

            if args.output:
                path = write_snapshot(
                    snapshot, args.output, iteration, watch_mode=watch_mode
                )
                print(path)
            elif args.compact:
                print(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")))
            else:
                print(json.dumps(snapshot, ensure_ascii=False, indent=2))

            if not watch_mode:
                break
            if args.max_iterations and iteration >= args.max_iterations:
                break
            time.sleep(args.watch)

        return 0  # noqa: TRY300
    except httpx.HTTPStatusError as exc:
        msg = (
            "error: upstream returned HTTP "
            f"{exc.response.status_code} for {exc.request.url}"
        )
        print(msg, file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"error: network error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
