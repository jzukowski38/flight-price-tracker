"""Core data types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Trip:
    """One round trip to price: a route, a pattern, an airport and two dates."""

    route: str
    pattern: str
    origin: str
    destination: str
    weekend: date  # the Saturday of the weekend this trip belongs to
    depart: date
    return_date: date

    @property
    def key(self) -> str:
        return f"{self.origin}-{self.route}#{self.pattern}#{self.depart.isoformat()}#{self.destination}"


@dataclass(frozen=True)
class FareOption:
    """One priced itinerary from a provider: round-trip price, outbound times."""

    price: int
    airlines: tuple[str, ...]
    depart_time: str  # outbound departure, "HH:MM"
    arrive_time: str  # outbound arrival, "HH:MM"
    stops: int = 0


@dataclass
class TripResult:
    trip: Trip
    lowest: FareOption | None = None        # cheapest AA nonstop, usually Basic Economy
    main_cabin: FareOption | None = None    # cheapest AA nonstop with Basic Economy excluded
    main_cabin_price: int | None = None     # main_cabin.price, or lowest + default gap if that search came back empty
    gap: int | None = None
    gap_estimated: bool = False
    lp_estimate: int | None = None
    is_deal: bool = False
    error: str | None = None

    @property
    def lowest_price(self) -> int | None:
        return self.lowest.price if self.lowest else None
