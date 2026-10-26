"""Made-up but plausible fares, for running and testing without network access.

Prices are deterministic per trip so test runs are repeatable. They are NOT
real fares.
"""

from __future__ import annotations

import hashlib

from ..models import FareOption, Trip

_TIMES = [("06:08", "10:30"), ("08:42", "13:04"), ("12:44", "17:04"), ("15:24", "19:41"), ("19:39", "23:59")]
_PATTERN_PREMIUM = {"Fri-Sun": 45, "Thu-Mon": 0, "Sat-Tue": -25}
_AIRPORT_PREMIUM = {"LGA": 0, "JFK": 20, "EWR": -15}


def _n(*parts: object) -> int:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return int(digest[:8], 16)


class SampleProvider:
    name = "sample"

    def search(self, trip: Trip, airline: str, exclude_basic_economy: bool) -> list[FareOption]:
        seed = _n(trip.key)
        if seed % 29 == 0:
            return []  # some trips have no nonstop availability

        base = 250 + seed % 120
        base += _PATTERN_PREMIUM.get(trip.pattern, 0) + _AIRPORT_PREMIUM.get(trip.destination, 0)

        if exclude_basic_economy:
            if seed % 17 == 0:
                return []  # Main Cabin search occasionally comes back empty
            base += 40 + _n(trip.key, "gap") % 90

        options = []
        for i, (dep, arr) in enumerate(_TIMES):
            options.append(
                FareOption(price=base + (i % 3) * 15, airlines=("American",), depart_time=dep, arrive_time=arr)
            )
        return options
