"""Fare data sources. Each one implements `FareProvider.search`."""

from __future__ import annotations

from .base import FareProvider, ProviderError


def get_provider(name: str, **kwargs) -> FareProvider:
    name = name.lower()
    if name in ("fast-flights", "fast_flights", "google"):
        from .fast_flights_provider import FastFlightsProvider

        return FastFlightsProvider(**kwargs)
    if name == "sample":
        from .sample import SampleProvider

        return SampleProvider()
    raise ValueError(f"Unknown provider {name!r}. Choose 'fast-flights' or 'sample'.")


__all__ = ["FareProvider", "ProviderError", "get_provider"]
