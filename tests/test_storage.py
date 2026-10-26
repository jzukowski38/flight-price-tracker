import io
import json
from datetime import date

import pytest

from fare_finder import storage
from fare_finder.storage import StorageError, SupabaseStore


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def capture(monkeypatch, pages):
    calls = []
    pages = list(pages)

    def fake_urlopen(req, timeout):
        calls.append(req)
        body = pages.pop(0) if pages else []
        return FakeResponse(json.dumps(body).encode() if body is not None else b"")

    monkeypatch.setattr(storage.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_history_query_and_paging(monkeypatch):
    monkeypatch.setattr(storage, "PAGE", 2)
    row = {"trip_key": "k", "scanned_at": "2027-01-04T13:37:00+00:00", "lowest_price": 300}
    calls = capture(monkeypatch, [[row, row], [row]])
    obs = SupabaseStore("https://x.supabase.co/", "sb_secret_abc").history("NYC", date(2027, 1, 4))

    assert len(obs) == 3 and obs[0].lowest_price == 300
    assert len(calls) == 2
    url = calls[0].full_url
    assert url.startswith("https://x.supabase.co/rest/v1/fare_observations?")
    assert "route=eq.NYC" in url and "depart=gte.2027-01-04" in url and "lowest_price=not.is.null" in url
    assert "offset=0" in url and "offset=2" in calls[1].full_url
    headers = {k.lower(): v for k, v in calls[0].header_items()}
    assert headers["apikey"] == "sb_secret_abc"
    assert "authorization" not in headers  # new secret keys must not be sent as a Bearer token


def test_legacy_jwt_key_also_sent_as_bearer(monkeypatch):
    calls = capture(monkeypatch, [[]])
    SupabaseStore("https://x.supabase.co", "eyJhbGciOi.legacy").sent_alerts(date(2026, 7, 1))
    headers = {k.lower(): v for k, v in calls[0].header_items()}
    assert headers["authorization"] == "Bearer eyJhbGciOi.legacy"
    assert "/rest/v1/fare_alerts?" in calls[0].full_url


def test_insert_batches_rows(monkeypatch):
    calls = capture(monkeypatch, [None, None])
    SupabaseStore("https://x.supabase.co", "sb_secret_abc").save_observations([{"n": i} for i in range(600)])
    assert [len(json.loads(c.data)) for c in calls] == [500, 100]
    assert all(c.get_method() == "POST" and c.full_url.endswith("/fare_observations") for c in calls)
    assert {k.lower(): v for k, v in calls[0].header_items()}["prefer"] == "return=minimal"


def test_http_error_becomes_storage_error(monkeypatch):
    import urllib.error

    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"message":"Invalid API key"}'))

    monkeypatch.setattr(storage.urllib.request, "urlopen", boom)
    with pytest.raises(StorageError, match="HTTP 401.*Invalid API key"):
        SupabaseStore("https://x.supabase.co", "bad").history("NYC", date(2027, 1, 4))
