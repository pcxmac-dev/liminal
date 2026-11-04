"""A stock listed outside the US (the user, 2026-11-02: "add exchanges where applicable and symbols"):
stored once as TICKER.SUFFIX with its exchange, filled over its exchange's own days (a Tokyo trading
day that is a US holiday), never re-pinned to a US exchange, its day bars the local calendar days
stamped at midnight ET of the local date, and left alone by the bad-data scans built on New York
sessions."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from liminal_libs import baddata, collector, derive
from liminal_libs.config import Tier
from liminal_libs.models import Exchange, Stock, country
from liminal_libs.sessions import ET
from liminal_libs.symbols import resolve

from .conftest import FakeSource

TIER = Tier("twse", requests_per_minute=10, history_years=None, history_start=date(2026, 11, 23))  # a Monday
NOW = datetime(2026, 11, 28, 12, 0, tzinfo=ET)  # Saturday noon: the week is over, Friday's day is published
THANKSGIVING = date(2026, 11, 26)


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=ET).timestamp() * 1000)


def _day_bar(d: date, px: float) -> dict:
    return {"t": _ms(d), "o": px, "h": px + 1, "l": px - 1, "c": px + 0.5, "v": 1000, "vw": px, "n": 10}


def test_a_listing_abroad_is_filled_over_its_own_days_including_a_us_holiday(store):
    days = [date(2026, 11, 23) + timedelta(days=i) for i in range(5)]  # Monday to Friday, Thanksgiving among them
    src = FakeSource(entitled=("day",), bars={"day": [_day_bar(d, 100 + i) for i, d in enumerate(days)]})
    store.watch_spec("fake", resolve("7203.T"), "day")  # a feed of daily bars (TWSE's, B3's)
    (row,) = store.watchlist("fake")
    assert row["ticker"] == "7203.T" and row["exchange"] == "XTKS" and row["asset"] == "stock"
    collector.sync(src, store, TIER, NOW, log=lambda m: None)
    (row,) = store.watchlist("fake")
    assert row["synced_at"] is not None and row["resolution"] == "day"
    assert store.bar_range("fake", "7203.T", "day") == (_ms(days[0]), _ms(days[-1]))
    assert all(start.date() <= THANKSGIVING <= end.date() for _, start, end, _, _ in src.bar_calls)  # the holiday asked for


def test_a_listing_abroad_keeps_its_exchange_when_a_source_lists_it_elsewhere(store):
    store.watch_spec("fake", resolve("7203.T"))
    src = FakeSource(listing=Stock("7203.T", name="Toyota Motor", list_date=date(1949, 5, 16), figi="BBG000BCM915",
                                   primary_exchange=Exchange("fake", 4, "Nasdaq", country("US"), mic="XNAS")))
    item = store.watchlist("fake", "7203.T")[0]
    lines = []
    listing = collector.check_listing(src, store, item, date(2026, 11, 2), log=lines.append)
    assert listing.listed_from == date(1949, 5, 16)
    (row,) = store.watchlist("fake", "7203.T")
    assert row["exchange"] == "XTKS" and row["listed_from"] == date(1949, 5, 16) and row["name"] == "Toyota Motor"
    assert row["figi"] == "BBG000BCM915" and store.details("fake", "7203.T")  # its identity recorded, not moved to Nasdaq
    assert any("keeps its exchange here" in line for line in lines)


def _minutes(start: datetime, n: int) -> pd.DataFrame:
    rows = pd.DataFrame([{"t": int((start + timedelta(minutes=i)).timestamp() * 1000), "o": 100 + i, "h": 101 + i,
                          "l": 99 + i, "c": 100.5 + i, "v": 1, "vw": 100 + i, "n": 1} for i in range(n)])
    rows["ts"], rows["time"] = rows["t"], pd.to_datetime(rows["t"], unit="ms", utc=True).dt.tz_convert(ET)
    return rows.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "vw": "vwap",
                                "n": "transactions"})


def test_day_bars_of_a_listing_abroad_are_its_local_days_stamped_at_midnight_new_york():
    # 09:00-09:59 Tokyo on Thursday 2026-11-26 is Wednesday 19:00-19:59 in New York
    m = _minutes(datetime(2026, 11, 25, 19, 0, tzinfo=ET), 60)
    (day,) = derive.aggregate(m, "day", 1, "stock", "XTKS")
    assert day["t"] == _ms(THANKSGIVING) and day["o"] == 100 and day["c"] == 159.5 and day["v"] == 60
    assert derive.aggregate(m, "day", 1, "stock") == []  # a US stock: outside the regular session
    (hour,) = derive.aggregate(m, "hour", 1, "stock", "XTKS")
    assert hour["t"] == int(datetime(2026, 11, 25, 19, 0, tzinfo=ET).timestamp() * 1000)


def test_the_live_view_names_listings_abroad_as_end_of_day_without_a_session_feed(store):
    from datetime import timezone

    from liminal_charts.gui import activity
    from liminal_libs.config import load_settings

    store.watch("massive", ["AAPL"], "minute", exchange="XNAS")
    store.watch_spec("twse", resolve("2330.TW"), "day")
    store.watch_spec("tiingo", resolve("600519.SS"), "day")
    out = activity.live_feeds(store, load_settings(env={"MASSIVE_API_KEY": "k"}, env_file=None), "massive",
                              datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc))
    rows = {f["asset"]: f for f in out["feeds"]}
    assert rows["stock"]["symbols"] == ["AAPL"] and rows["abroad"]["symbols"] == ["2330.TW", "600519.SS"]
    assert not rows["abroad"]["available"] and not rows["abroad"]["recording"]
    assert "no current-session feed" in rows["abroad"]["note"] and rows["abroad"]["delay"].startswith("end of day")


def test_a_request_is_put_under_the_stored_ticker_however_it_is_typed(tmp_path):
    from types import SimpleNamespace

    from liminal_charts.gui.server import ChartApp, stored_ticker
    from liminal_libs.config import load_settings
    from liminal_libs.storage import Store

    assert stored_ticker("TWSE:2330") == "2330.TW" and stored_ticker("SPCX::NASDAQ") == "SPCX" and stored_ticker("EUR/USD") == "EURUSD"
    s = Store(tmp_path / "m.db", check_same_thread=False)
    try:
        app = ChartApp(s, settings=load_settings(env={"MASSIVE_API_KEY": "k"}, env_file=None),
                       fetcher=SimpleNamespace(wake_up=lambda: None, ask_pass=lambda: None, status=lambda: {}))
        first = app.request_symbol({"symbol": "twse:2330", "kinds": ["bars"], "by": "page"})
        again = app.request_symbol({"symbol": "2330::XTAI", "kinds": ["bars"], "by": "page"})
        assert first["symbol"] == "2330.TW" and again["id"] == first["id"]  # one request, asked anew
        assert [r["symbol"] for r in s.request_rows()] == ["2330.TW"]
    finally:
        s.close()


def test_the_bad_data_scans_leave_a_listing_abroad_alone(store):
    bars, evidence = baddata.inconsistent(store, "fake", "7203.T", "day", _ms(date(2026, 11, 23)), _ms(date(2026, 11, 28)),
                                          "stock", "XTKS")
    assert bars.empty and evidence == []
