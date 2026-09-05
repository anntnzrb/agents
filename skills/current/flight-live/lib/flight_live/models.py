"""Domain models for flight-live search requests and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import date

TripType = Literal["oneway", "roundtrip"]
CabinClass = Literal["economy", "premium_economy", "business", "first"]


class FlightLiveError(RuntimeError):
    """Base runtime error for flight-live."""


class MissingExecutableError(FlightLiveError):
    """Required external executable is unavailable."""


@dataclass(slots=True, frozen=True)
class ResolvedPlace:
    """A place query resolved to an IATA code."""

    query: str
    iata: str
    name: str | None
    resolved_via_autocomplete: bool


@dataclass(slots=True)
class PlannerOffer:
    """One raw planner offer before scoring."""

    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    price: float
    currency: str
    transfers: int | None
    airline: str | None
    source: str = "kiwi_web_scrape"

    @property
    def nonstop(self) -> bool:
        """Whether the offer has no transfers."""
        return self.transfers == 0


@dataclass(slots=True)
class FlightOption:
    """One scored flight option presented to the caller."""

    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    price: float
    currency: str
    transfers: int | None
    airline: str | None
    source: str = "kiwi_web_scrape"
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)

    @property
    def nonstop(self) -> bool:
        """Whether the option has no transfers."""
        return self.transfers == 0

    @property
    def effective_price(self) -> float:
        """Price used for ranking."""
        return self.price

    def to_dict(self) -> dict[str, object]:
        """Serialize the option to a JSON-compatible mapping."""
        return {
            "origin": self.origin,
            "destination": self.destination,
            "depart_date": self.depart_date.isoformat(),
            "return_date": None
            if self.return_date is None
            else self.return_date.isoformat(),
            "price": self.price,
            "effective_price": self.effective_price,
            "currency": self.currency,
            "transfers": self.transfers,
            "nonstop": self.nonstop,
            "airline": self.airline,
            "source": self.source,
            "score": self.score,
            "reasons": list(self.reasons),
            "hints": list(self.hints),
        }


@dataclass(slots=True, frozen=True)
class SearchRequest:
    """Validated flight search parameters."""

    origin: str
    destination: str
    depart_start: date
    depart_end: date
    trip_type: TripType = "oneway"
    stay_min: int | None = None
    stay_max: int | None = None
    adults: int = 1
    children: int = 0
    infants: int = 0
    cabin: CabinClass = "economy"
    currency: str = "USD"
    locale: str = "en"
    market: str = "us"
    nonstop: bool = False
    max_budget: float | None = None
    planner_limit: int = 20
