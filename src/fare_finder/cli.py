"""Command line: `fare-finder scan`."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta

from .alerts import alert_rows, build_email, choose_alerts, email_configured, send_email
from .config import Config, load_config
from .history import load_and_annotate, observation_rows
from .models import TripResult
from .providers import get_provider
from .report import render_text, write_csv, write_json
from .scan import run_scan
from .storage import Store, StorageError, SupabaseStore
from .weekends import generate_trips

ALERT_LOOKBACK_DAYS = 180


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _progress(i: int, total: int, result) -> None:
    t = result.trip
    price = f"${result.lowest_price}" if result.lowest_price is not None else ("error" if result.error else "none")
    line = f"[{i}/{total}] {t.pattern} {t.depart} {t.destination}: {price}"
    if sys.stderr.isatty():  # one updating line in a terminal
        print(f"\r{line}".ljust(60), end="", file=sys.stderr, flush=True)
        if i == total:
            print(file=sys.stderr)
    elif i % 12 == 0 or i == total or result.error:  # occasional lines in CI logs
        print(line + (f" ({result.error})" if result.error else ""), file=sys.stderr)


def _run_context() -> tuple[str | None, str | None]:
    """GitHub Actions run id and URL, when running there."""
    run_id = os.environ.get("GITHUB_RUN_ID")
    if run_id and os.environ.get("GITHUB_REPOSITORY"):
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        return run_id, f"{server}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run_id}"
    return run_id, None


def finish(
    results: list[TripResult],
    config: Config,
    provider_name: str,
    today: date,
    store: Store | None,
    email_mode: str,  # "send", "print" or "off"
    run_id: str | None = None,
    run_url: str | None = None,
) -> tuple[str, list]:
    """History, report, alerts and storage after a scan. Returns (report text, alerts)."""
    sent = []
    if store is not None:
        try:
            load_and_annotate(results, store, today)
            sent = store.sent_alerts(since=today - timedelta(days=ALERT_LOOKBACK_DAYS))
        except StorageError as exc:
            _log(f"Could not load price history ({exc}); continuing without it.")
            store = None

    text = render_text(results, config, provider_name, today)
    alerts = choose_alerts(results, config, sent)

    emailed = False
    if alerts and email_mode == "print":
        msg = build_email(alerts, config, run_url)
        _log(f"\n--- Email preview ({len(alerts)} alerts) ---\nSubject: {msg['Subject']}\n\n{msg.get_content()}")
    elif alerts and email_mode == "send":
        try:
            to = send_email(build_email(alerts, config, run_url))
            emailed = True
            _log(f"Emailed {len(alerts)} alerts to {to}.")
        except Exception as exc:  # never lose the scan because email failed
            _log(f"Email failed: {type(exc).__name__}: {exc}")
    elif not alerts:
        _log("No new deals or big drops — no email.")

    if store is not None:
        try:
            store.save_observations(observation_rows(results, provider_name, run_id))
            if emailed:
                store.save_alerts(alert_rows(alerts))
            _log(f"Saved {len(results)} fares to price history.")
        except StorageError as exc:
            _log(f"Could not save price history: {exc}")

    return text, alerts


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
    scan.add_argument("--no-store", action="store_true", help="Don't read or write Supabase price history")
    scan.add_argument(
        "--email",
        choices=["auto", "send", "print", "off"],
        default="auto",
        help="auto = send if SMTP_USER/SMTP_PASSWORD are set; print = show the email instead of sending",
    )
    scan.add_argument("--today", type=date.fromisoformat, help=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    config = load_config(args.config)
    today = args.today or date.today()

    route = config.route(args.route) if args.route else None
    trips = generate_trips(config, today, route=route, weekends=args.weekends)
    kwargs = {"delay_seconds": args.delay} if args.provider.startswith("fast") else {}
    provider = get_provider(args.provider, **kwargs)

    store = None
    if not args.no_store:
        store = SupabaseStore.from_env()
        if store and provider.name == "sample":
            _log("Sample data is never saved to price history.")
            store = None
        elif store is None:
            _log("SUPABASE_URL / SUPABASE_SECRET_KEY not set — running without price history.")

    email_mode = args.email
    if email_mode == "auto":
        email_mode = "send" if email_configured() and provider.name != "sample" else "off"

    _log(f"Pricing {len(trips)} trips (2 searches each) via {provider.name}…")
    results = run_scan(trips, provider, config, on_progress=_progress)

    run_id, run_url = _run_context()
    text, _ = finish(results, config, provider.name, today, store, email_mode, run_id, run_url)
    print(text)

    if args.csv:
        write_csv(results, args.csv)
        _log(f"Wrote {args.csv}")
    if args.json:
        write_json(results, args.json, {"scanned": today.isoformat(), "provider": provider.name, "origin": config.origin})
        _log(f"Wrote {args.json}")

    if results and all(r.error for r in results):
        _log("Every search failed — the data source may be blocking requests.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
