"""Price every trip twice (lowest fare, then Main Cabin) and score the results."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .config import Config
from .loyalty import estimate_loyalty_points
from .models import FareOption, Trip, TripResult
from .providers.base import FareProvider, ProviderError


MAIN_CABIN_ATTEMPTS = 2


def _cheapest(options: Iterable[FareOption]) -> FareOption | None:
    return min(options, key=lambda o: o.price, default=None)


def price_trip(trip: Trip, provider: FareProvider, config: Config) -> TripResult:
    route = config.route(trip.route)
    result = TripResult(trip=trip)
    ground = route.ground_for(trip.destination)
    if ground:
        result.ground_minutes, result.ground_cost = ground.minutes, ground.cost
    try:
        result.lowest = _cheapest(provider.search(trip, config.airline, exclude_basic_economy=False))
        if result.lowest is None:
            return result  # no nonstop availability: skip the second search
        # The lowest-fare search found nonstops, so an empty Main Cabin search is
        # almost always a transient Google hiccup: try once more before giving up.
        for _ in range(MAIN_CABIN_ATTEMPTS):
            result.main_cabin = _cheapest(provider.search(trip, config.airline, exclude_basic_economy=True))
            if result.main_cabin is not None:
                break
    except ProviderError as exc:
        result.error = str(exc)
        if result.lowest is None:
            return result

    result.deal_basic = route.target_price > 0 and result.lowest.price <= route.target_price

    if result.main_cabin is None:
        # Never guess: a default gap can be off by hundreds (a $60 guess once
        # stood in for a real $324 gap). Show it as unknown instead.
        result.main_cabin_unknown = True
        return result

    result.main_cabin_price = max(result.main_cabin.price, result.lowest.price)
    result.gap = result.main_cabin_price - result.lowest.price
    result.lp_estimate = estimate_loyalty_points(result.main_cabin_price, config.loyalty)
    result.deal_main = route.main_cabin_target > 0 and result.main_cabin_price <= route.main_cabin_target
    return result


def run_scan(
    trips: list[Trip],
    provider: FareProvider,
    config: Config,
    on_progress: Callable[[int, int, TripResult], None] | None = None,
) -> list[TripResult]:
    results = []
    for i, trip in enumerate(trips, start=1):
        result = price_trip(trip, provider, config)
        results.append(result)
        if on_progress:
            on_progress(i, len(trips), result)
    return results


def best_per_weekend_pattern(results: list[TripResult]) -> dict[tuple, TripResult]:
    """Best airport for each (route, weekend, pattern): lowest door-to-door cost, then lowest fare."""
    best: dict[tuple, TripResult] = {}
    rank = lambda r: (r.door_to_door, r.lowest_price)
    for r in results:
        if r.lowest_price is None:
            continue
        k = (r.trip.route, r.trip.weekend, r.trip.pattern)
        if k not in best or rank(r) < rank(best[k]):
            best[k] = r
    return best
