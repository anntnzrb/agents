"""Behavioral and pure weather contracts."""

import json
import os
from typing import cast

import pytest
import weather_live
from pydantic import TypeAdapter
from weather_live import (
    ForecastOutput,
    Location,
    Metar,
    ObservationOutput,
    distance,
    nearest,
    present_weather,
)

from tests.support import Params, fixture, run, service


def test_now_and_contract() -> None:
    def handler(path: str, _params: Params) -> tuple[int, bytes]:
        if path.endswith("search"):
            return 200, fixture("geocode_guayaquil")
        if path.endswith("stationinfo"):
            return 200, fixture("stationinfo_gye")
        if path.endswith("metar"):
            return 200, fixture("metar_segu")
        return 200, fixture("forecast_icon")

    with service(handler) as (requests, env):
        result = run(env, "now", "--place", "Guayaquil", "--country", "EC")
    assert result.returncode == 0, result.stderr
    data = TypeAdapter(ObservationOutput).validate_json(result.stdout)
    assert data["station"]["icao"] == "SEGU"
    assert data["time_local"].endswith("-05:00")
    assert data["present_weather"]["vicinity_showers"] is True
    assert data["present_weather"]["rain"] is False
    assert data["visibility_sm"] == "6+"
    assert data["distance_km"] is not None
    assert data["distance_km"] > 0
    assert requests[0][1]["countryCode"] == ["EC"]
    assert requests[1][1]["bbox"] == ["-2.69616,-80.38621,-1.69616,-79.38621"]
    assert requests[2][1] == {"ids": ["SEGU"], "format": ["json"], "hours": ["1"]}
    assert all(ua == "weather-live/0.1" for _, _, ua in requests)


def test_station_variable_wind_numeric_visibility() -> None:
    data = TypeAdapter(list[Metar]).validate_json(fixture("metar_segu"))
    data[0].wdir, data[0].visib = "VRB", 4.0

    def handler(path: str, _params: Params) -> tuple[int, bytes]:
        return (
            (200, TypeAdapter(list[Metar]).dump_json(data, by_alias=True))
            if path.endswith("metar")
            else (200, fixture("forecast_icon"))
        )

    with service(handler) as (_, env):
        result = run(env, "now", "--station", "SEGU")
    assert result.returncode == 0, result.stderr
    obs = TypeAdapter(ObservationOutput).validate_json(result.stdout)
    assert obs["wind_direction"] == "VRB"
    assert obs["visibility_sm"] == 4
    assert obs["distance_km"] is None


@pytest.mark.parametrize(
    ("case", "args", "status", "part"),
    [
        ("miss", ["forecast", "--place", "zzqqxx"], 200, "No location found"),
        ("metar", ["now", "--station", "XXXX"], 204, "No recent METAR"),
        (
            "invalid",
            ["forecast", "--lat", "0", "--lon", "0", "--model", "nope"],
            400,
            "invalid String value nope",
        ),
        ("server", ["forecast", "--lat", "0", "--lon", "0"], 503, "HTTP 503"),
    ],
)
def test_external_errors(case: str, args: list[str], status: int, part: str) -> None:
    payload = {
        "miss": fixture("geocode_miss"),
        "metar": b"",
        "invalid": fixture("forecast_invalid"),
        "server": fixture("server_error"),
    }[case]
    with service(lambda _path, _params: (status, payload)) as (_, env):
        result = run(env, *args)
    assert result.returncode == 1
    assert part in result.stderr
    assert len(result.stderr.splitlines()) == 1


def test_aifs() -> None:
    with service(lambda _path, _params: (200, fixture("forecast_aifs"))) as (
        requests,
        env,
    ):
        result = run(
            env,
            "forecast",
            "--lat",
            "-2.19616",
            "--lon",
            "-79.88621",
            "--model",
            "ecmwf_aifs025_single",
        )
    assert result.returncode == 0, result.stderr
    data = TypeAdapter(ForecastOutput).validate_json(result.stdout)
    assert all(row["pop_pct"] is None for row in data["hourly"])
    assert "six-hour" in data["caveats"][0]
    assert requests[0][1]["models"] == ["ecmwf_aifs025_single"]


@pytest.mark.parametrize(
    "args",
    [
        ["forecast"],
        ["forecast", "--lat", "1"],
        ["now", "--station", "SEGU", "--place", "x"],
        ["forecast", "--lat", "91", "--lon", "0"],
        ["forecast", "--lat", "0", "--lon", "0", "--hours", "0"],
    ],
)
def test_invalid_inputs(args: list[str]) -> None:
    result = run(os.environ, *args)
    assert result.returncode == 2
    assert len(result.stderr.splitlines()) == 1


@pytest.mark.parametrize(
    ("wx", "rain", "intensity", "shower", "thunder", "drizzle", "vicinity"),
    [
        ("VCSH", False, None, False, False, False, True),
        ("-RA", True, "light", False, False, False, False),
        ("RA", True, "moderate", False, False, False, False),
        ("+RA", True, "heavy", False, False, False, False),
        ("SHRA", True, "moderate", True, False, False, False),
        ("-SHRA", True, "light", True, False, False, False),
        ("TSRA", True, "moderate", False, True, False, False),
        ("+TSRA", True, "heavy", False, True, False, False),
        ("DZ", False, None, False, False, True, False),
        ("BR", False, None, False, False, False, False),
        ("", False, None, False, False, False, False),
        (None, False, None, False, False, False, False),
        ("VCSH -RA", True, "light", False, False, False, True),
    ],
)
def test_weather(
    wx: str | None,
    rain: bool,
    intensity: str | None,
    shower: bool,
    thunder: bool,
    drizzle: bool,
    vicinity: bool,
) -> None:
    assert present_weather(wx) == {
        "rain": rain,
        "intensity": intensity,
        "shower": shower,
        "thunderstorm": thunder,
        "drizzle": drizzle,
        "vicinity_showers": vicinity,
    }


def test_distance_and_widening(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str | int | float] = []

    def get(_base: str, _path: str, params: dict[str, str | int | float]) -> object:
        calls.append(params["bbox"])
        return (
            []
            if len(calls) < 3
            else cast("object", json.loads(fixture("stationinfo_gye")))
        )

    monkeypatch.setattr(weather_live, "get", get)
    loc = Location(latitude=-2.19616, longitude=-79.88621)
    assert nearest(loc).icao_id == "SEGU"
    assert len(calls) == 3
    assert 4 < distance(loc.latitude, loc.longitude, -2.158, -79.884) < 5


def test_no_station_after_widening() -> None:
    with service(lambda _path, _params: (204, b"")) as (requests, env):
        result = run(env, "now", "--lat", "0", "--lon", "0")
    assert result.returncode == 1
    assert "No METAR station" in result.stderr
    assert len(requests) == 3


def test_network_failure() -> None:
    with service(lambda _path, _params: (200, b"[]")) as (_, env):
        pass
    result = run(env, "forecast", "--lat", "0", "--lon", "0")
    assert result.returncode == 1
    assert "Network request failed" in result.stderr
    assert len(result.stderr.splitlines()) == 1


def test_nearest_filters_non_metar_and_chooses_closest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stations = [
        {"icaoId": "NOAA", "lat": 0.001, "lon": 0, "siteType": ["TAF"]},
        {"icaoId": "FARX", "lat": 0.4, "lon": 0, "siteType": ["METAR"]},
        {"icaoId": "NEAR", "lat": 0.1, "lon": 0, "siteType": ["METAR"]},
    ]

    def get(_base: str, _path: str, _params: dict[str, str | int | float]) -> object:
        return stations

    monkeypatch.setattr(weather_live, "get", get)
    assert nearest(Location(latitude=0, longitude=0)).icao_id == "NEAR"


def test_invalid_json_is_actionable() -> None:
    with service(lambda _path, _params: (200, b"not json")) as (_, env):
        result = run(env, "forecast", "--lat", "0", "--lon", "0")
    assert result.returncode == 1
    assert "invalid JSON" in result.stderr
    assert len(result.stderr.splitlines()) == 1


def test_mismatched_hourly_columns_are_actionable() -> None:
    forecast = weather_live.Forecast.model_validate_json(fixture("forecast_icon"))
    assert forecast.hourly is not None
    _ = forecast.hourly.time.pop()
    with service(lambda _path, _params: (200, forecast.model_dump_json().encode())) as (
        _,
        env,
    ):
        result = run(env, "forecast", "--lat", "0", "--lon", "0")
    assert result.returncode == 1
    assert "mismatched hourly data" in result.stderr
    assert len(result.stderr.splitlines()) == 1


def test_text_forecast_has_rows() -> None:
    with service(lambda _path, _params: (200, fixture("forecast_icon"))) as (_, env):
        result = run(env, "forecast", "--lat", "0", "--lon", "0", "--text")
    assert result.returncode == 0, result.stderr
    assert "Local time" in result.stdout
    assert "Precip mm" in result.stdout
    assert "2026-10-30" in result.stdout


def test_station_time_is_normalized_and_text_is_readable() -> None:
    obs = TypeAdapter(list[Metar]).validate_json(fixture("metar_segu"))
    obs[0].report_time = "2026-10-30T14:00:00-05:00"

    def handler(path: str, _params: Params) -> tuple[int, bytes]:
        if path.endswith("metar"):
            return 200, TypeAdapter(list[Metar]).dump_json(obs, by_alias=True)
        return 200, fixture("forecast_icon")

    with service(handler) as (_, env):
        result = run(env, "now", "--station", "SEGU")
        readable = run(env, "now", "--station", "SEGU", "--text")
    assert result.returncode == 0, result.stderr
    assert TypeAdapter(ObservationOutput).validate_json(result.stdout)["time_utc"] == (
        "2026-10-30T19:00:00+00:00"
    )
    assert readable.returncode == 0, readable.stderr
    assert "SEGU" in readable.stdout
    assert "Temperature:" in readable.stdout
    assert "METAR:" in readable.stdout


def test_station_local_time_without_system_timezone_database() -> None:
    def handler(path: str, _params: Params) -> tuple[int, bytes]:
        if path.endswith("metar"):
            return 200, fixture("metar_segu")
        return 200, fixture("forecast_icon")

    with service(handler) as (_, env):
        result = run(env | {"PYTHONTZPATH": ""}, "now", "--station", "SEGU")
    assert result.returncode == 0, result.stderr
    obs = TypeAdapter(ObservationOutput).validate_json(result.stdout)
    assert obs["timezone"] == "America/Guayaquil"
    assert obs["time_local"].endswith("-05:00")
