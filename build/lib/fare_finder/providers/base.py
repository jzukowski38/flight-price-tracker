"""The interface every fare source implements, so sources can be swapped."""

from __future__ import annotations

from typing import Protocol

from ..models import FareOption, Trip


class ProviderError(RuntimeError):
    """A search failed (network, blocked, unparseable page)."""


class FareProvider(Protocol):
    name: str

    def search(self, trip: Trip, airline: str, exclude_basic_economy: bool) -> list[FareOption]:
        """Return round-trip nonstop itineraries on `airline` for `trip`.

        An empty list means the search worked and found nothing; failures raise
        ProviderError.
        """
        ...
