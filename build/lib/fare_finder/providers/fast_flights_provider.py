"""Google Flights via the free, unofficial `fast-flights` library.

Good for prototyping. Google can rate-limit or change its page without notice,
so this sits behind the FareProvider interface and can be swapped for a paid
source (Apify, SerpApi) later.
"""

from __future__ import annotations

import time

from fast_flights import FlightQuery, FlightsNotFound, create_query, get_flights

from ..models import FareOption, Trip
from .base import ProviderError


def _hhmm(t: tuple[int, int]) -> str:
    return f"{t[0]:02d}:{t[1]:02d}"


class FastFlightsProvider:
    name = "fast-flights"

    def __init__(self, delay_seconds: float = 2.0, retries: int = 1, proxy: str | None = None):
        self.delay_seconds = delay_seconds
        self.retries = retries
        self.proxy = proxy
        self._last_call = 0.0

    def build_query(self, trip: Trip, airline: str, exclude_basic_economy: bool):
        return create_query(
            flights=[
                FlightQuery(
                    date=trip.depart.isoformat(),
                    from_airport=trip.origin,
                    to_airport=trip.destination,
                    airlines=[airline],
                    max_stops=0,
                ),
                FlightQuery(
                    date=trip.return_date.isoformat(),
                    from_airport=trip.destination,
                    to_airport=trip.origin,
                    airlines=[airline],
                    max_stops=0,
                ),
            ],
            trip="round-trip",
            seat="economy",
            language="en-US",
            currency="USD",
            exclude_basic_economy=exclude_basic_economy,
        )

    def _throttle(self) -> None:
        wait = self.delay_seconds - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def search(self, trip: Trip, airline: str, exclude_basic_economy: bool) -> list[FareOption]:
        query = self.build_query(trip, airline, exclude_basic_economy)
        last_error: Exception | None = None

        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                results = get_flights(query, proxy=self.proxy)
            except FlightsNotFound:
                return []
            except Exception as exc:  # network errors, blocked requests, page changes
                last_error = exc
                time.sleep(self.delay_seconds * (attempt + 1))
                continue

            options = []
            for r in results:
                if len(r.flights) != 1 or not isinstance(r.price, int) or r.price <= 0:
                    continue  # keep nonstops with a real price only
                leg = r.flights[0]
                options.append(
                    FareOption(
                        price=r.price,
                        airlines=tuple(r.airlines),
                        depart_time=_hhmm(leg.departure.time),
                        arrive_time=_hhmm(leg.arrival.time),
                        stops=0,
                    )
                )
            return options

        raise ProviderError(f"{trip.key}: {type(last_error).__name__}: {last_error}")
