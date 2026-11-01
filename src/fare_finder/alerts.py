"""Decide which fares are worth an email, and send it.

Rules (per trip = route + pattern + departure date + airport):
  deal  — lowest fare is at or below the route's target_price, or the measured
          Main Cabin price is at or below main_cabin_target
  drop  — lowest fare fell at least `drop_percent` since the last scan and is
          now at or below `drop_max_price` (if set)
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
from html import escape

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
        elif (
            r.change_pct is not None
            and r.change_pct <= -config.drop_percent
            and (not config.drop_max_price or r.lowest_price <= config.drop_max_price)
        ):
            reason = "drop"  # a big drop, and cheap enough to be worth a look
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


def _dates(r: TripResult) -> str:
    t = r.trip
    if t.depart.month == t.return_date.month:
        return f"{t.depart:%a %b} {t.depart.day}–{t.return_date.day}"
    return f"{t.depart:%a %b} {t.depart.day} – {t.return_date:%b} {t.return_date.day}"


def _time(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    return f"{(h + 11) % 12 + 1}:{m:02d} {'AM' if h < 12 else 'PM'}"


def _change(r: TripResult) -> str:
    if r.prev_price is None:
        return "new"
    if r.prev_price == r.lowest_price:
        return "same"
    diff = r.lowest_price - r.prev_price
    return f"{'down' if diff < 0 else 'up'} ${abs(diff)} from ${r.prev_price}"


def _main_cabin(r: TripResult) -> str:
    if r.main_cabin_price is not None:
        return f"${r.main_cabin_price}"
    return "unknown"


def _text_row(a: Alert) -> str:
    r = a.result
    parts = [
        f"${r.lowest_price}  {_dates(r)} into {r.trip.destination} ({r.trip.pattern.replace('-', '–')})",
        _change(r),
        f"Main Cabin {_main_cabin(r)}",
    ]
    if r.ground_cost:
        parts.append(f"${r.door_to_door} door to door")
    parts.append(f"leaves {_time(r.lowest.depart_time)}")
    return "  " + " · ".join(parts)


def _html_table(title: str, alerts: list[Alert], show_ground: bool) -> str:
    th = 'style="text-align:left;padding:6px 10px;border-bottom:1px solid #d9dce3;color:#5b6170;font-weight:normal;font-size:12px"'
    thr = th.replace("text-align:left", "text-align:right")
    td = 'style="padding:8px 10px;border-bottom:1px solid #eceef2;vertical-align:top"'
    tdr = td.replace("vertical-align:top", "vertical-align:top;text-align:right")
    head = [f"<th {th}>Dates</th>", f"<th {th}>Airport</th>", f"<th {thr}>Fare</th>", f"<th {th}>Change</th>", f"<th {thr}>Main Cabin</th>"]
    if show_ground:
        head.append(f"<th {thr}>Door to door</th>")
    rows = []
    for a in alerts:
        r = a.result
        change = _change(r)
        color = "#1f7a4d" if change.startswith("down") else ("#b42318" if change.startswith("up") else "#5b6170")
        cells = [
            f"<td {td}><strong>{escape(_dates(r))}</strong><br>"
            f"<span style=\"color:#5b6170;font-size:12px\">{escape(r.trip.pattern.replace('-', '–'))} · leaves {escape(_time(r.lowest.depart_time))}</span></td>",
            f"<td {td}>{escape(r.trip.destination)}</td>",
            f"<td {tdr}><strong style=\"font-size:16px\">${r.lowest_price}</strong></td>",
            f"<td {td}><span style=\"color:{color}\">{escape(change)}</span></td>",
            f"<td {tdr}>{escape(_main_cabin(r))}</td>",
        ]
        if show_ground:
            cells.append(f"<td {tdr}>${r.door_to_door}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        f'<h3 style="margin:24px 0 8px;font-size:15px">{escape(title)}</h3>'
        '<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:14px">'
        f"<tr>{''.join(head)}</tr>{''.join(rows)}</table>"
    )


def build_email(alerts: list[Alert], config: Config, run_url: str | None = None) -> EmailMessage:
    deals = [a for a in alerts if a.reason == "deal"]
    drops = [a for a in alerts if a.reason == "drop"]
    top = alerts[0].result
    subject = f"AA fare alert: ${top.lowest_price} {_dates(top)} into {top.trip.destination}"
    if len(alerts) > 1:
        subject += f" (+{len(alerts) - 1} more)"

    targets = "; ".join(r.target_label for r in config.routes) if len(config.routes) == 1 else "; ".join(f"{r.name}: {r.target_label}" for r in config.routes)
    deal_title = f"Deals: {targets}"
    drop_title = f"Dropped {config.drop_percent:.0f}% or more since the last scan"
    if config.drop_max_price:
        drop_title += f", now ${config.drop_max_price} or less"
    show_ground = any(a.result.ground_cost for a in alerts)

    # Plain text, for clients that don't show HTML
    text = []
    if deals:
        text += [deal_title + ":", *(_text_row(a) for a in deals), ""]
    if drops:
        text += [drop_title + ":", *(_text_row(a) for a in drops), ""]
    if config.dashboard_url:
        text.append(f"Dashboard: {config.dashboard_url}")
    if run_url:
        text.append(f"This scan: {run_url}")
    text.append("Prices are AA nonstop round trips from Google Flights. Confirm on aa.com before booking.")

    links = []
    if config.dashboard_url:
        links.append(f'<a href="{escape(config.dashboard_url)}" style="color:#1d4ed8">Open the dashboard</a>')
    if run_url:
        links.append(f'<a href="{escape(run_url)}" style="color:#1d4ed8">This scan</a>')
    html = [
        '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#1c1f26;max-width:680px">',
        f'<p style="margin:0 0 4px;font-size:15px">{len(deals)} new deal{"s" if len(deals) != 1 else ""}'
        f'{f" and {len(drops)} price drop" + ("s" if len(drops) != 1 else "") if drops else ""} on American nonstops from DFW.</p>',
    ]
    if deals:
        html.append(_html_table(deal_title, deals, show_ground))
    if drops:
        html.append(_html_table(drop_title, drops, show_ground))
    if links:
        html.append(f'<p style="margin:20px 0 0;font-size:14px">{" · ".join(links)}</p>')
    html.append(
        '<p style="margin:12px 0 0;color:#5b6170;font-size:12px">Prices are AA nonstop round trips from Google Flights. '
        "Main Cabin is the cheapest fare with Basic Economy excluded. Door to door adds a round-trip rideshare. "
        "Confirm on aa.com before booking.</p></div>"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg.set_content("\n".join(text))
    msg.add_alternative("".join(html), subtype="html")
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
