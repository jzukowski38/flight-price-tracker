"""Command line: `fare-finder scan`."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from .config import load_config
from .providers import get_provider
from .report import render_text, write_csv, write_json
from .scan import run_scan
from .weekends import generate_trips


def _progress(i: int, total: int, result) -> None:
    t = result.trip
    price = f"${result.lowest_price}" if result.lowest_price is not None else ("error" if result.error else "none")
    print(f"\r[{i}/{total}] {t.pattern} {t.depart} {t.destination}: {price}".ljust(60), end="", file=sys.stderr, flush=True)
    if i == total:
        print(file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fare-finder", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Price upcoming weekends and print the cheapest")
    scan.add_argument("--config", default="config.yaml")
    scan.add_argument("--provider", default="fast-flights", help="fast-flights (live Google Flights) or sample (made-up data)")
    scan.add_argument("--route", help="Only scan this route name from config, e.g. NYC")
    scan.add_argument("--weekends", type=int, help="Override weekends_ahead")
    scan.add_argument("--delay", type=float, default=2.0, help="Seconds between live searches (default 2)")
    scan.add_argument("--csv", help="Also write every result to this CSV file")
    scan.add_argument("--json", help="Also write every result to this JSON file")
    scan.add_argument("--today", type=date.fromisoformat, help=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    config = load_config(args.config)
    today = args.today or date.today()

    route = config.route(args.route) if args.route else None
    trips = generate_trips(config, today, route=route, weekends=args.weekends)
    kwargs = {"delay_seconds": args.delay} if args.provider.startswith("fast") else {}
    provider = get_provider(args.provider, **kwargs)

    print(f"Pricing {len(trips)} trips (2 searches each) via {provider.name}…", file=sys.stderr)
    results = run_scan(trips, provider, config, on_progress=_progress)

    print(render_text(results, config, provider.name, today))
    if args.csv:
        write_csv(results, args.csv)
        print(f"\nWrote {args.csv}", file=sys.stderr)
    if args.json:
        write_json(results, args.json, {"scanned": today.isoformat(), "provider": provider.name, "origin": config.origin})
        print(f"Wrote {args.json}", file=sys.stderr)

    if results and all(r.error for r in results):
        print("Every search failed — the data source may be blocking requests.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
