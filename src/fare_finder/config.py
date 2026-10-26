"""Load and validate config.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass(frozen=True)
class Pattern:
    name: str
    depart_weekday: int  # Monday = 0
    nights: int


@dataclass(frozen=True)
class Ground:
    """Getting from an airport to where you're staying, one way."""

    minutes: int
    cost: int


@dataclass(frozen=True)
class Route:
    name: str
    destinations: tuple[str, ...]
    target_price: int
    blackout_dates: frozenset[date] = frozenset()
    main_cabin_target: int = 0  # 0 = no Main Cabin target
    ground_to: str | None = None
    ground: tuple[tuple[str, Ground], ...] = ()  # (airport, Ground) pairs; tuple keeps it hashable

    @property
    def target_label(self) -> str:
        label = f"${self.target_price}"
        if self.main_cabin_target:
            label += f" (any fare) or ${self.main_cabin_target} (Main Cabin)"
        return label

    def ground_for(self, airport: str) -> Ground | None:
        for code, g in self.ground:
            if code == airport:
                return g
        return None


@dataclass(frozen=True)
class LoyaltyConfig:
    lp_per_dollar: float = 5
    taxes_estimate: float = 45
    main_cabin_gap_default: int = 60


@dataclass(frozen=True)
class Config:
    origin: str
    airline: str
    weekends_ahead: int
    min_days_out: int
    patterns: tuple[Pattern, ...]
    routes: tuple[Route, ...]
    loyalty: LoyaltyConfig = field(default_factory=LoyaltyConfig)
    drop_percent: float = 15

    def route(self, name: str) -> Route:
        for r in self.routes:
            if r.name.lower() == name.lower():
                return r
        known = ", ".join(r.name for r in self.routes)
        raise ValueError(f"Unknown route {name!r}. Configured routes: {known}")


class ConfigError(ValueError):
    pass


def _airport(code: object, where: str) -> str:
    if not isinstance(code, str) or len(code) != 3 or not code.isalpha():
        raise ConfigError(f"{where}: {code!r} is not a 3-letter airport code")
    return code.upper()


def parse_config(raw: dict) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("config must be a mapping")

    patterns = []
    for i, p in enumerate(raw.get("patterns") or []):
        day = str(p.get("depart", "")).strip().lower()
        if day not in WEEKDAYS:
            raise ConfigError(f"patterns[{i}].depart: {p.get('depart')!r} is not a weekday name")
        nights = int(p.get("nights", 0))
        if nights < 1:
            raise ConfigError(f"patterns[{i}].nights must be at least 1")
        patterns.append(Pattern(name=str(p.get("name") or f"pattern-{i}"), depart_weekday=WEEKDAYS[day], nights=nights))
    if not patterns:
        raise ConfigError("at least one pattern is required")

    routes = []
    for i, r in enumerate(raw.get("routes") or []):
        dests = tuple(_airport(d, f"routes[{i}].destinations") for d in (r.get("destinations") or []))
        if not dests:
            raise ConfigError(f"routes[{i}] needs at least one destination")
        blackouts = frozenset(date.fromisoformat(str(d)) for d in (r.get("blackout_dates") or []))
        ground = []
        for code, g in (r.get("ground") or {}).items():
            code = _airport(code, f"routes[{i}].ground")
            if code not in dests:
                raise ConfigError(f"routes[{i}].ground: {code} is not one of this route's destinations")
            ground.append((code, Ground(minutes=int(g.get("minutes", 0)), cost=int(g.get("cost", 0)))))
        routes.append(
            Route(
                name=str(r.get("name") or "-".join(dests)),
                destinations=dests,
                target_price=int(r.get("target_price", 0)),
                blackout_dates=blackouts,
                main_cabin_target=int(r.get("main_cabin_target", 0)),
                ground_to=r.get("ground_to"),
                ground=tuple(ground),
            )
        )
    if not routes:
        raise ConfigError("at least one route is required")

    loyalty_raw = raw.get("loyalty") or {}
    loyalty = LoyaltyConfig(
        lp_per_dollar=float(loyalty_raw.get("lp_per_dollar", 5)),
        taxes_estimate=float(loyalty_raw.get("taxes_estimate", 45)),
        main_cabin_gap_default=int(loyalty_raw.get("main_cabin_gap_default", 60)),
    )

    weekends = int(raw.get("weekends_ahead", 12))
    if not 1 <= weekends <= 52:
        raise ConfigError("weekends_ahead must be between 1 and 52")

    return Config(
        origin=_airport(raw.get("origin", "DFW"), "origin"),
        airline=str(raw.get("airline", "AA")).upper(),
        weekends_ahead=weekends,
        min_days_out=int(raw.get("min_days_out", 3)),
        patterns=tuple(patterns),
        routes=tuple(routes),
        loyalty=loyalty,
        drop_percent=float((raw.get("alerts") or {}).get("drop_percent", 15)),
    )


def load_config(path: str | Path) -> Config:
    with open(path, encoding="utf-8") as fh:
        return parse_config(yaml.safe_load(fh))
