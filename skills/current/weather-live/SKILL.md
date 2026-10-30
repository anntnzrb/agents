---
name: weather-live
description: Use when checking hourly weather forecasts or current airport METAR observations for a place.
license: AGPL-3.0-or-later
---

# Weather live

## Public entrypoint

No credentials. No API keys. No commercial APIs.

```bash
uv run --script <skill-dir>/scripts/cli.py <command> [options]
```

## Common calls

Use `cli.py` below as shorthand for the public entrypoint.

```bash
cli.py forecast --place Guayaquil --country EC
cli.py forecast --lat -2.19616 --lon -79.88621 --hours 24
cli.py forecast --place Guayaquil --model ecmwf_aifs025_single
cli.py now --place Guayaquil
cli.py now --station SEGU
```

JSON is the default. Add `--text` for human-readable output. Forecasts default to 48 hours. Check the resolved location, airport distance, and observation time before interpreting results.

Use the default `icon_seamless` model. Avoid `best_match`, which can select models with a cold bias in Ecuador.

For temperature, `--model ecmwf_aifs025_single` is an alternative. Its precipitation values repeat six-hour blocks and cannot establish hourly rain timing. Its precipitation probability is null. Preserve unavailable probabilities as null, never zero.

Tropical rain forecasts are uncertain. Report probabilities, never certainty. Use `now` as ground truth at the airport at observation time. Conditions at the requested place can differ.

Vicinity showers are not rain at the station. `rain` reports RA at the station. `drizzle` separately reports DZ. Do not infer hourly rainfall in millimeters from a METAR, including in Ecuador.

Attribute [Open-Meteo](https://open-meteo.com/) and the [Aviation Weather Center](https://aviationweather.gov/data/api/) when presenting their data. Open-Meteo's free tier is for non-commercial use. See its [terms](https://open-meteo.com/en/terms).

The Aviation Weather Center allows at most 100 requests per minute and requires a custom User-Agent. Poll METARs no more than hourly.
