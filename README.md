# Flight Price Tracker

Finds the cheapest weekends to fly **American Airlines nonstop from DFW**, starting with New York (LGA, JFK, EWR).

For each of the next 12 weekends it prices three trip patterns — Fri–Sun, Thu–Mon, Sat–Tue — at every airport, twice:

1. the lowest AA nonstop fare (usually Basic Economy), and
2. the lowest AA nonstop fare **with Basic Economy excluded** (Main Cabin).

The difference is the real Main Cabin gap for that weekend. Each result also shows an estimate of the AAdvantage Loyalty Points a Main Cabin ticket would earn, since Basic Economy no longer earns any.

## Run it

**On GitHub (no install):** Actions tab → *Weekend fare scan* → *Run workflow*. The results appear in the run's summary, and the CSV/JSON are attached as an artifact. It also runs every Monday morning.

**Locally:**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

fare-finder scan                          # live Google Flights data, ~12 minutes
fare-finder scan --weekends 4             # quicker
fare-finder scan --csv output/fares.csv   # also save every result
fare-finder scan --provider sample        # made-up data, no network
pytest
```

A full scan is 108 trips × 2 searches. Searches are spaced 2 seconds apart (`--delay`) to stay polite to Google.

## Reading the output

- **Deals** — every trip at or below the route's `target_price`.
- **Weekend grid** — cheapest airport for each weekend × pattern. `*` marks a deal.
- **Lowest** is the cheapest AA nonstop round trip; **Main Cabin** is the cheapest with Basic excluded; **Gap** is the difference. A `~` means the Main Cabin search came back empty and the default gap was used.
- **Est. LP** = (Main Cabin price − ~$45 taxes) × 5, rounded. Change `lp_per_dollar` to 7 once you're Gold.

Prices come from Google Flights and usually match aa.com within a few dollars. Always confirm on aa.com before booking: cached availability can show a fare that has just sold out.

## Configure

Everything lives in [`config.yaml`](config.yaml): origin, airline, patterns, routes, airports, deal targets, blackout dates and Loyalty Points assumptions. To add a route:

```yaml
routes:
  - name: PIT
    destinations: [PIT]
    target_price: 250
```

## How it's built

```
src/fare_finder/
  config.py      config.yaml → typed settings
  weekends.py    weekends × patterns × airports → trips
  providers/     fare sources behind one interface
    fast_flights_provider.py   Google Flights via the free fast-flights library
    sample.py                  deterministic fake fares for tests
  scan.py        two searches per trip, gap, deal flag
  loyalty.py     Loyalty Points estimate
  report.py      text report, CSV, JSON
  cli.py         `fare-finder scan`
```

`fast-flights` is unofficial and can break if Google changes its page. If that happens, add a provider for a paid source (Apify or SerpApi) in `providers/` — nothing else needs to change.

## Roadmap

1. **MVP** (this) — local and GitHub Actions scans, text report, CSV.
2. **History** — store each run in Supabase, score weekends against their own price history, alert on drops.
3. **More routes** — Pittsburgh, Phoenix, Boston, Nashville, South Carolina via config.
4. **Status tracking** — Loyalty Points per booked trip against the 40,000 needed for Gold.
