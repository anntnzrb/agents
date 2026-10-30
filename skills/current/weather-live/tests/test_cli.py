"""Subprocess forecast contract."""

from pydantic import TypeAdapter
from weather_live import ForecastOutput

from tests.support import Params, fixture, run, service


def test_forecast_loopback() -> None:
    def handler(path: str, _params: Params) -> tuple[int, bytes]:
        name = "geocode_guayaquil" if path == "/v1/search" else "forecast_icon"
        return 200, fixture(name)

    with service(handler) as (requests, env):
        result = run(env, "forecast", "--place", "Guayaquil")
    assert result.returncode == 0, result.stderr
    data = TypeAdapter(ForecastOutput).validate_json(result.stdout)
    assert len(data["hourly"]) == 48
    assert data["location"]["name"] == "Guayaquil"
    assert all(ua == "weather-live/0.1" for _, _, ua in requests)
    assert requests[1][1]["models"] == ["icon_seamless"]
