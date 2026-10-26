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
    assert r.gap == 76 and not r.main_cabin_unknown
    assert r.lp_estimate == estimate_loyalty_points(389, CONFIG.loyalty) == 1720  # (389 - 45) x 5, nearest 10
    assert r.is_deal is False


def test_deal_flag_at_target():
    r = price_trip(TRIP, FakeProvider(lowest=[260], main=[300]), CONFIG)
    assert r.is_deal is True


def test_empty_main_cabin_search_is_retried_then_left_unknown():
    provider = FakeProvider(lowest=[300], main=[])
    r = price_trip(TRIP, provider, CONFIG)
    assert provider.calls == [False, True, True]  # one retry
    assert r.main_cabin_unknown and r.main_cabin_price is None and r.gap is None and r.lp_estimate is None
    assert r.lowest_price == 300  # the fare itself still counts


def test_main_cabin_retry_recovers_from_a_transient_empty_result():
    class FlakyMain(FakeProvider):
        def search(self, trip, airline, exclude_basic_economy):
            self.calls.append(exclude_basic_economy)
            if exclude_basic_economy and self.calls.count(True) == 1:
                return []  # first Main Cabin search: Google hiccup
            return [fare(619 if exclude_basic_economy else 295)]

    r = price_trip(TRIP, FlakyMain(lowest=[]), CONFIG)
    assert (r.lowest_price, r.main_cabin_price, r.gap, r.main_cabin_unknown) == (295, 619, 324, False)


def test_failed_main_cabin_search_keeps_lowest_and_reports_error():
    r = price_trip(TRIP, FakeProvider(lowest=[300], fail_main=True), CONFIG)
    assert r.lowest_price == 300 and r.main_cabin_unknown and r.error == "blocked"


def test_no_nonstop_retries_once_then_skips_main_cabin_search():
    provider = FakeProvider(lowest=[])
    r = price_trip(TRIP, provider, CONFIG)
    assert r.lowest is None and provider.calls == [False, False]


def test_lowest_fare_retry_recovers_from_a_transient_empty_result():
    class FlakyLowest(FakeProvider):
        def search(self, trip, airline, exclude_basic_economy):
            self.calls.append(exclude_basic_economy)
            if self.calls == [False]:
                return []  # first search: Google hiccup
            return [fare(405 if exclude_basic_economy else 295)]

    provider = FlakyLowest(lowest=[])
    r = price_trip(TRIP, provider, CONFIG)
    assert (r.lowest_price, r.main_cabin_price) == (295, 405)
    assert provider.calls == [False, False, True]


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


def test_door_to_door_picks_cheaper_airport_after_ground_costs():
    raw = {**RAW, "routes": [{**RAW["routes"][0], "ground_to": "West Village",
                              "ground": {"LGA": {"minutes": 35, "cost": 55}, "EWR": {"minutes": 50, "cost": 90}}}]}
    config = parse_config(raw)
    lga = Trip("NYC", "Thu-Mon", "DFW", "LGA", date(2027, 3, 13), date(2027, 3, 11), date(2027, 3, 15))
    ewr = Trip("NYC", "Thu-Mon", "DFW", "EWR", date(2027, 3, 13), date(2027, 3, 11), date(2027, 3, 15))
    r_lga = price_trip(lga, FakeProvider(lowest=[300], main=[360]), config)  # 300 + 110 = 410
    r_ewr = price_trip(ewr, FakeProvider(lowest=[260], main=[320]), config)  # 260 + 180 = 440
    assert (r_lga.door_to_door, r_ewr.door_to_door) == (410, 440)
    best = best_per_weekend_pattern([r_lga, r_ewr])
    assert best[("NYC", date(2027, 3, 13), "Thu-Mon")].trip.destination == "LGA"
    text = render_text([r_lga, r_ewr], config, "fake", date(2027, 1, 4))
    assert "To West Village" in text and "door-to-door" in text


def test_ground_airport_must_be_a_destination():
    import pytest

    from fare_finder.config import ConfigError

    raw = {**RAW, "routes": [{**RAW["routes"][0], "ground": {"BOS": {"minutes": 10, "cost": 5}}}]}
    with pytest.raises(ConfigError):
        parse_config(raw)


def test_main_cabin_target_makes_a_deal_only_when_measured():
    raw = {**RAW, "routes": [{**RAW["routes"][0], "target_price": 299, "main_cabin_target": 399}]}
    config = parse_config(raw)
    r = price_trip(TRIP, FakeProvider(lowest=[320], main=[395]), config)
    assert (r.deal_basic, r.deal_main, r.is_deal) == (False, True, True)
    r = price_trip(TRIP, FakeProvider(lowest=[298], main=[420]), config)
    assert (r.deal_basic, r.deal_main) == (True, False)
    r = price_trip(TRIP, FakeProvider(lowest=[320], main=[]), config)  # unknown Main Cabin: never a Main deal
    assert r.main_cabin_unknown and not r.is_deal
    assert config.routes[0].target_label == "$299 (any fare) or $399 (Main Cabin)"
