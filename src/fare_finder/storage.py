"""Price history in Supabase, over its REST API (PostgREST).

Uses only the standard library. Needs two environment variables:
  SUPABASE_URL         e.g. https://abcd1234.supabase.co
  SUPABASE_SECRET_KEY  the project's secret (service role) key — never a public key

Tables are public.fare_observations and public.fare_alerts (see
supabase/migrations/), readable only with the secret key.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

PAGE = 1000


@dataclass(frozen=True)
class Observation:
    trip_key: str
    scanned_at: datetime
    lowest_price: int


@dataclass(frozen=True)
class SentAlert:
    trip_key: str
    reason: str
    price: int
    sent_at: datetime


class StorageError(RuntimeError):
    pass


class Store(Protocol):
    def history(self, route: str, depart_from: date) -> list[Observation]: ...
    def sent_alerts(self, since: date) -> list[SentAlert]: ...
    def save_observations(self, rows: list[dict]) -> None: ...
    def save_alerts(self, rows: list[dict]) -> None: ...


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class SupabaseStore:
    def __init__(self, url: str, key: str, timeout: float = 30):
        self.base = url.rstrip("/") + "/rest/v1"
        self.key = key
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> SupabaseStore | None:
        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SECRET_KEY")
        return cls(url, key) if url and key else None

    def _headers(self, write: bool) -> dict[str, str]:
        h = {
            "apikey": self.key,
            "Content-Type": "application/json",
        }
        if self.key.startswith("eyJ"):  # legacy JWT keys also go in Authorization; new sb_secret_ keys must not
            h["Authorization"] = f"Bearer {self.key}"
        if write:
            h["Prefer"] = "return=minimal"
        return h

    def _request(self, method: str, table: str, params: dict | None = None, body: list | None = None):
        url = f"{self.base}/{table}"
        if params:
            url += "?" + urllib.parse.urlencode(params, safe=",.()*")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers(write=body is not None))
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            raise StorageError(f"{method} {table}: HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise StorageError(f"{method} {table}: {exc.reason}") from exc
        return json.loads(raw) if raw else None

    def _select_all(self, table: str, params: dict) -> list[dict]:
        rows: list[dict] = []
        while True:
            page = self._request("GET", table, {**params, "limit": PAGE, "offset": len(rows)})
            rows.extend(page)
            if len(page) < PAGE:
                return rows

    def history(self, route: str, depart_from: date) -> list[Observation]:
        rows = self._select_all(
            "fare_observations",
            {
                "select": "trip_key,scanned_at,lowest_price",
                "route": f"eq.{route}",
                "depart": f"gte.{depart_from.isoformat()}",
                "lowest_price": "not.is.null",
                "order": "scanned_at.asc,id.asc",
            },
        )
        return [Observation(r["trip_key"], _ts(r["scanned_at"]), r["lowest_price"]) for r in rows]

    def sent_alerts(self, since: date) -> list[SentAlert]:
        rows = self._select_all(
            "fare_alerts",
            {"select": "trip_key,reason,price,sent_at", "sent_at": f"gte.{since.isoformat()}", "order": "sent_at.asc,id.asc"},
        )
        return [SentAlert(r["trip_key"], r["reason"], r["price"], _ts(r["sent_at"])) for r in rows]

    def save_observations(self, rows: list[dict]) -> None:
        for i in range(0, len(rows), 500):
            self._request("POST", "fare_observations", body=rows[i : i + 500])

    def save_alerts(self, rows: list[dict]) -> None:
        if rows:
            self._request("POST", "fare_alerts", body=rows)


class MemoryStore:
    """In-memory store for tests and dry runs."""

    def __init__(self):
        self.observations: list[dict] = []
        self.alerts: list[dict] = []

    def history(self, route: str, depart_from: date) -> list[Observation]:
        return [
            Observation(r["trip_key"], _ts(r["scanned_at"]), r["lowest_price"])
            for r in self.observations
            if r["route"] == route and date.fromisoformat(r["depart"]) >= depart_from and r["lowest_price"] is not None
        ]

    def sent_alerts(self, since: date) -> list[SentAlert]:
        return [
            SentAlert(r["trip_key"], r["reason"], r["price"], _ts(r["sent_at"]))
            for r in self.alerts
            if _ts(r["sent_at"]).date() >= since
        ]

    def save_observations(self, rows: list[dict]) -> None:
        self.observations.extend(rows)

    def save_alerts(self, rows: list[dict]) -> None:
        self.alerts.extend(rows)
