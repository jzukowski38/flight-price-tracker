"""Plain-text and CSV/JSON output."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from .config import Config
from .models import TripResult
from .scan import best_per_weekend_pattern


def _money(v: int | None, unknown: bool = False) -> str:
    if v is None:
        return "?" if unknown else "—"
    return f"${v}"


def _day(d: date, weekday: bool = True) -> str:
    return f"{d:%a %b} {d.day}" if weekday else f"{d:%b} {d.day}"  # portable: no %-d on Windows


def _vs_last(r: TripResult) -> str:
    if r.prev_price is None:
        return "new"
    if r.lowest_price == r.prev_price:
        return "same"
    return f"was ${r.prev_price} ({r.change_pct:+.0f}%)"


def _span(r: TripResult) -> str:
    return f"{_day(r.trip.depart)} – {_day(r.trip.return_date)}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(h), *(len(row[i]) for row in rows)) if rows else len(h) for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths)).rstrip()
    out = [line(headers), line(["-" * w for w in widths])]
    out += [line(row) for row in rows]
    return "\n".join(out)


def render_text(results: list[TripResult], config: Config, provider_name: str, today: date) -> str:
    parts: list[str] = []
    priced = [r for r in results if r.lowest_price is not None]
    errors = [r for r in results if r.error]

    header = f"AA nonstop weekend fares from {config.origin} — scanned {_day(today, False)}, {today.year} via {provider_name}"
    parts.append(header)
    parts.append("=" * len(header))
    if provider_name == "sample":
        parts.append("NOTE: sample provider — these prices are made up, for testing only.")

    for route in config.routes:
        route_results = [r for r in priced if r.trip.route == route.name]
        if not route_results:
            continue
        has_ground = bool(route.ground)
        has_history = any(r.prior_count for r in route_results)
        dest_label = route.ground_to or route.name
        parts.append("")
        parts.append(f"{route.name}: {', '.join(route.destinations)} · deal: {route.target_label}")

        # 1. Deals (fare at or below target), cheapest door-to-door first
        deals = sorted(
            (r for r in route_results if r.is_deal), key=lambda r: (r.door_to_door, r.lowest_price, r.trip.depart)
        )
        parts.append("")
        if deals:
            parts.append(f"Deals at or below {route.target_label}:")
            headers = ["Dates", "Pattern", "Airport", "Lowest", "Main Cabin", "Gap", "Est. LP", "Outbound"]
            if has_ground:
                headers[4:4] = [f"To {dest_label}", "Door-to-door"]
            rows = []
            for r in deals:
                row = [
                    _span(r),
                    r.trip.pattern,
                    r.trip.destination,
                    _money(r.lowest_price),
                    _money(r.main_cabin_price, r.main_cabin_unknown),
                    _money(r.gap, r.main_cabin_unknown),
                    f"{r.lp_estimate:,}" if r.lp_estimate else "—",
                    f"{r.lowest.depart_time}→{r.lowest.arrive_time}",
                ]
                if has_ground:
                    ground = f"{r.ground_minutes}m, ${r.ground_cost} each way" if r.ground_cost is not None else "—"
                    row[4:4] = [ground, _money(r.door_to_door)]
                if has_history:
                    row.append(_vs_last(r))
                rows.append(row)
            if has_history:
                headers.append("vs last scan")
            parts.append(_table(headers, rows))
        else:
            cheapest = min(route_results, key=lambda r: r.lowest_price)
            parts.append(
                f"No deals at or below {route.target_label} yet. Cheapest: {_money(cheapest.lowest_price)} "
                f"{cheapest.trip.pattern} {_span(cheapest)} into {cheapest.trip.destination}."
            )

        # Biggest moves since the last scan
        if has_history:
            moved = [r for r in route_results if r.change_pct is not None and r.lowest_price != r.prev_price]
            drops = sorted((r for r in moved if r.change_pct < 0), key=lambda r: r.change_pct)[:5]
            parts.append("")
            if drops:
                parts.append("Biggest drops since the last scan:")
                for r in drops:
                    low = " · lowest seen" if r.lowest_price <= (r.prior_low or 0) else ""
                    parts.append(
                        f"  {_money(r.lowest_price)} {r.trip.pattern} {_span(r)} {r.trip.destination}: {_vs_last(r)}{low}"
                    )
            else:
                rises = sum(1 for r in moved if r.change_pct > 0)
                parts.append(f"No fares dropped since the last scan ({rises} went up).")

        # 2. Weekend grid: cheapest airport per weekend x pattern
        best = best_per_weekend_pattern(route_results)
        weekends = sorted({r.trip.weekend for r in route_results})
        patterns = [p.name for p in config.patterns]
        rows = []
        for sat in weekends:
            row = [_day(sat, False)]
            for p in patterns:
                b = best.get((route.name, sat, p))
                row.append(f"{_money(b.lowest_price)} {b.trip.destination}{' *' if b.is_deal else ''}" if b else "—")
            rows.append(row)
        parts.append("")
        if has_ground:
            parts.append(
                f"Best AA nonstop by weekend — airport with the lowest fare + ground cost to {dest_label}; "
                "fare shown (Saturday shown; * = deal):"
            )
        else:
            parts.append("Cheapest AA nonstop by weekend (Saturday shown; * = deal):")
        parts.append(_table(["Weekend", *patterns], rows))

        # Airport comparison: typical fare vs typical door-to-door
        if len(route.destinations) > 1:
            lines = []
            for code in route.destinations:
                fares = sorted(r.lowest_price for r in route_results if r.trip.destination == code)
                if not fares:
                    continue
                median_fare = fares[len(fares) // 2]
                g = route.ground_for(code)
                if g:
                    lines.append(
                        f"  {code}: median fare ${median_fare} + ${2 * g.cost} ground "
                        f"= ${median_fare + 2 * g.cost} door-to-door, {g.minutes} min each way"
                    )
                else:
                    lines.append(f"  {code}: median fare ${median_fare}")
            parts.append("")
            parts.append("Airports compared:" if not has_ground else f"Airports compared (to {dest_label}):")
            parts.extend(lines)

        # 3. Main Cabin gap summary
        gaps = [r.gap for r in route_results if r.gap is not None]
        if gaps:
            gaps.sort()
            median = gaps[len(gaps) // 2]
            parts.append("")
            parts.append(
                f"Main Cabin gap over Basic: median ${median}, range ${gaps[0]}–${gaps[-1]} "
                f"({len(gaps)} trips measured). '?' = Main Cabin price unavailable this scan."
            )

    parts.append("")
    parts.append(
        f"{len(results)} trips · {len(priced)} priced · "
        f"{len(results) - len(priced) - len(errors)} with no AA nonstop · {len(errors)} errors"
    )
    if errors:
        parts.append("First error: " + errors[0].error)
    return "\n".join(parts)


FIELDS = [
    "route", "pattern", "weekend", "depart", "return", "airport",
    "lowest_price", "main_cabin_price", "gap", "main_cabin_unknown", "lp_estimate", "is_deal",
    "ground_minutes", "ground_cost", "door_to_door",
    "outbound_depart", "outbound_arrive", "error",
]


def to_rows(results: list[TripResult]) -> list[dict]:
    rows = []
    for r in results:
        t = r.trip
        rows.append(
            {
                "route": t.route,
                "pattern": t.pattern,
                "weekend": t.weekend.isoformat(),
                "depart": t.depart.isoformat(),
                "return": t.return_date.isoformat(),
                "airport": t.destination,
                "lowest_price": r.lowest_price,
                "main_cabin_price": r.main_cabin_price,
                "gap": r.gap,
                "main_cabin_unknown": r.main_cabin_unknown,
                "lp_estimate": r.lp_estimate,
                "is_deal": r.is_deal,
                "ground_minutes": r.ground_minutes,
                "ground_cost": r.ground_cost,
                "door_to_door": r.door_to_door,
                "outbound_depart": r.lowest.depart_time if r.lowest else None,
                "outbound_arrive": r.lowest.arrive_time if r.lowest else None,
                "error": r.error,
            }
        )
    return rows


def write_csv(results: list[TripResult], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(to_rows(results))


def write_json(results: list[TripResult], path: str | Path, meta: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "results": to_rows(results)}, fh, indent=2)
