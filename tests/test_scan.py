from datetime import date

from fare_finder.config import parse_config
from fare_finder.loyalty import estimate_loyalty_points
from fare_finder.models import FareOption, Trip
from fare_finder.providers.base import ProviderError
from fare_finder.providers.sample import SampleProvider
from fare_finder.report import render_text, to_rows
from fare_finder.scan import best_per_weekend_pattern, price_trip, run_scan
from fare_finder.weekends import generate_trips

from test_weekends import RAW

CONFIG = parse_config(RAW)
TRIP = Trip("NYC", "Thu-Mon", "DFW", "LGA", date(2027, 3, 13), date(2027, 3, 11), date(2027, 3, 15))


def fare(price):
    return FareOption(price=price, airlines=("American",), depart_time="06:08", arrive_time="10:30")


class FakeProvider:
    name = "fake"

    def __init__(self, lowest, main=None, fail_main=False):
        self.lowest, self.main, self.fail_main = lowest, main, fail_main
        self.calls = []

    def search(self, trip, airline, exclude_basic_economy):
        self.calls.append(exclude_basic_economy)
        if exclude_basic_economy:
            if self.fail_main:
                raise ProviderError("blocked")
            return [fare(p) for p in self.main or []]
        return [fare(p) for p in self.lowest]


def test_measured_gap_and_loyalty_points():
    r = price_trip(TRIP, FakeProvider(lowest=[313, 340], main=[389, 420]), CONFIG)
    assert r.lowest_price == 313
    assert r.main_cabin_price == 389
    assert r.gap == 76 and not r.gap_estimated
    assert r.lp_estimate == estimate_loyalty_points(389, CONFIG.loyalty) == 1720  # (389 - 45) x 5, nearest 10
    assert r.is_deal is False


def test_deal_flag_at_target():
    r = price_trip(TRIP, FakeProvider(lowest=[260], main=[300]), CONFIG)
    assert r.is_deal is True


def test_empty_main_cabin_search_uses_default_gap():
    r = price_trip(TRIP, FakeProvider(lowest=[300], main=[]), CONFIG)
    assert r.gap_estimated is True
    assert r.main_cabin_price == 300 + CONFIG.loyalty.main_cabin_gap_default


def test_failed_main_cabin_search_keeps_lowest_and_reports_error():
    r = price_trip(TRIP, FakeProvider(lowest=[300], fail_main=True), CONFIG)
    assert r.lowest_price == 300 and r.gap_estimated and r.error == "blocked"


def test_no_nonstop_skips_second_search():
    provider = FakeProvider(lowest=[])
    r = price_trip(TRIP, provider, CONFIG)
    assert r.lowest is None and provider.calls == [False]


def test_sample_scan_end_to_end():
    trips = generate_trips(CONFIG, today=date(2027, 1, 4))
    results = run_scan(trips, SampleProvider(), CONFIG)
    assert len(results) == len(trips) == 18
    best = best_per_weekend_pattern(results)
    assert all(b.lowest_price == min(r.lowest_price for r in results if r.lowest_price and (r.trip.route, r.trip.weekend, r.trip.pattern) == k) for k, b in best.items())
    text = render_text(results, CONFIG, "sample", date(2027, 1, 4))
    assert "Cheapest AA nonstop by weekend" in text and "made up" in text
    assert {row["airport"] for row in to_rows(results)} == {"LGA", "JFK", "EWR"}


def test_fast_flights_query_sets_filters():
    from fast_flights.pb.flights_pb2 import Info

    from fare_finder.providers.fast_flights_provider import FastFlightsProvider

    q = FastFlightsProvider().build_query(TRIP, "AA", exclude_basic_economy=True)
    info = Info.FromString(q.to_bytes())
    assert info.exclude_basic_economy is True
    assert [(d.date, d.from_airport.airport, d.to_airport.airport) for d in info.data] == [
        ("2027-03-11", "DFW", "LGA"),
        ("2027-03-15", "LGA", "DFW"),
    ]
    assert all(list(d.airlines) == ["AA"] and d.max_stops == 0 for d in info.data)
