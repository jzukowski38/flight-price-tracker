"""Turn the config into the list of round trips to price."""

from __future__ import annotations

from datetime import date, timedelta

from .config import Config, Route
from .models import Trip

SATURDAY = 5


def upcoming_saturdays(today: date, count: int) -> list[date]:
    """The next `count` Saturdays, starting with this week's (today counts if it is Saturday)."""
    first = today + timedelta(days=(SATURDAY - today.weekday()) % 7)
    return [first + timedelta(weeks=i) for i in range(count)]


def depart_for(saturday: date, weekday: int) -> date:
    """Departure date for a pattern within the weekend anchored on `saturday`.

    Wednesday through Saturday fall before (or on) the Saturday; Sunday is the day after.
    """
    offset = weekday - SATURDAY
    if offset < -3:  # Monday or Tuesday: treat as the following week's start
        offset += 7
    return saturday + timedelta(days=offset)


def generate_trips(config: Config, today: date, route: Route | None = None, weekends: int | None = None) -> list[Trip]:
    routes = [route] if route else list(config.routes)
    count = weekends or config.weekends_ahead
    earliest = today + timedelta(days=config.min_days_out)
    trips: list[Trip] = []

    for saturday in upcoming_saturdays(today, count):
        for r in routes:
            for pattern in config.patterns:
                depart = depart_for(saturday, pattern.depart_weekday)
                if depart < earliest or depart in r.blackout_dates:
                    continue
                for airport in r.destinations:
                    trips.append(
                        Trip(
                            route=r.name,
                            pattern=pattern.name,
                            origin=config.origin,
                            destination=airport,
                            weekend=saturday,
                            depart=depart,
                            return_date=depart + timedelta(days=pattern.nights),
                        )
                    )
    return trips
