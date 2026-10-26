from datetime import date

from fare_finder.config import parse_config
from fare_finder.weekends import depart_for, generate_trips, upcoming_saturdays

RAW = {
    "origin": "DFW",
    "weekends_ahead": 2,
    "min_days_out": 3,
    "patterns": [
        {"name": "Fri-Sun", "depart": "Friday", "nights": 2},
        {"name": "Thu-Mon", "depart": "Thursday", "nights": 4},
        {"name": "Sat-Tue", "depart": "Saturday", "nights": 3},
    ],
    "routes": [{"name": "NYC", "destinations": ["LGA", "JFK", "EWR"], "target_price": 260}],
}


def test_upcoming_saturdays_starts_this_week():
    # Mon Oct 26, 2026 -> Sat Oct 31
    assert upcoming_saturdays(date(2026, 10, 26), 2) == [date(2026, 10, 31), date(2026, 11, 7)]
    # A Saturday counts as its own weekend
    assert upcoming_saturdays(date(2026, 10, 31), 1) == [date(2026, 10, 31)]


def test_depart_for_patterns():
    sat = date(2027, 3, 13)
    assert depart_for(sat, 3) == date(2027, 3, 11)  # Thursday
    assert depart_for(sat, 4) == date(2027, 3, 12)  # Friday
    assert depart_for(sat, 5) == sat                # Saturday
    assert depart_for(sat, 6) == date(2027, 3, 14)  # Sunday


def test_generate_trips_counts_and_dates():
    config = parse_config(RAW)
    trips = generate_trips(config, today=date(2026, 10, 19))  # Monday, so this week's Thursday is 3 days out
    # 2 weekends x 3 patterns x 3 airports
    assert len(trips) == 18
    thu_mon = [t for t in trips if t.pattern == "Thu-Mon" and t.destination == "LGA"]
    assert [(t.depart, t.return_date) for t in thu_mon] == [
        (date(2026, 10, 22), date(2026, 10, 26)),
        (date(2026, 10, 29), date(2026, 11, 2)),
    ]


def test_min_days_out_and_blackouts_skip_trips():
    raw = {**RAW, "routes": [{**RAW["routes"][0], "blackout_dates": ["2026-10-30"]}]}
    config = parse_config(raw)
    trips = generate_trips(config, today=date(2026, 10, 21))  # Wednesday: Thursday is only 1 day out
    departs = {(t.pattern, t.depart) for t in trips}
    assert ("Thu-Mon", date(2026, 10, 22)) not in departs  # too soon
    assert ("Fri-Sun", date(2026, 10, 30)) not in departs  # blacked out
    assert ("Sat-Tue", date(2026, 10, 24)) in departs
