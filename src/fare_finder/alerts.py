"""Decide which fares are worth an email, and send it.

Rules (per trip = route + pattern + departure date + airport):
  deal  — lowest fare is at or below the route's target_price, or the measured
          Main Cabin price is at or below main_cabin_target
  drop  — lowest fare fell at least `drop_percent` since the last scan
A trip is emailed again only if its fare is at least $10 below the last fare
we emailed for it, so a deal that sits there for weeks is sent once.

Email goes out over SMTP. For Gmail, create an app password (needs 2-Step
Verification) and set these environment variables:
  SMTP_USER            you@gmail.com
  SMTP_PASSWORD        the 16-character app password
  ALERT_EMAIL_TO       optional, defaults to SMTP_USER
  SMTP_HOST / SMTP_PORT optional, default smtp.gmail.com / 465
"""

from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage

from .config import Config
from .models import TripResult
from .storage import SentAlert

RE_ALERT_MIN_DROP = 10  # dollars


@dataclass
class Alert:
    result: TripResult
    reason: str  # "deal" or "drop"


def choose_alerts(results: list[TripResult], config: Config, sent: list[SentAlert]) -> list[Alert]:
    last_sent: dict[str, int] = {}
    for s in sorted(sent, key=lambda s: s.sent_at):
        last_sent[s.trip_key] = s.price

    alerts = []
    for r in results:
        if r.lowest_price is None:
            continue
        if r.is_deal:
            reason = "deal"
        elif r.change_pct is not None and r.change_pct <= -config.drop_percent:
            reason = "drop"
        else:
            continue
        previous = last_sent.get(r.trip.key)
        if previous is not None and r.lowest_price > previous - RE_ALERT_MIN_DROP:
            continue  # already told you about this fare (or a cheaper one)
        alerts.append(Alert(r, reason))

    return sorted(alerts, key=lambda a: (a.reason != "deal", a.result.door_to_door, a.result.trip.depart))


def alert_rows(alerts: list[Alert]) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    return [{"sent_at": now, "trip_key": a.result.trip.key, "reason": a.reason, "price": a.result.lowest_price} for a in alerts]


def _line(a: Alert) -> str:
    r, t = a.result, a.result.trip
    parts = [
        f"${r.lowest_price} {t.pattern} {t.depart:%a %b} {t.depart.day} – {t.return_date:%a %b} {t.return_date.day} into {t.destination}",
        f"outbound {r.lowest.depart_time}→{r.lowest.arrive_time}",
    ]
    if r.prev_price is not None and r.prev_price != r.lowest_price:
        parts.append(f"was ${r.prev_price} last scan ({r.change_pct:+.0f}%)")
    if r.main_cabin_price is not None:
        parts.append(f"Main Cabin ${r.main_cabin_price}, ~{r.lp_estimate:,} LP")
    elif r.main_cabin_unknown:
        parts.append("Main Cabin price unavailable — check aa.com")
    if r.ground_cost:
        parts.append(f"${r.door_to_door} door-to-door")
    return "  • " + " · ".join(parts)


def build_email(alerts: list[Alert], config: Config, run_url: str | None = None) -> EmailMessage:
    deals = [a for a in alerts if a.reason == "deal"]
    drops = [a for a in alerts if a.reason == "drop"]
    top = alerts[0].result
    subject = (
        f"AA fare alert: ${top.lowest_price} {top.trip.pattern} {top.trip.depart:%b} {top.trip.depart.day} "
        f"into {top.trip.destination}"
    )
    if len(alerts) > 1:
        subject += f" (+{len(alerts) - 1} more)"

    body = []
    if deals:
        targets = "; ".join(f"{r.name} {r.target_label}" for r in config.routes)
        body.append(f"At or below your target ({targets}):")
        body.extend(_line(a) for a in deals)
        body.append("")
    if drops:
        body.append(f"Dropped {config.drop_percent:.0f}%+ since the last scan:")
        body.extend(_line(a) for a in drops)
        body.append("")
    body.append("Prices are AA nonstop round trips from Google Flights. Confirm on aa.com before booking.")
    if run_url:
        body.append(f"Full report: {run_url}")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg.set_content("\n".join(body))
    return msg


def send_email(msg: EmailMessage) -> str:
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    to = os.environ.get("ALERT_EMAIL_TO") or user
    msg["From"] = os.environ.get("ALERT_EMAIL_FROM") or user
    msg["To"] = to

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls(context=context)
            smtp.login(user, password)
            smtp.send_message(msg)
    return to


def email_configured() -> bool:
    return bool(os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"))
