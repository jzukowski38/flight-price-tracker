"""Compare this scan's fares with earlier scans of the same trips."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from statistics import median

from .models import TripResult
from .storage import Observation, Store


def annotate(results: list[TripResult], observations: list[Observation]) -> None:
    by_trip: dict[str, list[Observation]] = defaultdict(list)
    for o in observations:
        by_trip[o.trip_key].append(o)

    for r in results:
        prior = sorted(by_trip.get(r.trip.key, []), key=lambda o: o.scanned_at)
        if not prior:
            continue
        prices = [o.lowest_price for o in prior]
        r.prev_price = prices[-1]
        r.prior_low = min(prices)
        r.prior_median = int(median(prices))
        r.prior_count = len(prices)


def load_and_annotate(results: list[TripResult], store: Store, today: date) -> None:
    for route in sorted({r.trip.route for r in results}):
        annotate([r for r in results if r.trip.route == route], store.history(route, depart_from=today))


def observation_rows(results: list[TripResult], provider: str, run_id: str | None, scanned_at: datetime | None = None) -> list[dict]:
    ts = (scanned_at or datetime.now(timezone.utc)).isoformat()
    rows = []
    for r in results:
        t = r.trip
        rows.append(
            {
                "scanned_at": ts,
                "run_id": run_id,
                "provider": provider,
                "trip_key": t.key,
                "origin": t.origin,
                "route": t.route,
                "pattern": t.pattern,
                "weekend": t.weekend.isoformat(),
                "depart": t.depart.isoformat(),
                "return_date": t.return_date.isoformat(),
                "airport": t.destination,
                "lowest_price": r.lowest_price,
                "main_cabin_price": r.main_cabin_price,
                "gap": r.gap,
                "main_cabin_unknown": r.main_cabin_unknown,
                "lp_estimate": r.lp_estimate,
                "ground_cost": r.ground_cost,
                "door_to_door": r.door_to_door,
                "outbound_depart": r.lowest.depart_time if r.lowest else None,
                "outbound_arrive": r.lowest.arrive_time if r.lowest else None,
                "error": r.error,
            }
        )
    return rows
