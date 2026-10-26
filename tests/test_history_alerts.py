from datetime import date, datetime, timedelta, timezone

from fare_finder.alerts import build_email, choose_alerts
from fare_finder.cli import finish
from fare_finder.config import parse_config
from fare_finder.history import annotate
from fare_finder.models import FareOption, Trip, TripResult
from fare_finder.storage import MemoryStore, Observation, SentAlert, StorageError

from test_weekends import RAW

CONFIG = parse_config(RAW)  # target $260, drop 15%
T0 = datetime(2027, 1, 4, 13, 37, tzinfo=timezone.utc)


def trip(depart_day=11, airport="LGA"):
    d = date(2027, 3, depart_day)
    return Trip("NYC", "Thu-Mon", "DFW", airport, date(2027, 3, 13), d, d + timedelta(days=4))


def result(price, t=None, prev=None):
    r = TripResult(trip=t or trip(), lowest=FareOption(price, ("American",), "06:08", "10:30"))
    r.main_cabin_price, r.gap, r.lp_estimate = price + 60, 60, (price + 15) * 5
    r.is_deal = price <= 260
    r.prev_price = prev
    return r


def test_annotate_uses_this_trips_history_only():
    t, other = trip(), trip(airport="JFK")
    obs = [
        Observation(t.key, T0 - timedelta(days=14), 340),
        Observation(t.key, T0 - timedelta(days=7), 320),
        Observation(other.key, T0 - timedelta(days=7), 199),
    ]
    r = result(280, t)
    annotate([r], obs)
    assert (r.prev_price, r.prior_low, r.prior_median, r.prior_count) == (320, 320, 330, 2)
    assert round(r.change_pct, 1) == -12.5


def test_deal_alert_sent_once_until_it_gets_cheaper():
    r = result(255)
    assert [a.reason for a in choose_alerts([r], CONFIG, [])] == ["deal"]
    sent = [SentAlert(r.trip.key, "deal", 255, T0)]
    assert choose_alerts([result(255)], CONFIG, sent) == []        # same fare: no repeat
    assert choose_alerts([result(250)], CONFIG, sent) == []        # only $5 cheaper: no repeat
    assert len(choose_alerts([result(244)], CONFIG, sent)) == 1    # $11 cheaper: email again


def test_drop_alert_needs_15_percent():
    assert choose_alerts([result(300, prev=340)], CONFIG, []) == []      # -11.8%
    alerts = choose_alerts([result(285, prev=340)], CONFIG, [])          # -16.2%
    assert [a.reason for a in alerts] == ["drop"]


def test_email_lists_deals_then_drops():
    alerts = choose_alerts([result(285, trip(18), prev=340), result(249, trip(11))], CONFIG, [])
    msg = build_email(alerts, CONFIG, "https://github.com/x/y/actions/runs/1")
    assert msg["Subject"].startswith("AA fare alert: $249 Thu-Mon Mar 11 into LGA (+1 more)")
    body = msg.get_content()
    assert body.index("At or below your target") < body.index("Dropped 15%+")
    assert "was $340 last scan (-16%)" in body and "actions/runs/1" in body


def test_finish_saves_history_and_only_logs_alerts_that_were_emailed(monkeypatch):
    store = MemoryStore()
    sent_messages = []
    monkeypatch.setattr("fare_finder.cli.send_email", lambda msg: sent_messages.append(msg) or "me@example.com")

    r = result(249)
    finish([r], CONFIG, "fast-flights", date(2027, 1, 4), store, "send", run_id="42")
    assert len(sent_messages) == 1
    assert len(store.observations) == 1 and store.observations[0]["run_id"] == "42"
    assert [a["price"] for a in store.alerts] == [249]

    # Next week, same fare: history is used, no second email
    r2 = result(249)
    finish([r2], CONFIG, "fast-flights", date(2027, 1, 11), store, "send")
    assert r2.prev_price == 249 and len(sent_messages) == 1

    # Print mode never records alerts
    finish([result(240)], CONFIG, "fast-flights", date(2027, 1, 18), store, "print")
    assert len(store.alerts) == 1


def test_finish_survives_storage_outage(monkeypatch):
    class DownStore(MemoryStore):
        def history(self, route, depart_from):
            raise StorageError("HTTP 503")

    text, alerts = finish([result(249)], CONFIG, "fast-flights", date(2027, 1, 4), DownStore(), "off")
    assert "Deals at or below $260" in text and len(alerts) == 1
