"""Tiingo's forex (tiingo (forex), a feed of the Tiingo plugin, in its package): the app's sync fills a
pair from 2020 through yesterday, inverted as the watch row shows it."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from liminal.config import load_settings
from liminal.sources import build_source


class FakeTiingo:
    """Answers /tiingo/fx/prices with a bar every 6 hours of the days asked (and one outside them)."""

    def __init__(self):
        self.asked = []
        self.requests_made = 0

    def get(self, path, params):
        self.asked.append((path, dict(params)))
        self.requests_made += 1
        d, last = date.fromisoformat(params["startDate"]), date.fromisoformat(params["endDate"])
        rows = []
        while d <= last:
            for h in (0, 6, 12, 18):
                t = datetime(d.year, d.month, d.day, h, tzinfo=timezone.utc)
                rows.append({"date": t.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "ticker": params["tickers"],
                             "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15})
            d += timedelta(days=1)
        return rows


def test_a_sync_fills_a_pair_from_2020_inverted_as_shown_through_the_day_before(store):
    from liminal.collector import sync
    from liminal.coverage import FeedProfile
    from liminal.symbols import resolve

    settings = load_settings(env={"TIINGO_API_KEY": "k", "TIINGO_PLAN": "power"}, env_file=None)
    tier = settings.for_source("tiingofx").tier
    store.watch_spec("tiingofx", resolve("USDEUR"), "minute")  # shown as USD/EUR: Tiingo's eurusd inverted
    client = FakeTiingo()
    source = build_source("tiingofx", settings)  # the plugin's source, from its package
    source.client = client
    now = datetime(2020, 1, 10, 12, tzinfo=timezone.utc)
    sync(source, store, tier, now, log=lambda *_: None,
         feeds={"tiingofx": FeedProfile("tiingofx", tier, frozenset({"fx"}), 1, venues={"fx": "tiingofx"})})
    asked = [(p["startDate"], p["endDate"]) for _, p in client.asked]
    assert asked and {p["tickers"] for _, p in client.asked} == {"eurusd"}
    assert min(a for a, _ in asked) == "2020-01-01" and max(b for _, b in asked) <= "2020-01-09"  # whole days to yesterday
    lo = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    bars = store.bars_window(["tiingofx"], "USDEUR", "minute", lo, lo + 10 * 86_400_000, filtered=False)
    # every day held, inverted; the history floor's day starts at New York midnight, so 00:00 UTC on
    # 1 January (New Year's Day: the market shut) is before it
    assert len(bars) == 9 * 4 - 1 and abs(bars["close"].iloc[0] - 1 / 1.15) < 1e-9
    assert abs(bars["high"].iloc[0] - 1 / 1.0) < 1e-9 and abs(bars["low"].iloc[0] - 1 / 1.2) < 1e-9
