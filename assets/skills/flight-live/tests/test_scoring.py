from __future__ import annotations

from datetime import date

from flight_live.models import FlightOption
from flight_live.scoring import rank_options


def _option(
    *, depart: str, ret: str | None, price: float, transfers: int
) -> FlightOption:
    return FlightOption(
        origin="SFO",
        destination="JFK",
        depart_date=date.fromisoformat(depart),
        return_date=None if ret is None else date.fromisoformat(ret),
        price=price,
        currency="USD",
        transfers=transfers,
        airline="XX",
    )


def test_weekday_departure_beats_weekend_given_similar_price() -> None:
    weekend = _option(
        depart="2026-05-16", ret="2026-05-20", price=280.0, transfers=0
    )  # Sat
    weekday = _option(
        depart="2026-05-19", ret="2026-05-23", price=285.0, transfers=0
    )  # Tue

    ranked = rank_options([weekend, weekday], max_budget=None, prefer_nonstop=False)

    assert ranked[0].depart_date == date(2026, 5, 19)
    assert "weekday_departure_bonus" in ranked[0].reasons
    assert "weekend_departure_penalty" in ranked[1].reasons


def test_nonstop_preference_penalizes_stops() -> None:
    nonstop = _option(depart="2026-06-02", ret=None, price=310.0, transfers=0)
    with_stop = _option(depart="2026-06-02", ret=None, price=260.0, transfers=1)

    ranked = rank_options([with_stop, nonstop], max_budget=None, prefer_nonstop=True)

    assert ranked[0].transfers == 0
    assert "nonstop_preferred_bonus" in ranked[0].reasons
    assert "nonstop_preferred_penalty" in ranked[1].reasons
