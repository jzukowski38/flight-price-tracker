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
    deal_basic: bool = False                # lowest fare at or below the route's target_price
    deal_main: bool = False                 # measured Main Cabin price at or below main_cabin_target
    ground_minutes: int | None = None       # airport to destination, one way
    ground_cost: int | None = None          # airport to destination, one way
    # Price history for this exact trip from earlier scans (filled in by history.annotate)
    prev_price: int | None = None           # last scan's lowest fare
    prior_low: int | None = None            # lowest fare ever seen
    prior_median: int | None = None
    prior_count: int = 0
    error: str | None = None

    @property
    def change_pct(self) -> float | None:
        """Change in the lowest fare since the last scan, in percent (negative = cheaper)."""
        if self.lowest is None or not self.prev_price:
            return None
        return (self.lowest.price - self.prev_price) / self.prev_price * 100

    @property
    def is_deal(self) -> bool:
        return self.deal_basic or self.deal_main

    @is_deal.setter
    def is_deal(self, value: bool) -> None:  # convenience for tests: a plain fare deal
        self.deal_basic = value

    @property
    def lowest_price(self) -> int | None:
        return self.lowest.price if self.lowest else None

    @property
    def door_to_door(self) -> int | None:
        """Lowest fare plus ground transport both ways; the fare alone if no ground cost is configured."""
        if self.lowest is None:
            return None
        return self.lowest.price + 2 * (self.ground_cost or 0)
